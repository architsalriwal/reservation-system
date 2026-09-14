from rest_framework import serializers

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer


class CartItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class CartItemSerializer(serializers.Serializer):
    product = ProductSerializer()
    quantity = serializers.IntegerField()
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2)


class CartSerializer(serializers.Serializer):
    items = CartItemSerializer(many=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2)

    @staticmethod
    def build(cart):
        product_ids = [int(pid) for pid in cart.keys()]
        products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}

        items = []
        total = 0
        for pid, quantity in cart.items():
            product = products.get(int(pid))
            if product is None:
                continue
            line_total = product.price * quantity
            items.append({"product": product, "quantity": quantity, "line_total": line_total})
            total += line_total

        return {"items": items, "total": total}
