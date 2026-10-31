# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# "Tools" here are the specific functions the Gemini AI assistant is
# allowed to call on a user's behalf (search products, check an order's
# status, add something to the cart) - TOOL_IMPLEMENTATIONS is a lookup
# dict mapping a tool's name to its real Python function, and these tests
# call those functions directly, the same way the assistant's own
# function-calling loop would, without needing a real AI model in the loop
# at all.
#
# The one test worth reading carefully is
# test_get_order_status_tool_is_scoped_to_the_requesting_user - it's the
# proof that the AI assistant can't be tricked into leaking a DIFFERENT
# user's order details just because it was asked to.
# ============================================================================

from unittest.mock import patch

import pytest

from apps.assistant.tools import TOOL_IMPLEMENTATIONS
from apps.orders.services import begin_checkout
from apps.orders.tests.factories import ProductFactory, UserFactory
from apps.storefront import cart as cart_ops


class FakeSession(dict):
    # A minimal stand-in for Django's real session object - the real one
    # has extra plumbing for things like talking to the database, but the
    # cart code under test here only ever treats the session like a plain
    # dictionary, so a plain dict subclass is all these tests need.
    pass


@pytest.mark.django_db
def test_search_products_tool_filters_by_max_price():
    cheap = ProductFactory(name="Budget Mug", price=200, embedding=[0.0] * 768)
    expensive = ProductFactory(name="Premium Mug", price=5000, embedding=[0.0] * 768)

    with patch("apps.assistant.tools.semantic_search", return_value=[cheap, expensive]):
        result = TOOL_IMPLEMENTATIONS["search_products"]({}, query="mug", max_price=1000)

    names = [p["name"] for p in result["products"]]
    assert names == ["Budget Mug"]


@pytest.mark.django_db
def test_get_order_status_tool_requires_login():
    from django.contrib.auth.models import AnonymousUser

    result = TOOL_IMPLEMENTATIONS["get_order_status"]({"user": AnonymousUser()}, order_id="x")
    assert "error" in result


@pytest.mark.django_db
def test_get_order_status_tool_is_scoped_to_the_requesting_user():
    owner = UserFactory()
    other_user = UserFactory()
    product = ProductFactory(stock=5)
    order = begin_checkout(owner, [(product.id, 1)])

    as_owner = TOOL_IMPLEMENTATIONS["get_order_status"]({"user": owner}, order_id=str(order.id))
    assert as_owner["status"] == "pending_payment"

    as_other = TOOL_IMPLEMENTATIONS["get_order_status"]({"user": other_user}, order_id=str(order.id))
    assert "error" in as_other


@pytest.mark.django_db
def test_add_to_cart_tool_adds_a_real_cart_item():
    product = ProductFactory(name="Widget", stock=5)
    session = FakeSession()

    result = TOOL_IMPLEMENTATIONS["add_to_cart"]({"session": session}, product_slug=product.slug, quantity=2)

    assert result["added"] == "Widget"
    assert cart_ops.get_cart(session) == {str(product.id): 2}


@pytest.mark.django_db
def test_add_to_cart_tool_rejects_insufficient_stock():
    product = ProductFactory(name="Widget", stock=1)
    session = FakeSession()

    result = TOOL_IMPLEMENTATIONS["add_to_cart"]({"session": session}, product_slug=product.slug, quantity=5)

    assert "error" in result
    assert cart_ops.get_cart(session) == {}
