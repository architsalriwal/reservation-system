"""The three functions the assistant can actually call. Each is a real
call into existing backend logic (search.semantic_search, the orders
models, the storefront cart) - the LLM never touches the database or cart
state directly, it only ever gets back what these functions choose to
return.
"""

from google.genai import types

from apps.assistant.search import semantic_search
from apps.orders.models import Order
from apps.storefront import cart as cart_ops
from apps.catalog.models import Product


def _search_products(context, query, max_price=None):
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
    user = context["user"]
    if not user or not user.is_authenticated:
        return {"error": "You need to be logged in to check an order's status."}
    try:
        order = Order.objects.get(pk=order_id, user=user)
    except (Order.DoesNotExist, ValueError):
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
    if product.available < quantity:
        return {"error": f"Only {product.available} of '{product.name}' available."}
    cart_ops.add_item(session, product.id, quantity)
    return {"added": product.name, "quantity": quantity}


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

TOOL_IMPLEMENTATIONS = {
    "search_products": _search_products,
    "get_order_status": _get_order_status,
    "add_to_cart": _add_to_cart,
}
