from django.urls import re_path

from apps.realtime.consumers import OrderConsumer

websocket_urlpatterns = [
    re_path(r"ws/orders/(?P<order_id>[0-9a-f-]+)/$", OrderConsumer.as_asgi()),
]
