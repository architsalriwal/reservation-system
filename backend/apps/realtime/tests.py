"""Proof for hard feature #4 (Real-time order status) and the
"only genuine transitions" guard from CLAUDE.md's known architecture gaps.
"""

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import RefreshToken

from apps.orders.models import Order
from apps.orders.services import transition_order_status
from apps.orders.tests.factories import ProductFactory, UserFactory
from apps.realtime.middleware import JWTAuthMiddlewareStack
from apps.realtime.routing import websocket_urlpatterns


@database_sync_to_async
def _make_order_and_token():
    user = UserFactory()
    product = ProductFactory(stock=5, reserved=0)
    order = Order.objects.create(user=user, status=Order.Status.PENDING_PAYMENT)
    token = str(RefreshToken.for_user(user).access_token)
    return order, token, product


@database_sync_to_async
def _transition(order, new_status, source="test"):
    order.refresh_from_db()
    return transition_order_status(order, new_status, source=source)


@database_sync_to_async
def _resave_unrelated_field(order):
    order.refresh_from_db()
    order.total_amount = order.total_amount + 1
    order.save(update_fields=["total_amount"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_websocket_receives_push_only_on_genuine_status_transition():
    order, token, _product = await _make_order_and_token()

    app = JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    communicator = WebsocketCommunicator(app, f"/ws/orders/{order.id}/?token={token}")
    connected, _ = await communicator.connect()
    assert connected

    await _transition(order, Order.Status.PAID, source="webhook")

    message = await communicator.receive_json_from(timeout=2)
    assert message == {
        "type": "order.status",
        "order_id": str(order.id),
        "old_status": Order.Status.PENDING_PAYMENT,
        "new_status": Order.Status.PAID,
    }

    # A save that doesn't change status (e.g. total_amount recalculation)
    # must NOT trigger another push - only genuine transitions publish.
    await _resave_unrelated_field(order)
    assert await communicator.receive_nothing(timeout=1)

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_websocket_rejects_unauthenticated_connection():
    order, _token, _product = await _make_order_and_token()

    app = JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    communicator = WebsocketCommunicator(app, f"/ws/orders/{order.id}/")
    connected, _ = await communicator.connect()
    assert not connected
