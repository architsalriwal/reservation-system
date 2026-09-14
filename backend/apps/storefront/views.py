from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.storefront import cart as cart_ops
from apps.storefront.serializers import CartItemInputSerializer, CartSerializer


class CartView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        cart = cart_ops.get_cart(request.session)
        return Response(CartSerializer(CartSerializer.build(cart)).data)

    def delete(self, request):
        cart_ops.clear(request.session)
        return Response(status=204)


class CartItemView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CartItemInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = cart_ops.add_item(
            request.session,
            serializer.validated_data["product_id"],
            serializer.validated_data["quantity"],
        )
        return Response(CartSerializer(CartSerializer.build(cart)).data, status=201)

    def patch(self, request, product_id):
        quantity = request.data.get("quantity")
        if quantity is None:
            return Response({"detail": "quantity is required."}, status=400)
        cart = cart_ops.set_item_quantity(request.session, product_id, int(quantity))
        return Response(CartSerializer(CartSerializer.build(cart)).data)

    def delete(self, request, product_id):
        cart = cart_ops.remove_item(request.session, product_id)
        return Response(CartSerializer(CartSerializer.build(cart)).data)
