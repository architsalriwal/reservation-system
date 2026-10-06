# Thin HTTP wrappers around apps/storefront/cart.py's plain functions -
# this file's only job is translating a web request into a call to one of
# those functions and serializing the result back to JSON. No cart logic
# of its own lives here; see cart.py for the actual implementation.

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.storefront import cart as cart_ops
from apps.storefront.serializers import CartItemInputSerializer, CartSerializer


class CartView(APIView):
    # AllowAny: unlike almost every other view in this project, you do NOT
    # need to be logged in to have a cart - browsing and adding items works
    # for anonymous visitors too (the session cookie alone is enough to
    # track their cart). Login only becomes required at checkout time - see
    # apps/orders/views.py's CheckoutView, which uses IsAuthenticated
    # instead.
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
        # "Add to cart" - note there is NO stock check anywhere in this
        # method. Adding something to a cart never touches Product.stock or
        # Product.reserved at all; the real check only happens later, at
        # checkout (see apps/orders/services.py's begin_checkout()).
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
