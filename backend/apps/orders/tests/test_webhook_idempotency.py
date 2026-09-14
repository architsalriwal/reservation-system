"""Proof for hard feature #3 (Idempotent webhook handling) and #5 (graceful
failure recovery via the unprocessed-event sweep).
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.orders.models import Order, StripeEvent
from apps.orders.services import begin_checkout, handle_stripe_event
from apps.orders.tasks import sweep_unprocessed_stripe_events
from apps.orders.tests.factories import ProductFactory, UserFactory


def _claim_event(event_id, order_id, event_type="checkout.session.completed"):
    return StripeEvent.objects.create(
        stripe_event_id=event_id,
        event_type=event_type,
        order_id=order_id,
        payload={"id": event_id, "type": event_type},
    )


@pytest.mark.django_db
def test_duplicate_stripe_event_id_is_rejected_at_the_db_level():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    _claim_event("evt_dup_1", order.id)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _claim_event("evt_dup_1", order.id)

    assert StripeEvent.objects.filter(stripe_event_id="evt_dup_1").count() == 1


@pytest.mark.django_db
def test_handle_stripe_event_confirms_order_exactly_once_even_if_replayed():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    stripe_event = _claim_event("evt_replay_1", order.id)
    handle_stripe_event(stripe_event)

    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.status_events.filter(to_status=Order.Status.PAID).count() == 1

    # Replaying the same (already-processed) event must not create a second
    # PAID transition or otherwise double-apply the payment.
    handle_stripe_event(stripe_event)
    order.refresh_from_db()
    assert order.status_events.filter(to_status=Order.Status.PAID).count() == 1


@pytest.mark.django_db
def test_sweep_recovers_event_claimed_but_never_processed():
    """Simulates a worker crash: the claim-insert committed (so the row
    exists) but the process died before handle_stripe_event ran, leaving
    processed_at NULL. The recovery sweep should pick it up and converge.
    """
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    stripe_event = _claim_event("evt_crash_1", order.id)
    stripe_event.created_at = timezone.now() - timedelta(minutes=5)
    stripe_event.save(update_fields=["created_at"])

    assert stripe_event.processed_at is None
    order.refresh_from_db()
    assert order.status == Order.Status.PENDING_PAYMENT

    processed_count = sweep_unprocessed_stripe_events()

    stripe_event.refresh_from_db()
    order.refresh_from_db()
    assert processed_count == 1
    assert stripe_event.processed_at is not None
    assert order.status == Order.Status.PAID
