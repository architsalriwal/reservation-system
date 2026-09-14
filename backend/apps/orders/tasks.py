from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders.models import Order, Reservation, StripeEvent
from apps.orders.redis_client import write_through_available
from apps.orders.services import handle_stripe_event, transition_order_status

# Real fulfillment takes days; this is a demo, and the whole point of
# showing this off is watching the order-status page update live without
# refreshing, so the steps are seconds apart instead.
FULFILLMENT_STEP_DELAY_SECONDS = 8


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


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_order_confirmation_email(self, order_id):
    """One of two independent consumers of the "order placed" event (see
    apps.orders.events) - runs on its own, retried on its own. A slow or
    down email provider can never block the checkout response (this task
    is enqueued, not awaited) or affect start_fulfillment below.
    """
    try:
        order = Order.objects.select_related("user").get(pk=order_id)
    except Order.DoesNotExist:
        return

    if not order.user or not order.user.email:
        return

    try:
        send_mail(
            subject=f"Order confirmed - {order.id}",
            message=(
                f"Thanks for your order!\n\nTotal: {order.currency} {order.total_amount}\n"
                f"Order ID: {order.id}\n\nWe'll let you know as it ships."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.user.email],
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3)
def start_fulfillment(self, order_id):
    """The other independent consumer of the same event. Immediately moves
    a paid order into processing, then schedules the remaining stages as
    delayed follow-up tasks rather than sleeping in-process - a worker
    isn't blocked holding this task for the full fulfillment duration.
    """
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return

    if order.status != Order.Status.PAID:
        return  # moved on already (e.g. a refund/cancellation) - don't force it backward

    transition_order_status(order, Order.Status.PROCESSING, source="fulfillment")
    advance_fulfillment.apply_async(
        args=[order_id, Order.Status.SHIPPED], countdown=FULFILLMENT_STEP_DELAY_SECONDS
    )


@shared_task(bind=True, max_retries=3)
def advance_fulfillment(self, order_id, next_status):
    """transition_order_status() itself no-ops on a non-transition, so this
    is safe to run more than once for the same step if Celery ever
    redelivers it - not a special case added just for this task.
    """
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return

    if order.status in (Order.Status.CANCELED, Order.Status.EXPIRED):
        return

    transition_order_status(order, next_status, source="fulfillment")

    if next_status == Order.Status.SHIPPED:
        advance_fulfillment.apply_async(
            args=[order_id, Order.Status.DELIVERED], countdown=FULFILLMENT_STEP_DELAY_SECONDS
        )


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
