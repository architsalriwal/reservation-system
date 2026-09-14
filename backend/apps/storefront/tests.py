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
