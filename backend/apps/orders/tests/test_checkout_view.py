"""Proof for hard feature #5's "Stripe timeout mid-transaction" scenario:
begin_checkout's reservation must survive a Stripe outage untouched, and the
endpoint must degrade (502, order still exists, stock still reserved under
its normal TTL) instead of crashing or losing the reservation.
"""

from unittest.mock import patch

import pytest
import stripe
from rest_framework.test import APIClient

from apps.orders.models import Order, Reservation
from apps.orders.tests.factories import ProductFactory, UserFactory


@pytest.mark.django_db
def test_checkout_degrades_gracefully_when_stripe_is_unreachable():
    product = ProductFactory(price=10, stock=5)
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")

    with patch("stripe.checkout.Session.create", side_effect=stripe.error.APIConnectionError("down")):
        resp = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="test-key-1")

    assert resp.status_code == 502
    assert resp.data["checkout_url"] is None

    order = Order.objects.get(pk=resp.data["order"]["id"])
    assert order.status == Order.Status.PENDING_PAYMENT

    reservation = Reservation.objects.get(order=order)
    assert reservation.status == Reservation.Status.ACTIVE

    product.refresh_from_db()
    assert product.reserved == 1  # the reservation is intact, not lost or doubled
