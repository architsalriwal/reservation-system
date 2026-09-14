import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="USD")

    placed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.id} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField()
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product_id} (order {self.order_id})"


class Reservation(models.Model):
    """Transient stock hold for a pending order, released by TTL expiry or confirmed on payment.

    Kept separate from OrderItem so the expiry sweep only ever touches this
    table, never the permanent order-history rows.
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
    """

    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="stripe_events")
    payload = models.JSONField()

    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.stripe_event_id} ({self.event_type})"


class OrderStatusEvent(models.Model):
    """Append-only audit log. The only path that triggers a WebSocket push."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    source = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.order_id}: {self.from_status} -> {self.to_status} ({self.source})"
