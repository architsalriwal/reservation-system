import stripe
from django.conf import settings
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.exceptions import OutOfStock
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.orders.services import begin_checkout


class CheckoutView(APIView):
    """Begins checkout for the caller's cart: reserves stock, creates a
    pending order, and returns a Stripe Checkout session to redirect to.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        cart_items = [(item["product_id"], item["quantity"]) for item in request.data.get("items", [])]
        if not cart_items:
            return Response({"detail": "Cart is empty."}, status=400)

        try:
            order = begin_checkout(request.user, cart_items)
        except OutOfStock as exc:
            return Response(
                {"detail": "Insufficient stock.", "product_id": exc.product_id, "available": exc.available},
                status=409,
            )

        stripe.api_key = settings.STRIPE_SECRET_KEY
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

        return Response(
            {"order": OrderSerializer(order).data, "checkout_url": session.url}, status=201
        )


class OrderDetailView(RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "order_id"

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)
