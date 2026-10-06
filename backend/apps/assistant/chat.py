"""The function-calling loop: send the conversation to Gemini, and if it
asks to call a tool, run the real backend function, feed the result back,
and repeat until it answers in plain text. A manual loop rather than the
SDK's automatic-function-calling helper so the exact request/response at
each turn stays visible and auditable - not magic.

BEGINNER MAP OF THIS FILE: this is the only file that actually talks to
Gemini (the AI model). "Function calling" means the AI isn't just typing
text back - it can ask US to run one of a fixed set of real functions (see
apps/assistant/tools.py for what those are: search_products,
get_order_status, add_to_cart), see the real result, and use that in its
reply. The AI never touches the database directly - it only ever sees
whatever our own Python code in tools.py chooses to hand back to it.
"""

from django.conf import settings
from google.genai import errors, types

from apps.assistant.gemini_client import get_client
from apps.assistant.tools import TOOL_DECLARATIONS, TOOL_IMPLEMENTATIONS

# This exact wording is sent to Gemini on every single chat request,
# telling it how to behave. The last two sentences about plain text exist
# because of a real bug: without them, Gemini's replies contained literal
# "**bold**" asterisk characters, since the chat UI on the frontend doesn't
# render Markdown formatting - it just shows whatever text comes back, as-is.
SYSTEM_INSTRUCTION = """You are the shopping assistant for Reservly, a flash-sale
storefront. Help the shopper find products, check their own order status, and add
items to their cart. Use the tools available to you rather than guessing at
product names, prices, or order statuses - only state facts a tool actually
returned. Prices are in INR - always format them as e.g. "₹3,499", never
as a bare number or with a currency code after it. Keep replies brief and
conversational. Reply in
plain text only - the chat UI does not render Markdown, so never use **bold**,
bullet/numbered list syntax, or other formatting; use plain sentences instead."""

# A safety limit: the conversation loop below can go back and forth with
# Gemini calling tools at most this many times before giving up and
# returning a "couldn't finish" message, instead of looping forever if the
# model keeps asking for more tool calls indefinitely.
MAX_TOOL_ROUNDS = 4


def run_chat(message, history, user, session):
    """history: list of {"role": "user"|"model", "text": str} from earlier
    turns in this conversation (the frontend keeps and resends it - no
    server-side session state for the chat itself).

    BEGINNER NOTE: "no server-side session state for the chat" means our
    backend doesn't remember what you said 2 messages ago on its own - the
    FRONTEND sends the whole conversation history again, every single
    time, and this function rebuilds the full picture from that each call.
    """
    client = get_client()
    # tool_context carries the ACTUAL logged-in user and session into the
    # real tool functions (tools.py) - this is what lets get_order_status
    # correctly scope its database query to "orders belonging to THIS
    # user" rather than trusting anything the AI model itself might claim.
    tool_context = {"user": user, "session": session}

    # Rebuild the conversation so far into the shape Gemini's API expects -
    # a list of "who said what" turns, oldest first.
    contents = [
        types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])]) for turn in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        # Telling Gemini exactly which functions it's allowed to ask us to
        # run, and what arguments each one takes - see tools.py's
        # TOOL_DECLARATIONS for the actual list. The AI can ONLY ask for
        # one of these three; it cannot invent a new function to call.
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
    )

    tool_calls_made = []

    # THE ACTUAL LOOP: ask Gemini something, and if it wants a tool run,
    # run it for real and feed the result back as a new turn, repeating up
    # to MAX_TOOL_ROUNDS times. This keeps going until Gemini replies with
    # plain text instead of a tool request (handled by the `if not
    # function_calls:` check below), or we hit the round limit.
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.models.generate_content(
                model=settings.GEMINI_CHAT_MODEL, contents=contents, config=config
            )
        except errors.APIError as exc:
            # A quota/rate-limit hit or a Gemini-side outage shouldn't 500 the
            # request - the chat is a nice-to-have layered on top of a working
            # store, not something the rest of the app depends on.
            if getattr(exc, "code", None) == 429:
                reply = "I'm getting a lot of requests right now - please try again in a minute."
            else:
                reply = "I'm having trouble reaching the assistant right now. Please try again shortly."
            return {"reply": reply, "tool_calls": tool_calls_made, "degraded": True}

        candidate = response.candidates[0]
        # Gemini's reply can contain a mix of plain text AND requests to
        # call tools - this line pulls out just the tool-call requests, if
        # any. If this list is empty, Gemini answered directly with no
        # tool needed.
        function_calls = [
            part.function_call for part in candidate.content.parts if part.function_call
        ]

        if not function_calls:
            # No tool requested - Gemini's `response.text` is the final
            # answer, done.
            return {"reply": response.text, "tool_calls": tool_calls_made}

        # Gemini asked for one or more tools - add its own request to the
        # conversation history first (so the next call to Gemini has full
        # context of what it asked for), then actually run each requested
        # tool for real.
        contents.append(candidate.content)
        response_parts = []
        for call in function_calls:
            # Look up the REAL Python function matching the tool name
            # Gemini asked for (see tools.py's TOOL_IMPLEMENTATIONS dict),
            # and actually run it with the arguments Gemini supplied, plus
            # our own trusted tool_context (the real user/session - never
            # supplied by the AI itself).
            impl = TOOL_IMPLEMENTATIONS.get(call.name)
            result = impl(tool_context, **call.args) if impl else {"error": f"Unknown tool {call.name}"}
            tool_calls_made.append({"name": call.name, "args": dict(call.args), "result": result})
            # Package the REAL result (not anything the AI made up) to feed
            # back to Gemini on the next loop iteration.
            response_parts.append(types.Part.from_function_response(name=call.name, response=result))
        contents.append(types.Content(role="user", parts=response_parts))

    # Only reached if MAX_TOOL_ROUNDS was used up without Gemini ever
    # settling on a plain-text answer.
    return {
        "reply": "I wasn't able to finish that - could you rephrase or ask something simpler?",
        "tool_calls": tool_calls_made,
    }
