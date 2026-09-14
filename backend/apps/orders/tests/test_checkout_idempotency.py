"""Proof for the checkout-idempotency-key pattern from CLAUDE.md's "Patterns
worth building" list: a retried checkout request (flaky network, a
double-click that slips past the disabled button) must never create a
second order for the same logical attempt.

Same claim-before-mutate design as the Stripe webhook's idempotency
guarantee (test_webhook_idempotency.py) - the DB unique constraint on
(user, key), not an app-level check, is what actually prevents the race.
"""

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django import db
from rest_framework.test import APIClient

from apps.orders.models import CheckoutIdempotencyKey, Order
from apps.orders.tests.factories import ProductFactory, UserFactory

FAKE_SESSION = SimpleNamespace(url="https://checkout.stripe.com/fake-session")


def _authed_client_with_cart_item(product, quantity=1):
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    client.post("/api/cart/items/", {"product_id": product.id, "quantity": quantity}, format="json")
    return client, user


@pytest.mark.django_db
def test_checkout_requires_idempotency_key_header():
    product = ProductFactory(price=10, stock=5)
    client, _ = _authed_client_with_cart_item(product)

    resp = client.post("/api/checkout/")

    assert resp.status_code == 400
    assert Order.objects.count() == 0


@pytest.mark.django_db
def test_retrying_same_idempotency_key_after_success_returns_same_order():
    product = ProductFactory(price=10, stock=5)
    client, _ = _authed_client_with_cart_item(product)

    with patch("stripe.checkout.Session.create", return_value=FAKE_SESSION):
        first = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="retry-key-1")
        # Re-add to cart to prove the retry does NOT create a second order
        # even though the cart could plausibly be checked out again.
        client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
        second = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="retry-key-1")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["order"]["id"] == second.data["order"]["id"]
    assert Order.objects.count() == 1


@pytest.mark.django_db
def test_different_idempotency_keys_create_different_orders():
    product = ProductFactory(price=10, stock=5)
    client, _ = _authed_client_with_cart_item(product)

    with patch("stripe.checkout.Session.create", return_value=FAKE_SESSION):
        first = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="key-a")
        client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
        second = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="key-b")

    assert first.data["order"]["id"] != second.data["order"]["id"]
    assert Order.objects.count() == 2


@pytest.mark.django_db
def test_out_of_stock_releases_the_key_so_a_retry_can_succeed():
    product = ProductFactory(price=10, stock=1)
    client, user = _authed_client_with_cart_item(product, quantity=2)

    resp = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="oos-key")
    assert resp.status_code == 409
    assert not CheckoutIdempotencyKey.objects.filter(user=user, key="oos-key").exists()

    # Fix the cart and retry with the SAME key - must not be blocked by a
    # stale claim from the failed attempt.
    client.patch(f"/api/cart/items/{product.id}/", {"quantity": 1}, format="json")
    with patch("stripe.checkout.Session.create", return_value=FAKE_SESSION):
        retry = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="oos-key")

    assert retry.status_code == 201
    assert Order.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_with_same_idempotency_key_creates_exactly_one_order():
    """The actual concurrency proof: N threads submit the identical
    (user, key) pair simultaneously. Exactly one must win the DB unique
    constraint and create an order; every other thread must get back
    that same winner's order or a 409 - never a second order.
    """
    product = ProductFactory(price=10, stock=20)
    user = UserFactory()

    # Cart is session-scoped, so each thread needs its OWN client with its
    # own populated session cart - set that up sequentially first. The
    # property under test (DB uniqueness of (user, key)) doesn't care that
    # these are technically different sessions; what matters is that every
    # thread is a real, individually-fundable checkout attempt racing on
    # the same idempotency key.
    clients = []
    for _ in range(10):
        client = APIClient()
        client.force_authenticate(user=user)
        client.post("/api/cart/items/", {"product_id": product.id, "quantity": 1}, format="json")
        clients.append(client)

    results = []
    lock = threading.Lock()

    def attempt(client):
        resp = client.post("/api/checkout/", HTTP_IDEMPOTENCY_KEY="concurrent-shared-key")
        db.connections.close_all()
        with lock:
            results.append((resp.status_code, resp.data))

    # Patched once around the whole race, not inside each thread: patch()
    # swaps the attribute on __enter__/__exit__, which isn't safe to do
    # concurrently from multiple threads each with their own context.
    with patch("stripe.checkout.Session.create", return_value=FAKE_SESSION):
        threads = [threading.Thread(target=attempt, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # Every response is either the created order (201) or a 409 telling the
    # caller a request with this key is already in flight - never a crash,
    # never a distinct second order.
    assert all(status in (201, 409) for status, _ in results)
    order_ids = {data["order"]["id"] for status, data in results if status == 201}
    assert len(order_ids) == 1
    assert Order.objects.filter(user=user).count() == 1
