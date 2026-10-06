"""Cart is deliberately just a {product_id: quantity} dict in the Django
session - no DB model, no cart-owned checkout logic. This sidesteps the old
project's central bug: a cart app that grew its own half-implemented Order
concept. Stock is never touched here; it's only ever mutated by
apps.orders.services.begin_checkout at the point of checkout.

BEGINNER NOTE: every function below takes `session` as its first argument
instead of reading some global/shared cart. `session` is Django's built-in
per-visitor storage, tied to the visitor's browser via a cookie - it's
already unique to whoever is making the request, so there's no risk of one
user's cart leaking into another's. None of these functions talk to the
database at all - "the cart" really is just this plain dictionary sitting
in `session["cart"]`, nothing more. Compare this file's total lack of
locking/transactions with apps/orders/services.py's begin_checkout() - that
contrast IS the point: nothing here needs to be airtight, because nothing
here commits you to anything yet.
"""

SESSION_KEY = "cart"


def get_cart(session):
    # Falls back to an empty dict if nothing's been added yet - so callers
    # never have to separately handle "cart doesn't exist" as a special case.
    return session.get(SESSION_KEY, {})


def add_item(session, product_id, quantity):
    cart = get_cart(session)
    # Session data gets serialized (turned into a storable format, e.g.
    # JSON) under the hood, and JSON object keys are always text - so the
    # product id is converted to a string here to keep the key type
    # consistent every time, whether this is the first time this product
    # was added or the tenth.
    key = str(product_id)
    cart[key] = cart.get(key, 0) + quantity
    # Session changes don't save themselves just by mutating the dict in
    # memory - re-assigning session[SESSION_KEY] is what tells Django "this
    # key changed, please persist it" when the response is sent back.
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
    # Called by apps/orders/views.py's CheckoutView right after a checkout
    # attempt finishes (success or failure alike) - see that file's own
    # comment on why an extra explicit session.save() is needed right after
    # calling this, which was a real bug found through testing.
    session[SESSION_KEY] = {}
