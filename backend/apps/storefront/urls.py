from django.urls import path

from apps.storefront.views import CartItemView, CartView

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemView.as_view(), name="cart-item-add"),
    path("cart/items/<int:product_id>/", CartItemView.as_view(), name="cart-item-detail"),
]
