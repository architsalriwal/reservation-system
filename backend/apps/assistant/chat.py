"""The function-calling loop: send the conversation to Gemini, and if it
asks to call a tool, run the real backend function, feed the result back,
and repeat until it answers in plain text. A manual loop rather than the
SDK's automatic-function-calling helper so the exact request/response at
each turn stays visible and auditable - not magic.
"""

from django.conf import settings
from google.genai import types

from apps.assistant.gemini_client import get_client
from apps.assistant.tools import TOOL_DECLARATIONS, TOOL_IMPLEMENTATIONS

SYSTEM_INSTRUCTION = """You are the shopping assistant for Reservly, a flash-sale
storefront. Help the shopper find products, check their own order status, and add
items to their cart. Use the tools available to you rather than guessing at
product names, prices, or order statuses - only state facts a tool actually
returned. Prices are in INR. Keep replies brief and conversational. Reply in
plain text only - the chat UI does not render Markdown, so never use **bold**,
bullet/numbered list syntax, or other formatting; use plain sentences instead."""

MAX_TOOL_ROUNDS = 4


def run_chat(message, history, user, session):
    """history: list of {"role": "user"|"model", "text": str} from earlier
    turns in this conversation (the frontend keeps and resends it - no
    server-side session state for the chat itself).
    """
    client = get_client()
    tool_context = {"user": user, "session": session}

    contents = [
        types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])]) for turn in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
    )

    tool_calls_made = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=settings.GEMINI_CHAT_MODEL, contents=contents, config=config
        )
        candidate = response.candidates[0]
        function_calls = [
            part.function_call for part in candidate.content.parts if part.function_call
        ]

        if not function_calls:
            return {"reply": response.text, "tool_calls": tool_calls_made}

        contents.append(candidate.content)
        response_parts = []
        for call in function_calls:
            impl = TOOL_IMPLEMENTATIONS.get(call.name)
            result = impl(tool_context, **call.args) if impl else {"error": f"Unknown tool {call.name}"}
            tool_calls_made.append({"name": call.name, "args": dict(call.args), "result": result})
            response_parts.append(types.Part.from_function_response(name=call.name, response=result))
        contents.append(types.Content(role="user", parts=response_parts))

    return {
        "reply": "I wasn't able to finish that - could you rephrase or ask something simpler?",
        "tool_calls": tool_calls_made,
    }
