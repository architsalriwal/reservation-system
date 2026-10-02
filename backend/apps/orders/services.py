from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders.events import dispatch_order_placed
from apps.orders.exceptions import OutOfStock
from apps.orders.models import Order, OrderItem, OrderStatusEvent, Reservation, StripeEvent
from apps.orders.redis_client import available_stock_key, get_redis, write_through_available
from apps.realtime.publish import publish_order_status


def begin_checkout(user, cart_items):
    """Reserve stock for a cart and create the pending order that holds it.

    cart_items: iterable of (product_id, quantity).

    Two requests racing for the last unit of stock: both may pass the Redis
    pre-check (it's advisory, not atomic), but only one acquires the Postgres
    row lock first and succeeds; the other re-checks availability under the
    lock and raises OutOfStock. Postgres is the source of truth; Redis only
    exists to reject clearly-doomed requests before they touch the database.

    BEGINNER WALKTHROUGH - this function is the whole overselling-prevention
    story in one place:

      1) Cheap, fast check in Redis first - this is just a quick glance at a
         cached number. It's allowed to be slightly wrong/out of date. Its
         only job is to instantly reject requests that are CLEARLY doomed
         (e.g. 1000 people asking for a sold-out item) without making the
         database do any work for them.
      2) For everyone who passes that quick glance, open ONE database
         transaction per checkout attempt and take a LOCK on the product row
         (select_for_update()). A "lock" here means: while I'm inside this
         block, nobody else is allowed to even READ this row for the purpose
         of writing to it - they have to wait in line until I'm done.
      3) While holding that lock, check the REAL, current stock number
         (not the cached Redis one) and decide, for real, whether there's
         enough. This is the only check that actually matters.
      4) If there's enough: take it (increase `reserved`), create the Order
         and a Reservation holding that stock, and finish.
      5) The lock is released the moment this transaction block ends. The
         next person waiting in line for the same product then gets to look
         at the real number themselves - which is now lower (or zero).
    """
    redis_conn = get_redis()

    # STEP 1 (see docstring above): the cheap pre-check. `cached` is just a
    # number we read from Redis - a snapshot that might already be a little
    # stale. If it clearly says "not enough," reject right here and never
    # even talk to the real database for this request.
    for product_id, quantity in cart_items:
        cached = redis_conn.get(available_stock_key(product_id))
        if cached is not None and quantity > int(cached):
            raise OutOfStock(product_id, quantity, int(cached))

    # How long this reservation holds the stock before it's automatically
    # released if the buyer never finishes paying (see tasks.py's
    # expire_reservations, which runs every minute looking for these).
    ttl = timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
    expires_at = timezone.now() + ttl

    # STEP 2-4: everything inside this `with` block runs as ONE atomic
    # database transaction - either ALL of it succeeds and is saved
    # permanently, or if anything raises an error partway through (like
    # OutOfStock below), NONE of it is saved - it's as if none of these
    # lines ever ran. This all-or-nothing behavior is why it's safe to
    # create the Order first and only find out about a stock problem later
    # in the loop - if that happens, the half-created Order is thrown away
    # automatically, not left behind as broken data.
    with transaction.atomic():
        order = Order.objects.create(user=user, status=Order.Status.PENDING_PAYMENT, placed_at=timezone.now())
        total_amount = 0
        locked_products = {}

        for product_id, quantity in cart_items:
            # THE ACTUAL LOCK. select_for_update() means: "give me this row,
            # and make everyone else who also wants to select_for_update()
            # this same row WAIT until my transaction finishes." This is
            # what makes it impossible for two requests to both see "1
            # available" and both take it - whoever gets here first makes
            # the second one simply wait, then see the updated, lower number.
            product = Product.objects.select_for_update().get(pk=product_id)

            # The REAL check, now that we hold the lock. `available` is
            # always `stock - reserved` (see catalog/models.py) - the true,
            # current, trustworthy number. This is the check that actually
            # decides who wins; the Redis check earlier was only ever a
            # cheap filter, never the real decision.
            if product.available < quantity:
                raise OutOfStock(product_id, quantity, product.available)

            # We're not reducing `stock` here - we're increasing `reserved`.
            # Think of `reserved` as "spoken for but not yet fully sold."
            # `available` (stock minus reserved) drops immediately, which is
            # what stops the NEXT buyer from also taking this unit.
            product.reserved += quantity
            product.version += 1
            product.save(update_fields=["reserved", "version", "updated_at"])
            locked_products[product_id] = product

            # unit_price_snapshot: we copy today's price onto this specific
            # order item right now. Even if the product's price changes
            # later, this order's total never silently changes with it.
            OrderItem.objects.create(
                order=order, product=product, quantity=quantity, unit_price_snapshot=product.price
            )
            # This Reservation row is the actual "hold" on the stock - it's
            # what the TTL-expiry task (tasks.py) looks for and releases if
            # the buyer never completes payment.
            Reservation.objects.create(
                order=order, product=product, quantity=quantity, expires_at=expires_at
            )
            total_amount += product.price * quantity

        order.total_amount = total_amount
        order.currency = next(iter(locked_products.values())).currency if locked_products else "INR"
        order.save(update_fields=["total_amount", "currency"])
    # <- transaction.atomic() block ends here: everything above this line is
    # now permanently saved, and the lock on each product row is released.

    # STEP 5's other half: now that Postgres has the real, final numbers,
    # push them into Redis too, so the NEXT request's cheap pre-check
    # (step 1) sees today's real numbers instead of yesterday's.
    for product in locked_products.values():
        write_through_available(product.id, product.available)

    return order


def transition_order_status(order, new_status, source):
    """The single writer of Order.status. No-ops on a non-transition, and
    publishes the WebSocket update only after the DB transaction commits —
    so a rolled-back transition is never announced to a client.

    BEGINNER NOTE: every single place in this codebase that ever needs to
    change an order's status calls THIS function - nothing anywhere else
    does `order.status = "paid"` directly. That's a deliberate rule, not an
    accident: it means there's exactly one place that can mess up a status
    change, one place that logs the history of every change, and one place
    that notifies the frontend over WebSocket - instead of that logic being
    copy-pasted (and inevitably drifting out of sync) in five different spots.
    """
    old_status = order.status
    # If the status isn't actually changing (e.g. some other field on the
    # order was updated and this got called out of habit/safety), do
    # nothing. Without this check, saving an order for an unrelated reason
    # could accidentally send a "status changed!" message to the frontend
    # for a status that didn't really change.
    if old_status == new_status:
        return order

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    # A permanent history row - every transition this order ever went
    # through is recorded here, which is what lets you debug "wait, how did
    # this order end up in this state?" after the fact.
    OrderStatusEvent.objects.create(
        order=order, from_status=old_status, to_status=new_status, source=source
    )
    # transaction.on_commit(...) means: don't send the WebSocket message
    # right now - wait until the surrounding database transaction has
    # ACTUALLY, successfully saved. If something later in the same
    # transaction fails and everything gets rolled back, this scheduled
    # message is simply never sent - so a client is never told about a
    # status change that, in the end, never really happened.
    transaction.on_commit(lambda: publish_order_status(str(order.id), old_status, new_status))
    return order


def confirm_reservation(order, source="webhook"):
    """Marks an order's active reservations CONFIRMED and the order PAID.

    Locks Reservation, then Order - the same order expire_single_reservation
    uses - so a webhook confirming payment and the expiry sweep releasing the
    same order's stock can never deadlock by each holding one lock and
    waiting on the other. (Neither path locks Product here: a paid order's
    `reserved` count is never given back, so there's nothing on Product for
    this function to touch - only the expiry path, which does release stock,
    needs that third lock.)

    Returns False (no-op) if the order already moved past pending_payment —
    e.g. it already expired, or this event was already processed.
    """
    with transaction.atomic():
        # Lock first, read the actual list of reservations second - we grab
        # the lock on these rows before deciding anything, same idea as the
        # product lock in begin_checkout above.
        reservations = list(
            Reservation.objects.select_for_update().filter(
                order_id=order.pk, status=Reservation.Status.ACTIVE
            )
        )
        order = Order.objects.select_for_update().get(pk=order.pk)
        # Someone else already moved this order on (most likely: it expired
        # just before this payment confirmation arrived). Don't try to
        # "un-expire" it - just report honestly whether it ended up paid.
        if order.status != Order.Status.PENDING_PAYMENT:
            return order.status == Order.Status.PAID

        # Reservation -> permanent. No stock number changes here at all -
        # `reserved` was already bumped up back in begin_checkout, and for
        # a successful sale it just stays that way forever.
        for reservation in reservations:
            reservation.status = Reservation.Status.CONFIRMED
            reservation.save(update_fields=["status"])

        transition_order_status(order, Order.Status.PAID, source=source)
        # Kick off the "send a confirmation email" and "start fulfillment"
        # background jobs - see events.py / tasks.py for what happens next.
        dispatch_order_placed(order.id)

    return True


def handle_stripe_event(stripe_event: StripeEvent):
    """Applies the effect of a claimed Stripe event. Safe to call more than
    once for the same event (e.g. replayed by the crash-recovery sweep)
    because every mutation it performs checks current state before acting.
    """
    if stripe_event.order_id is None:
        stripe_event.processed_at = timezone.now()
        stripe_event.save(update_fields=["processed_at"])
        return

    if stripe_event.event_type == "checkout.session.completed" or stripe_event.event_type == "payment_intent.succeeded":
        order = Order.objects.get(pk=stripe_event.order_id)
        paid = confirm_reservation(order, source="webhook")
        if not paid:
            # Order already left pending_payment (most likely: TTL expired
            # before Stripe's confirmation arrived) but Stripe says the
            # charge succeeded — the money is real even though the
            # reservation isn't. Record it loudly for manual reconciliation
            # instead of silently dropping either the payment or the stock.
            OrderStatusEvent.objects.create(
                order=order,
                from_status=order.status,
                to_status="payment_after_expiry_conflict",
                source="webhook",
            )

    stripe_event.processed_at = timezone.now()
    stripe_event.save(update_fields=["processed_at"])
