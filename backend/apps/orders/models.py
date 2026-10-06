# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This is where every database table used by the ordering/payment system is
# DEFINED - nothing in here runs any logic; it only describes the shape of
# the data. The actual logic that creates and changes rows in these tables
# lives in apps/orders/services.py and apps/orders/tasks.py. Think of this
# file as the blueprint, and those other files as the people doing the work
# according to that blueprint.
#
# Five tables, each with a specific, narrow job:
#   Order              - one purchase attempt, and its current status
#   OrderItem           - one line item on an order (which product, how many,
#                          at what price) - PERMANENT history, never deleted
#   Reservation          - a TEMPORARY hold on stock, separate from OrderItem
#                          on purpose (see its own docstring below)
#   StripeEvent          - "have we already processed this exact webhook?"
#   CheckoutIdempotencyKey - "has this exact checkout click already been
#                          handled?" (a different problem from StripeEvent -
#                          see that model's own docstring)
#   OrderStatusEvent      - a permanent log of every status change an order
#                          ever went through
# ============================================================================

import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    # models.TextChoices defines a fixed, named set of allowed values for
    # the `status` field below - Python code elsewhere refers to these as
    # Order.Status.PAID, Order.Status.EXPIRED, etc., instead of writing the
    # raw string "paid" everywhere (which would be easy to typo).
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELED = "canceled", "Canceled"  # defined, but nothing in this project currently sets an order to this
        EXPIRED = "expired", "Expired"

    # A UUID (a long random unique identifier, like
    # "f43348ec-2456-47a1-8e8c-a44f91a67e67") instead of a simple counting
    # number (1, 2, 3...) as the primary key. One practical reason: order
    # IDs show up in URLs (e.g. the Stripe success_url) and WebSocket
    # channel names - a UUID can't be easily guessed or enumerated by
    # incrementing a number, the way a sequential ID could.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # on_delete=SET_NULL + null=True: if the User who placed this order is
    # ever deleted, keep the Order row around (for historical/accounting
    # purposes) but blank out who it belonged to, rather than deleting the
    # order too.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="INR")

    placed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.id} ({self.status})"


class OrderItem(models.Model):
    """One line item on an order - "2 of product X, at ₹899 each." This is
    PERMANENT order history, unlike Reservation below - an OrderItem is
    never deleted or expired, even if the order itself never gets paid.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # on_delete=PROTECT: refuses to let a Product be deleted from the
    # database at all if any OrderItem still references it - protecting
    # historical order records from silently breaking/disappearing just
    # because a product was later removed from the catalog.
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField()
    # unit_price_snapshot: the product's price AT THE MOMENT this order was
    # placed, copied here permanently. If the product's price changes next
    # week, this old order's total still correctly reflects what was
    # actually charged at the time - it never silently changes.
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product_id} (order {self.order_id})"


class Reservation(models.Model):
    """Transient stock hold for a pending order, released by TTL expiry or confirmed on payment.

    Kept separate from OrderItem so the expiry sweep only ever touches this
    table, never the permanent order-history rows.

    BEGINNER NOTE: think of this as a claim ticket, separate from the
    receipt (OrderItem). "I am holding 2 units of product X until 3:15pm,
    unless payment confirms first" is exactly what one Reservation row
    says. Created in apps/orders/services.py's begin_checkout(), flipped to
    CONFIRMED in that same file's confirm_reservation() (on real payment),
    or flipped to EXPIRED in apps/orders/tasks.py's
    expire_single_reservation() (if nobody paid in time).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CONFIRMED = "confirmed", "Confirmed"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="reservations")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="reservations")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=["status", "expires_at"])]

    def __str__(self):
        return f"Reservation {self.id} ({self.status}) for order {self.order_id}"


class StripeEvent(models.Model):
    """Idempotency record for Stripe webhook deliveries.

    The unique constraint on stripe_event_id is the actual guarantee against
    double-processing a duplicate delivery — not an application-level exists()
    check, which would have its own race between two concurrent deliveries.

    BEGINNER NOTE: `unique=True` right on the field below is doing the real
    work here - it's a rule enforced by the DATABASE ITSELF, not by Python
    code. Two attempts to save a row with the same stripe_event_id will have
    the SECOND one rejected by Postgres with an error, no matter how close
    together in time they arrive - that's what makes this safe even against
    two near-simultaneous duplicate webhook deliveries, which a plain Python
    "does this already exist?" check could be fooled by.
    """

    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="stripe_events")
    payload = models.JSONField()

    # processed_at starts out empty (null) the moment a webhook is first
    # claimed, and only gets filled in once apps/orders/services.py's
    # handle_stripe_event() finishes applying its effect. A row sitting
    # here with processed_at still null for more than 2 minutes is exactly
    # what apps/orders/tasks.py's sweep_unprocessed_stripe_events() looks
    # for - proof something crashed partway through.
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.stripe_event_id} ({self.event_type})"


class CheckoutIdempotencyKey(models.Model):
    """Guards POST /checkout/ against duplicate orders from a retried
    request (flaky network, double-click that slips past the disabled
    button, a proxy replaying a POST it didn't get a response for).

    Same claim-before-mutate pattern as StripeEvent: the unique constraint
    on (user, key) is the actual guarantee, not an app-level exists()
    check, which would have its own race between two concurrent requests
    carrying the same key. The claiming INSERT happens before
    begin_checkout() ever reserves stock, so a losing concurrent request
    is rejected before it can reserve anything - no reservation to clean
    up afterward.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="checkout_keys")
    key = models.CharField(max_length=255)
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="idempotency_keys"
    )
    checkout_url = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="unique_user_checkout_idempotency_key")
        ]

    def __str__(self):
        return f"{self.user_id}:{self.key}"


class OrderStatusEvent(models.Model):
    """Append-only audit log. The only path that triggers a WebSocket push."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_events")
    # Wider than Order.Status's own choices (max 20 chars) because this log
    # also records off-model conflict/degradation markers, e.g.
    # "payment_after_expiry_conflict" and "stripe_session_failed", which
    # aren't real Order statuses - just audit-trail events.
    from_status = models.CharField(max_length=40)
    to_status = models.CharField(max_length=40)
    source = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.order_id}: {self.from_status} -> {self.to_status} ({self.source})"
