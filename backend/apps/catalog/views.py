from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from apps.catalog.models import Category, Product
from apps.catalog.serializers import CategorySerializer, ProductSerializer


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
