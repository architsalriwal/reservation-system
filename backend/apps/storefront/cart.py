"""Cart is deliberately just a {product_id: quantity} dict in the Django
session - no DB model, no cart-owned checkout logic. This sidesteps the old
project's central bug: a cart app that grew its own half-implemented Order
concept. Stock is never touched here; it's only ever mutated by
apps.orders.services.begin_checkout at the point of checkout.
"""

SESSION_KEY = "cart"


def get_cart(session):
    return session.get(SESSION_KEY, {})


def add_item(session, product_id, quantity):
    cart = get_cart(session)
    key = str(product_id)
    cart[key] = cart.get(key, 0) + quantity
    session[SESSION_KEY] = cart
    return cart


def set_item_quantity(session, product_id, quantity):
    cart = get_cart(session)
    key = str(product_id)
    if quantity <= 0:
        cart.pop(key, None)
    else:
        cart[key] = quantity
    session[SESSION_KEY] = cart
    return cart


def remove_item(session, product_id):
    cart = get_cart(session)
    cart.pop(str(product_id), None)
    session[SESSION_KEY] = cart
    return cart


def clear(session):
    session[SESSION_KEY] = {}
