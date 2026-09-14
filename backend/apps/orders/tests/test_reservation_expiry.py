"""Proof for hard feature #2 (Reservation expiry TTL) and its race against a
concurrent webhook confirming payment (hard feature #5, graceful failure).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders.models import Order, Reservation
from apps.orders.services import begin_checkout, confirm_reservation
from apps.orders.tasks import expire_single_reservation
from apps.orders.tests.factories import ProductFactory, UserFactory


@pytest.mark.django_db
def test_expired_reservation_releases_stock_and_marks_order_expired():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 2)])

    reservation = order.reservations.get()
    reservation.expires_at = timezone.now() - timedelta(minutes=1)
    reservation.save(update_fields=["expires_at"])

    expire_single_reservation(reservation.id)

    product.refresh_from_db()
    order.refresh_from_db()
    reservation.refresh_from_db()

    assert product.reserved == 0
    assert product.available == 5
    assert order.status == Order.Status.EXPIRED
    assert reservation.status == Reservation.Status.EXPIRED


@pytest.mark.django_db
def test_expiry_is_a_noop_once_webhook_already_confirmed_payment():
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 2)])
    reservation = order.reservations.get()

    # Webhook wins the race: payment confirmed before the sweep runs.
    confirm_reservation(order, source="webhook")

    reservation.expires_at = timezone.now() - timedelta(minutes=1)
    reservation.save(update_fields=["expires_at"])

    expire_single_reservation(reservation.id)

    product.refresh_from_db()
    order.refresh_from_db()
    reservation.refresh_from_db()

    # Expiry must not undo a payment that already landed.
    assert order.status == Order.Status.PAID
    assert reservation.status == Reservation.Status.CONFIRMED
    assert product.reserved == 2
