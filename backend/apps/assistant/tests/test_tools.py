from unittest.mock import patch

import pytest

from apps.assistant.tools import TOOL_IMPLEMENTATIONS
from apps.orders.services import begin_checkout
from apps.orders.tests.factories import ProductFactory, UserFactory
from apps.storefront import cart as cart_ops


class FakeSession(dict):
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
