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


@pytest.mark.django_db
def test_checkout_clears_the_cart_even_when_stripe_fails():
    """Found via the circuit-breaker test below: a failed checkout must
    still clear the cart, or the same items silently reappear on the next
    checkout attempt and get reserved again on top of the old reservation.
    """
    product = ProductFactory(price=10, stock=20)
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    with patch("stripe.checkout.Session.create", side_effect=stripe.error.APIConnectionError("down")):
        client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
        client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="clear-key-1")

    cart_resp = client.get("/api/cart/")
    assert cart_resp.data["items"] == []


@pytest.mark.django_db
def test_checkout_stops_calling_stripe_after_repeated_failures():
    """The actual point of a circuit breaker over plain error handling:
    once it trips, the 6th request must not even attempt to call Stripe -
    a bare try/except would still call it every single time.
    """
    product = ProductFactory(price=10, stock=20)
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    with patch("stripe.checkout.Session.create", side_effect=stripe.error.APIConnectionError("down")):
        for i in range(5):
            client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
            resp = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY=f"breaker-key-{i}")
            assert resp.status_code == 502

    client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
    with patch("stripe.checkout.Session.create") as mock_create:
        resp = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="breaker-key-final")

    assert resp.status_code == 502
    mock_create.assert_not_called()  # the breaker rejected this before it ever reached Stripe
