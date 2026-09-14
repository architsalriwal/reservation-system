from django.urls import path

from apps.orders.views import CheckoutView, OrderDetailView
from apps.orders.webhooks import StripeWebhookView

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/<uuid:order_id>/", OrderDetailView.as_view(), name="order-detail"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
]
