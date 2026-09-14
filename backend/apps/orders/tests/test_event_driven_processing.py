"""Proof for CLAUDE.md's event-driven order processing pattern: paying for
an order fires one event, and two independent consumers - email and
fulfillment - handle it without either depending on or blocking the other.

Deliberately NOT tested here: inventory deduction becoming event-driven,
because it doesn't - see apps/orders/events.py's module docstring for why
moving it off the synchronous locked transaction would reopen the exact
overselling race this whole project exists to close.
"""

from unittest.mock import patch

import pytest
from django.core import mail

from apps.orders.models import Order, OrderStatusEvent
from apps.orders.services import begin_checkout, confirm_reservation, transition_order_status
from apps.orders.tasks import advance_fulfillment, send_order_confirmation_email, start_fulfillment
from apps.orders.tests.factories import ProductFactory, UserFactory


@pytest.mark.django_db(transaction=True)
def test_confirm_reservation_dispatches_both_consumers_independently():
    """Two separate .delay() calls, not one task invoking the other - that
    structural independence is what actually guarantees a broken email
    provider can never affect fulfillment, not a comment saying so.
    """
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])

    with patch("apps.orders.tasks.send_order_confirmation_email.delay") as mock_email, patch(
        "apps.orders.tasks.start_fulfillment.delay"
    ) as mock_fulfillment:
        confirm_reservation(order, source="webhook")

    mock_email.assert_called_once_with(order.id)
    mock_fulfillment.assert_called_once_with(order.id)


@pytest.mark.django_db
def test_send_order_confirmation_email_actually_sends():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory(email="buyer@example.com")
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")

    mail.outbox.clear()
    send_order_confirmation_email.apply(args=[order.id])

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["buyer@example.com"]
    assert str(order.id) in mail.outbox[0].body


@pytest.mark.django_db
def test_email_task_retries_on_send_failure_instead_of_crashing_silently():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory(email="buyer@example.com")
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")

    with patch("apps.orders.tasks.send_mail", side_effect=ConnectionError("SMTP down")):
        result = send_order_confirmation_email.apply(args=[order.id], throw=False)

    assert result.failed() or isinstance(result.result, Exception)


@pytest.mark.django_db
def test_start_fulfillment_moves_paid_order_to_processing_and_schedules_next_step():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")

    with patch("apps.orders.tasks.advance_fulfillment.apply_async") as mock_advance:
        start_fulfillment.apply(args=[order.id])

    order.refresh_from_db()
    assert order.status == Order.Status.PROCESSING
    mock_advance.assert_called_once_with(args=[order.id, Order.Status.SHIPPED], countdown=8)


@pytest.mark.django_db
def test_advance_fulfillment_progresses_shipped_then_delivered_and_stops():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")
    transition_order_status(order, Order.Status.PROCESSING, source="fulfillment")

    with patch("apps.orders.tasks.advance_fulfillment.apply_async") as mock_advance:
        advance_fulfillment.apply(args=[order.id, Order.Status.SHIPPED])
    order.refresh_from_db()
    assert order.status == Order.Status.SHIPPED
    mock_advance.assert_called_once_with(args=[order.id, Order.Status.DELIVERED], countdown=8)

    with patch("apps.orders.tasks.advance_fulfillment.apply_async") as mock_advance_again:
        advance_fulfillment.apply(args=[order.id, Order.Status.DELIVERED])
    order.refresh_from_db()
    assert order.status == Order.Status.DELIVERED
    mock_advance_again.assert_not_called()  # delivered is the end of the pipeline

    statuses = list(order.status_events.values_list("to_status", flat=True))
    assert statuses == ["paid", "processing", "shipped", "delivered"]


@pytest.mark.django_db
def test_fulfillment_does_not_force_a_canceled_order_forward():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")
    order.status = Order.Status.CANCELED
    order.save(update_fields=["status"])

    with patch("apps.orders.tasks.advance_fulfillment.apply_async") as mock_advance:
        advance_fulfillment.apply(args=[order.id, Order.Status.SHIPPED])

    order.refresh_from_db()
    assert order.status == Order.Status.CANCELED
    mock_advance.assert_not_called()


@pytest.mark.django_db
def test_start_fulfillment_is_a_noop_if_order_already_moved_on():
    """transition_order_status() no-ops on a non-transition by design - this
    proves start_fulfillment relies on that rather than duplicating the
    check, and that a redelivered task can't force a canceled order back
    into processing.
    """
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 1)])
    confirm_reservation(order, source="webhook")
    order.status = Order.Status.CANCELED
    order.save(update_fields=["status"])

    start_fulfillment.apply(args=[order.id])

    order.refresh_from_db()
    assert order.status == Order.Status.CANCELED
