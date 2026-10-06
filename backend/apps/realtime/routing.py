# This is the WebSocket equivalent of config/urls.py - except config/urls.py
# only routes normal HTTP requests (GET/POST/etc), and this file only routes
# WebSocket CONNECTION attempts. They're kept completely separate because
# WebSockets work fundamentally differently under the hood (one long-lived
# open connection instead of many short request/reply cycles), so Django
# Channels needs its own routing table for them.
#
# When the frontend does `new WebSocket(".../ws/orders/<some-id>/?token=...")`
# (see frontend/src/pages/OrderStatus.jsx), THIS is the line that decides
# which Python class handles that connection - apps/realtime/consumers.py's
# OrderConsumer. The `(?P<order_id>[0-9a-f-]+)` part is a regular expression
# that captures whatever ID is in the URL and makes it available inside the
# consumer as self.scope["url_route"]["kwargs"]["order_id"].

from django.urls import re_path

from apps.realtime.consumers import OrderConsumer

websocket_urlpatterns = [
    re_path(r"ws/orders/(?P<order_id>[0-9a-f-]+)/$", OrderConsumer.as_asgi()),
]
