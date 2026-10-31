# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# WebSocket tests look different from normal Django tests because a
# WebSocket is a long-lived, two-way connection, not a one-off
# request/response - so these use `async def` test functions and
# Channels' own WebsocketCommunicator (a fake WebSocket client built for
# tests) instead of DRF's APIClient. @database_sync_to_async wraps
# ordinary, synchronous Django ORM calls (like order.save()) so they can
# safely be awaited from inside an async test - Django's ORM itself isn't
# async-native, so this bridges the two worlds.
#
# Two tests: (1) the actual real-time proof - connect over a WebSocket,
# trigger a REAL order status change elsewhere, and confirm the connected
# client receives a live push message, while confirming a save that
# DOESN'T actually change the status produces no push at all; (2) a
# connection with no valid auth token gets rejected outright, proving you
# can't eavesdrop on someone else's order updates by connecting without
# logging in.
# ============================================================================

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
