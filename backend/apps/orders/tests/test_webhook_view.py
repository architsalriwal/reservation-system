"""Exercises the actual StripeWebhookView.post() parsing path, not just the
service-layer handle_stripe_event() the other webhook tests cover. This is
the test that would have caught a real bug found via a live end-to-end
Stripe Checkout run: stripe.Webhook.construct_event() returns typed
StripeObjects (Session, Charge, PaymentIntent, ...), not plain dicts, so
.get() on event["data"]["object"] raised AttributeError for every single
real webhook delivery - 500s across the board - despite every other test
in this suite passing, because they all only ever exercised
handle_stripe_event() directly with hand-built plain-dict payloads.
"""

from unittest.mock import patch

import pytest
import stripe
from rest_framework.test import APIClient

from apps.orders.models import Order, StripeEvent
from apps.orders.tests.factories import ProductFactory, UserFactory
from apps.orders.services import begin_checkout


def _build_typed_event(event_id, event_type, order_id):
    """Mirrors what stripe.Webhook.construct_event() actually returns: a
    stripe.Event wrapping typed sub-objects, not nested plain dicts.
    """
    event_json = {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "api_version": "2025-05-28.basil",
        "created": 1700000000,
        "data": {
            "object": {
                "object": "checkout.session",
                "id": "cs_test_fixture",
                "metadata": {"order_id": str(order_id)},
            }
        },
    }
    return stripe.Event.construct_from(event_json, "sk_test_fixture")


@pytest.mark.django_db
def test_webhook_view_parses_real_typed_stripe_event_and_confirms_order():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    typed_event = _build_typed_event("evt_view_test_1", "checkout.session.completed", order.id)

    client = APIClient()
    with patch("stripe.Webhook.construct_event", return_value=typed_event):
        resp = client.post(
            "/api/webhooks/stripe/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="fake",
        )

    assert resp.status_code == 200
    assert StripeEvent.objects.filter(stripe_event_id="evt_view_test_1").exists()

    order.refresh_from_db()
    assert order.status == Order.Status.PAID


@pytest.mark.django_db
def test_webhook_view_deduplicates_real_typed_event_on_replay():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    typed_event = _build_typed_event("evt_view_test_2", "checkout.session.completed", order.id)

    client = APIClient()
    with patch("stripe.Webhook.construct_event", return_value=typed_event):
        first = client.post(
            "/api/webhooks/stripe/", data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="fake"
        )
        second = client.post(
            "/api/webhooks/stripe/", data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="fake"
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert StripeEvent.objects.filter(stripe_event_id="evt_view_test_2").count() == 1

    order.refresh_from_db()
    assert order.status_events.filter(to_status=Order.Status.PAID).count() == 1
