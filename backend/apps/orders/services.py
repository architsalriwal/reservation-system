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
    """
    redis_conn = get_redis()

    # Cheap pre-check: reject obviously out-of-stock requests without a DB hit.
    for product_id, quantity in cart_items:
        cached = redis_conn.get(available_stock_key(product_id))
        if cached is not None and quantity > int(cached):
            raise OutOfStock(product_id, quantity, int(cached))

    ttl = timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
    expires_at = timezone.now() + ttl

    with transaction.atomic():
        order = Order.objects.create(user=user, status=Order.Status.PENDING_PAYMENT, placed_at=timezone.now())
        total_amount = 0
        locked_products = {}

        for product_id, quantity in cart_items:
            product = Product.objects.select_for_update().get(pk=product_id)
            if product.available < quantity:
                raise OutOfStock(product_id, quantity, product.available)

            product.reserved += quantity
            product.version += 1
            product.save(update_fields=["reserved", "version", "updated_at"])
            locked_products[product_id] = product

            OrderItem.objects.create(
                order=order, product=product, quantity=quantity, unit_price_snapshot=product.price
            )
            Reservation.objects.create(
                order=order, product=product, quantity=quantity, expires_at=expires_at
            )
            total_amount += product.price * quantity

        order.total_amount = total_amount
        order.currency = next(iter(locked_products.values())).currency if locked_products else "INR"
        order.save(update_fields=["total_amount", "currency"])

    for product in locked_products.values():
        write_through_available(product.id, product.available)

    return order


def transition_order_status(order, new_status, source):
    """The single writer of Order.status. No-ops on a non-transition, and
    publishes the WebSocket update only after the DB transaction commits —
    so a rolled-back transition is never announced to a client.
    """
    old_status = order.status
    if old_status == new_status:
        return order

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusEvent.objects.create(
        order=order, from_status=old_status, to_status=new_status, source=source
    )
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
        reservations = list(
            Reservation.objects.select_for_update().filter(
                order_id=order.pk, status=Reservation.Status.ACTIVE
            )
        )
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.PENDING_PAYMENT:
            return order.status == Order.Status.PAID

        for reservation in reservations:
            reservation.status = Reservation.Status.CONFIRMED
            reservation.save(update_fields=["status"])

        transition_order_status(order, Order.Status.PAID, source=source)
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
