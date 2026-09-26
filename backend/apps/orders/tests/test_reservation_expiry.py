"""Proof for hard feature #2 (Reservation expiry TTL) and its race against a
concurrent webhook confirming payment (hard feature #5, graceful failure).
"""

import threading
from datetime import timedelta

import pytest
from django import db
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


@pytest.mark.django_db(transaction=True)
def test_webhook_and_expiry_race_on_the_same_order_without_deadlocking():
    """confirm_reservation() and expire_single_reservation() both lock
    Reservation then Order (see confirm_reservation's docstring) precisely so
    that firing both at once on the same order - a webhook landing at the
    exact moment the beat sweep decides that order is expired - serializes
    instead of deadlocking. If they ever locked in opposite order again,
    Postgres would detect the deadlock and abort one side with a
    django.db.utils.OperationalError instead of either thread completing
    cleanly - which is exactly the failure mode this test would catch.
    """
    product = ProductFactory(stock=5, reserved=0)
    user = UserFactory()
    order = begin_checkout(user, [(product.id, 2)])
    reservation = order.reservations.get()
    reservation.expires_at = timezone.now() - timedelta(minutes=1)
    reservation.save(update_fields=["expires_at"])

    barrier = threading.Barrier(2)
    errors = []

    def run_confirm():
        try:
            barrier.wait(timeout=5)
            confirm_reservation(order, source="webhook")
        except Exception as exc:  # noqa: BLE001 - a deadlock surfaces here
            errors.append(exc)
        finally:
            db.connections.close_all()

    def run_expiry():
        try:
            barrier.wait(timeout=5)
            expire_single_reservation(reservation.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.connections.close_all()

    threads = [threading.Thread(target=run_confirm), threading.Thread(target=run_expiry)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "a thread is still blocked - looks like a deadlock"
    assert errors == [], f"race produced an exception instead of clean serialization: {errors}"

    order.refresh_from_db()
    reservation.refresh_from_db()
    product.refresh_from_db()

    # Whichever side won, the result must be one consistent, valid outcome -
    # never a mix (e.g. order PAID but reservation EXPIRED, or stock released
    # for an order that's actually paid).
    if order.status == Order.Status.PAID:
        assert reservation.status == Reservation.Status.CONFIRMED
        assert product.reserved == 2
    else:
        assert order.status == Order.Status.EXPIRED
        assert reservation.status == Reservation.Status.EXPIRED
        assert product.reserved == 0
