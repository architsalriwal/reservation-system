from django.contrib import admin

from apps.orders.models import Order, OrderItem, OrderStatusEvent, Reservation, StripeEvent


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class ReservationInline(admin.TabularInline):
    model = Reservation
    extra = 0


class OrderStatusEventInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    readonly_fields = ["from_status", "to_status", "source", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "total_amount", "created_at"]
    list_filter = ["status"]
    inlines = [OrderItemInline, ReservationInline, OrderStatusEventInline]


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ["stripe_event_id", "event_type", "order", "processed_at", "created_at"]
    list_filter = ["event_type"]
