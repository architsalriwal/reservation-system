# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# The shopping cart in this project deliberately does NOT require being
# logged in - it's a session dict, not a database table - so anonymous
# visitors can browse and add things to their cart, and login is only
# required once they actually try to check out. That's why there's no
# force_authenticate() call here, unlike most of the orders/accounts
# tests: this APIClient is making genuinely anonymous requests, on
# purpose, and Django's session cookie machinery is what keeps "the same
# cart" across the three requests below.
#
# One straightforward test, walking through the cart's full lifecycle:
# add an item, update its quantity, then remove it - checking the running
# total recalculates correctly at each step.
# ============================================================================

import pytest
from rest_framework.test import APIClient

from apps.orders.tests.factories import ProductFactory


@pytest.mark.django_db
def test_add_update_remove_cart_item():
    product = ProductFactory(price=10, stock=5)
    client = APIClient()

    resp = client.post("/api/cart/items/", {"product_id": product.id, "quantity": 2}, format="json")
    assert resp.status_code == 201
    assert resp.data["total"] == "20.00"
    assert len(resp.data["items"]) == 1

    resp = client.patch(f"/api/cart/items/{product.id}/", {"quantity": 3}, format="json")
    assert resp.status_code == 200
    assert resp.data["total"] == "30.00"

    resp = client.delete(f"/api/cart/items/{product.id}/")
    assert resp.status_code == 200
    assert resp.data["items"] == []
