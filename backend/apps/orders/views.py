import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from apps.orders.exceptions import OutOfStock
from apps.orders.models import CheckoutIdempotencyKey, Order, OrderStatusEvent
from apps.orders.serializers import OrderSerializer
from apps.orders.services import begin_checkout
from apps.storefront import cart as cart_ops

# Fail fast rather than let a slow/unreachable Stripe hang the checkout
# request open - the reservation has already committed by this point, so a
# Stripe outage here is a payment-initiation failure, not a stock-safety one.
STRIPE_REQUEST_TIMEOUT_SECONDS = 5

# After 5 straight Stripe failures, stop even trying for 30s and fail
# instantly instead - during a real Stripe outage this saves every request
# in that window from waiting out a timeout it was going to hit anyway.
stripe_breaker = CircuitBreaker("stripe", failure_threshold=5, cooldown_seconds=30)


class CheckoutView(APIView):
    """Begins checkout for the caller's session cart: reserves stock, creates
    a pending order, and returns a Stripe Checkout session to redirect to.
    The session cart (not client-supplied line items) is the source of truth
    for what's being purchased.

    Requires an `Idempotency-Key` header (client-generated, one per logical
    checkout attempt) so a retried request - flaky network, a double-click
    that slips past the disabled button, a proxy replaying a POST it never
    got a response for - can't create a second order. The claiming INSERT
    happens before begin_checkout() ever reserves stock, mirroring the
    Stripe webhook's claim-before-mutate pattern: a losing concurrent
    request with the same key is rejected before it reserves anything, so
    there's no reservation to clean up on the losing side.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response({"detail": "Idempotency-Key header is required."}, status=400)

        try:
            with transaction.atomic():
                key_record = CheckoutIdempotencyKey.objects.create(user=request.user, key=idempotency_key)
        except IntegrityError:
            existing = CheckoutIdempotencyKey.objects.get(user=request.user, key=idempotency_key)
            if existing.order_id:
                # A prior request with this same key already completed -
                # replay its result instead of creating a second order.
                return Response(
                    {"order": OrderSerializer(existing.order).data, "checkout_url": existing.checkout_url},
                    status=201 if existing.checkout_url else 502,
                )
            return Response(
                {"detail": "A checkout with this idempotency key is already being processed."}, status=409
            )

        cart = cart_ops.get_cart(request.session)
        cart_items = [(int(product_id), quantity) for product_id, quantity in cart.items()]
        if not cart_items:
            key_record.delete()  # nothing was ever attempted - safe to let a retry with this key try again
            return Response({"detail": "Cart is empty."}, status=400)

        try:
            order = begin_checkout(request.user, cart_items)
        except OutOfStock as exc:
            key_record.delete()  # no order/reservation exists - a retry (e.g. after fixing the cart) should not be blocked
            return Response(
                {"detail": "Insufficient stock.", "product_id": exc.product_id, "available": exc.available},
                status=409,
            )

        checkout_url = None
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe_breaker.call(
                stripe.checkout.Session.create,
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
        except CircuitBreakerOpen:
            # Stripe has failed repeatedly in the last 30s - don't even try,
            # just degrade immediately. The reservation is untouched either way.
            OrderStatusEvent.objects.create(
                order=order,
                from_status=order.status,
                to_status="stripe_circuit_open",
                source="checkout",
            )
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

        key_record.order = order
        key_record.checkout_url = checkout_url or ""
        key_record.save(update_fields=["order", "checkout_url"])

        cart_ops.clear(request.session)
        # Explicit save rather than relying on SessionMiddleware's automatic
        # save-on-response: found via testing that repeated checkout calls in
        # the same session could see a stale, un-cleared cart on the very
        # next request without this - not worth leaving as an implicit
        # "the framework will handle it" for something that means a user's
        # already-purchased items silently reappearing in their cart.
        request.session.save()

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
