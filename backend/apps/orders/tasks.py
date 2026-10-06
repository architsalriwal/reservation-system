# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# Everything in this file is a "Celery task" - a function that does NOT run
# immediately when something calls it. Instead it either (a) gets queued with
# .delay() / .apply_async() and picked up later by a separate background
# process (the "Celery worker"), or (b) gets run automatically on a repeating
# schedule (the "Celery beat" process - see config/celery.py's
# `app.conf.beat_schedule` for exactly when). Nothing in this file runs
# inside a normal web request/response cycle - a user clicking something
# never directly waits on any function here.
#
# Five tasks, two unrelated jobs:
#   1. expire_reservations / expire_single_reservation
#      - runs automatically every 60 seconds, releases stock nobody paid for.
#   2. send_order_confirmation_email / start_fulfillment / advance_fulfillment
#      - queued once, right after a real payment is confirmed (triggered from
#        apps/orders/events.py's dispatch_order_placed(), which itself is
#        called from apps/orders/services.py's confirm_reservation()).
#   3. sweep_unprocessed_stripe_events
#      - runs automatically every 1-2 minutes, finishes any webhook that got
#        "claimed" but never fully processed (e.g. the server crashed
#        mid-way) - see apps/orders/webhooks.py and services.py's
#        handle_stripe_event() for the claim-then-process pattern this
#        is cleaning up after.
# ============================================================================

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

    BEGINNER NOTE: "@shared_task" is what turns a normal Python function into
    something Celery knows how to run as a background job. Without it,
    calling .delay() on this function below wouldn't work at all - it's the
    decorator that registers this function with Celery.
    """
    # A "reservation" is a temporary hold on stock created at checkout time -
    # see apps/orders/services.py's begin_checkout() for where these get
    # created, and reservly-end-to-end-flows.md section 10 for the full
    # story. This query finds every hold whose time has run out.
    expired_ids = list(
        Reservation.objects.filter(
            status=Reservation.Status.ACTIVE, expires_at__lte=timezone.now()
        ).values_list("id", flat=True)
    )
    # Deliberately ONE small task PER expired reservation, instead of
    # looping through all of them right here in one go. Reason: if one
    # reservation happens to be locked by something else right now (say, a
    # payment confirming at this exact moment - see services.py's
    # confirm_reservation()), that one slow/stuck reservation would stall
    # the release of every OTHER expired reservation too if they were all
    # handled in a single block. Separate tasks mean one stuck row can't
    # hold up the rest.
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
    # Everything inside this `with` block is ONE atomic database transaction
    # - either every change below gets saved together, or (if anything
    # fails) none of it does. See services.py's begin_checkout() for a more
    # detailed explanation of what "atomic" and "select_for_update" mean if
    # this is your first time seeing them.
    with transaction.atomic():
        try:
            # select_for_update() = lock this specific row. Anyone else
            # trying to lock this same row (e.g. a webhook confirming
            # payment for this exact reservation) has to wait until this
            # transaction finishes.
            reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
        except Reservation.DoesNotExist:
            return

        # Re-check the real, current state NOW that we hold the lock -
        # things may have changed in the time between expire_reservations()
        # finding this row and this task actually getting a turn to run.
        if reservation.status != Reservation.Status.ACTIVE:
            return  # already confirmed or released elsewhere
        if reservation.expires_at > timezone.now():
            return  # renewed/raced, not actually expired anymore

        order = Order.objects.select_for_update().get(pk=reservation.order_id)
        if order.status != Order.Status.PENDING_PAYMENT:
            return  # order already progressed (paid/canceled) - don't touch it

        # The actual "give the stock back" step. This is the ONLY place in
        # the entire project where `reserved` ever goes back DOWN - compare
        # with begin_checkout() in services.py, where it only ever goes up.
        product = Product.objects.select_for_update().get(pk=reservation.product_id)
        product.reserved -= reservation.quantity
        product.save(update_fields=["reserved", "updated_at"])

        reservation.status = Reservation.Status.EXPIRED
        reservation.save(update_fields=["status"])

        # The single function allowed to change an order's status - see
        # services.py's transition_order_status() for why that rule exists
        # and what it does (writes a history row, pushes a live WebSocket
        # update to anyone watching this order's page).
        transition_order_status(order, Order.Status.EXPIRED, source="celery_beat")

    # This line runs AFTER the `with` block ends - meaning the lock above
    # has already been released and the change is already permanently
    # saved. Now that Postgres has the new, real number, copy it into Redis
    # too, so the next checkout's cheap pre-check (services.py's
    # begin_checkout) sees today's real number instead of a stale one.
    write_through_available(product.id, product.available)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_order_confirmation_email(self, order_id):
    """One of two independent consumers of the "order placed" event (see
    apps.orders.events) - runs on its own, retried on its own. A slow or
    down email provider can never block the checkout response (this task
    is enqueued, not awaited) or affect start_fulfillment below.

    BEGINNER NOTE: this function is never called directly by name anywhere.
    It only ever gets run because apps/orders/events.py's
    dispatch_order_placed() called `send_order_confirmation_email.delay(order_id)`
    - that queues it, and whenever the separate Celery worker process gets a
    free moment, IT calls this function for real, on its own schedule, not
    yours. "bind=True" just means this function gets access to itself (as
    `self`) so it can call `self.retry(...)` below.
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
        # Something went wrong sending the email (provider down, network
        # blip). self.retry() tells Celery "try this exact same task again
        # later" (up to max_retries=3 times, ~30s apart) instead of just
        # giving up - a temporary outage shouldn't mean the customer never
        # gets their confirmation email.
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
    # apply_async(..., countdown=8) means "run advance_fulfillment, but not
    # right now - wait 8 seconds first." This is NOT the same as
    # time.sleep(8) - this worker process is free to do other work in the
    # meantime; it just schedules a note for later instead of pausing here.
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

    # This one function handles BOTH remaining steps of the simulated
    # journey (processing -> shipped, then shipped -> delivered) by calling
    # itself again with the next status, 8 seconds later. When next_status
    # is DELIVERED, this `if` is false, nothing gets scheduled again, and
    # the chain naturally stops.
    if next_status == Order.Status.SHIPPED:
        advance_fulfillment.apply_async(
            args=[order_id, Order.Status.DELIVERED], countdown=FULFILLMENT_STEP_DELAY_SECONDS
        )


@shared_task
def sweep_unprocessed_stripe_events():
    """Beat task (every 1-2 min): recovers Stripe events whose claim-insert
    committed but whose mutation never finished (worker crash between the
    two). handle_stripe_event() is itself idempotent-safe to replay.

    BEGINNER NOTE: think of a StripeEvent row like a restaurant order
    ticket. apps/orders/webhooks.py "tears off the ticket" (saves a
    StripeEvent row) the moment a Stripe webhook arrives, THEN separately
    calls handle_stripe_event() (in services.py) to actually "cook the
    food" (mark the order paid). If the server crashes exactly between
    those two steps, the ticket exists but the food never got made -
    `processed_at` stays empty/null forever unless something notices. This
    task is that "something": a manager doing rounds, picking up any ticket
    that's been sitting unstarted for more than 2 minutes and finishing it.
    """
    cutoff = timezone.now() - timedelta(minutes=2)
    stuck = StripeEvent.objects.filter(processed_at__isnull=True, created_at__lt=cutoff)
    processed = 0
    for stripe_event in stuck:
        # Safe to call again even if this somehow already succeeded -
        # handle_stripe_event() checks the order's real current status
        # before changing anything, so "run it twice" and "run it once"
        # produce the exact same end result. Code written to behave safely
        # like this is called "idempotent" - you'll see this word a lot in
        # this codebase.
        handle_stripe_event(stripe_event)
        processed += 1
    return processed
