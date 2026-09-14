import stripe
from django.conf import settings
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.exceptions import OutOfStock
from apps.orders.models import Order, OrderStatusEvent
from apps.orders.serializers import OrderSerializer
from apps.orders.services import begin_checkout
from apps.storefront import cart as cart_ops

# Fail fast rather than let a slow/unreachable Stripe hang the checkout
# request open - the reservation has already committed by this point, so a
# Stripe outage here is a payment-initiation failure, not a stock-safety one.
STRIPE_REQUEST_TIMEOUT_SECONDS = 5


class CheckoutView(APIView):
    """Begins checkout for the caller's session cart: reserves stock, creates
    a pending order, and returns a Stripe Checkout session to redirect to.
    The session cart (not client-supplied line items) is the source of truth
    for what's being purchased.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        cart = cart_ops.get_cart(request.session)
        cart_items = [(int(product_id), quantity) for product_id, quantity in cart.items()]
        if not cart_items:
            return Response({"detail": "Cart is empty."}, status=400)

        try:
            order = begin_checkout(request.user, cart_items)
        except OutOfStock as exc:
            return Response(
                {"detail": "Insufficient stock.", "product_id": exc.product_id, "available": exc.available},
                status=409,
            )

        checkout_url = None
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": order.currency.lower(),
                            "product_data": {"name": item.product.name},
                            "unit_amount": int(item.unit_price_snapshot * 100),
                        },
                        "quantity": item.quantity,
                    }
                    for item in order.items.select_related("product").all()
                ],
                metadata={"order_id": str(order.id)},
                success_url=f"{settings.FRONTEND_URL}/orders/{order.id}?success=true",
                cancel_url=f"{settings.FRONTEND_URL}/orders/{order.id}?canceled=true",
            )
            checkout_url = session.url
        except stripe.error.StripeError:
            # The reservation already committed and holds the stock under its
            # normal TTL - a Stripe outage here degrades to "payment session
            # unavailable, try again", not a corrupted or lost reservation.
            OrderStatusEvent.objects.create(
                order=order,
                from_status=order.status,
                to_status="stripe_session_failed",
                source="checkout",
            )

        cart_ops.clear(request.session)

        return Response(
            {"order": OrderSerializer(order).data, "checkout_url": checkout_url},
            status=201 if checkout_url else 502,
        )


class OrderDetailView(RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "order_id"

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)
