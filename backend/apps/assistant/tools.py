"""The three functions the assistant can actually call. Each is a real
call into existing backend logic (search.semantic_search, the orders
models, the storefront cart) - the LLM never touches the database or cart
state directly, it only ever gets back what these functions choose to
return.

BEGINNER MAP OF THIS FILE: two parallel lists below that must stay matched
up. TOOL_DECLARATIONS is what gets SENT TO Gemini - a description of each
tool's name and what arguments it takes, written in a format the AI model
understands, so it knows what it's allowed to ask for. TOOL_IMPLEMENTATIONS
is the REAL Python function that actually runs when Gemini asks for that
tool by name - see apps/assistant/chat.py's run_chat() for where this
mapping actually gets used. The three `_search_products` /
`_get_order_status` / `_add_to_cart` functions are the real work; everything
below them is just metadata describing those functions to the AI.
"""

from google.genai import types

from apps.assistant.search import semantic_search
from apps.orders.models import Order
from apps.storefront import cart as cart_ops
from apps.catalog.models import Product


def _search_products(context, query, max_price=None):
    # The actual "search by meaning" work happens in search.py, not here -
    # see that file for what semantic_search() does. This function's own
    # job is just: call it, optionally filter by price, and shape the
    # result into plain data (a dict of basic types) that can be safely
    # sent back to the AI model and eventually turned into JSON.
    results = semantic_search(query, limit=5)
    if max_price is not None:
        results = [p for p in results if float(p.price) <= float(max_price)]
    return {
        "products": [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "price": str(p.price),
                "currency": p.currency,
                "available": p.available,
            }
            for p in results
        ]
    }


def _get_order_status(context, order_id):
    # `context` is the tool_context dict built in chat.py's run_chat() -
    # carrying the REAL logged-in user, never anything the AI model
    # itself claims about who's asking.
    user = context["user"]
    if not user or not user.is_authenticated:
        return {"error": "You need to be logged in to check an order's status."}
    try:
        # THE SECURITY-CRITICAL LINE: `user=user` is part of the query
        # itself, not a separate check done after fetching the order. If
        # someone asks about an order ID that isn't theirs, this query
        # simply finds NOTHING (it doesn't match both conditions at once) -
        # there's no code path where another user's order data could
        # accidentally get returned here.
        order = Order.objects.get(pk=order_id, user=user)
    except (Order.DoesNotExist, ValueError):
        # ValueError is caught too because order_id might not even be a
        # validly-formatted ID at all (e.g. if the AI or user typos it) -
        # without catching that, a malformed ID would crash this function
        # instead of returning a normal, friendly "not found" response.
        return {"error": "No order with that ID found on your account."}
    return {
        "order_id": str(order.id),
        "status": order.status,
        "total_amount": str(order.total_amount),
        "currency": order.currency,
    }


def _add_to_cart(context, product_slug, quantity=1):
    session = context["session"]
    try:
        product = Product.objects.get(slug=product_slug, is_active=True)
    except Product.DoesNotExist:
        return {"error": f"No product found with slug '{product_slug}'."}
    # Even here, in a chat-assistant convenience function, the real
    # available-stock number is still checked before adding - though note
    # this is only a friendly heads-up, not the real stock guarantee. The
    # real, airtight check still only happens later, at actual checkout
    # (apps/orders/services.py's begin_checkout()) - same as the regular
    # "Add to cart" button on the catalog page.
    if product.available < quantity:
        return {"error": f"Only {product.available} of '{product.name}' available."}
    # Calls the EXACT SAME cart function the regular "Add to cart" button
    # uses (apps/storefront/cart.py's add_item) - the AI doesn't get its
    # own special cart-writing code path, it goes through the same real
    # function as everything else.
    cart_ops.add_item(session, product.id, quantity)
    return {"added": product.name, "quantity": quantity}


# Sent to Gemini on every chat request (see chat.py's run_chat()) so it
# knows what tools exist and exactly what arguments each one needs. This is
# ONLY a description/schema - calling types.FunctionDeclaration(...) here
# does NOT run any code; it just builds a structured description that gets
# handed to the AI model.
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="search_products",
        description="Search the product catalog by meaning, not just keywords - e.g. 'something for running' matches running shoes even without the word 'shoes'.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(type=types.Type.STRING, description="What the shopper is looking for."),
                "max_price": types.Schema(
                    type=types.Type.NUMBER, description="Optional upper price bound in INR."
                ),
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_order_status",
        description="Look up the current status of one of the logged-in user's own orders by its ID.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"order_id": types.Schema(type=types.Type.STRING)},
            required=["order_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="add_to_cart",
        description="Add a product to the shopper's cart by its slug.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "product_slug": types.Schema(type=types.Type.STRING),
                "quantity": types.Schema(type=types.Type.INTEGER),
            },
            required=["product_slug"],
        ),
    ),
]

# The REAL functions, keyed by the exact same names used in
# TOOL_DECLARATIONS above. When Gemini asks to call "search_products",
# chat.py looks up TOOL_IMPLEMENTATIONS["search_products"] and gets back
# the actual _search_products function to run. The names in both places
# have to match exactly, or a requested tool would silently fail to be
# found.
TOOL_IMPLEMENTATIONS = {
    "search_products": _search_products,
    "get_order_status": _get_order_status,
    "add_to_cart": _add_to_cart,
}
