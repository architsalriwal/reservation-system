from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders.models import Order, Reservation, StripeEvent
from apps.orders.redis_client import write_through_available
from apps.orders.services import handle_stripe_event, transition_order_status


@shared_task
def expire_reservations():
    """Beat task (every 60s): finds ACTIVE reservations past their TTL and
    fans out to per-reservation release tasks, so one locked row can't stall
    the whole sweep.
    """
    expired_ids = list(
        Reservation.objects.filter(
            status=Reservation.Status.ACTIVE, expires_at__lte=timezone.now()
        ).values_list("id", flat=True)
    )
    for reservation_id in expired_ids:
        expire_single_reservation.delay(reservation_id)
    return len(expired_ids)


@shared_task(bind=True, max_retries=3)
def expire_single_reservation(self, reservation_id):
    """Releases one reservation's stock hold, unless a concurrent webhook
    already confirmed it or moved the order past pending_payment. Locking
    Reservation -> Order -> Product in the same order confirm_reservation()
    uses is what lets Postgres serialize this against that path instead of
    racing on which write wins.
    """
    with transaction.atomic():
        try:
            reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
        except Reservation.DoesNotExist:
            return

        if reservation.status != Reservation.Status.ACTIVE:
            return  # already confirmed or released elsewhere
        if reservation.expires_at > timezone.now():
            return  # renewed/raced, not actually expired anymore

        order = Order.objects.select_for_update().get(pk=reservation.order_id)
        if order.status != Order.Status.PENDING_PAYMENT:
            return  # order already progressed (paid/canceled) - don't touch it

        product = Product.objects.select_for_update().get(pk=reservation.product_id)
        product.reserved -= reservation.quantity
        product.save(update_fields=["reserved", "updated_at"])

        reservation.status = Reservation.Status.EXPIRED
        reservation.save(update_fields=["status"])

        transition_order_status(order, Order.Status.EXPIRED, source="celery_beat")

    write_through_available(product.id, product.available)


@shared_task
def sweep_unprocessed_stripe_events():
    """Beat task (every 1-2 min): recovers Stripe events whose claim-insert
    committed but whose mutation never finished (worker crash between the
    two). handle_stripe_event() is itself idempotent-safe to replay.
    """
    cutoff = timezone.now() - timedelta(minutes=2)
    stuck = StripeEvent.objects.filter(processed_at__isnull=True, created_at__lt=cutoff)
    processed = 0
    for stripe_event in stuck:
        handle_stripe_event(stripe_event)
        processed += 1
    return processed
