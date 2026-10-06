# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This file handles WebSocket connections - NOT normal HTTP requests. A
# WebSocket is like a phone call that stays open, instead of a normal web
# request (sending a letter, getting one reply, done). The frontend opens
# one of these per order-status page it has open (see
# frontend/src/pages/OrderStatus.jsx), and this class is what runs on the
# server side of that open connection.
#
# The actual messages sent down this connection come from a completely
# different file - apps/orders/services.py's transition_order_status()
# calls publish.py's publish_order_status(), which "broadcasts" to whichever
# of these connections are listening. This file is only the "receiving end."
# ============================================================================

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class OrderConsumer(AsyncJsonWebsocketConsumer):
    """Streams status transitions for a single order to its owner.

    BEGINNER NOTE: "async def" methods are functions that can PAUSE while
    waiting on something slow (a database query, a network call) without
    blocking the whole server - other WebSocket connections keep working
    while this one is paused mid-function. "await" is the keyword that
    marks each pause point. You don't need to understand async/await deeply
    to follow the logic below - just read "await someFunction()" as "call
    this and wait for the result," same as a normal function call.
    """

    async def connect(self):
        # Runs once, the moment a browser tries to open this WebSocket -
        # e.g. `new WebSocket(".../ws/orders/<id>/?token=...")` on the
        # frontend. `self.scope` holds everything about this connection
        # attempt (the URL it connected to, who's making the request).
        self.order_id = self.scope["url_route"]["kwargs"]["order_id"]
        user = self.scope["user"]

        # SECURITY CHECK #1: are you even logged in? If not, refuse the
        # connection outright - 4401 is a custom close code (like an HTTP
        # status code, but for WebSockets) this project chose to mean
        # "unauthenticated," matching the 401 HTTP code used elsewhere.
        if not user.is_authenticated:
            await self.close(code=4401)
            return

        # SECURITY CHECK #2: is this YOUR order? A real database lookup,
        # not just trusting whatever order_id was in the URL - without
        # this, any logged-in user could watch live updates for anyone
        # else's order just by guessing or copying an order ID.
        if not await self.user_owns_order(user.id, self.order_id):
            await self.close(code=4403)
            return

        # Both checks passed - "subscribe" this connection to a named
        # group. Think of f"order.{self.order_id}" as a radio channel
        # unique to this one order; anyone tuned into it gets every message
        # sent to it. See publish.py for the other end of this - where a
        # message actually gets sent TO this group.
        self.group_name = f"order.{self.order_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()  # finally, actually accept the connection

    async def disconnect(self, close_code):
        # Runs when the connection closes for any reason (user closed the
        # tab, navigated away, lost internet). Clean up by leaving the
        # group, so we don't keep trying to send messages to a connection
        # that no longer exists.
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def order_status(self, event):
        # This method's NAME matters - it's not arbitrary. publish.py sends
        # a message with `"type": "order.status"`, and Channels
        # automatically converts that to "order_status" and calls the
        # method of that exact name on every consumer in the group. This is
        # Channels' own routing convention, not something built in this
        # file - rename this method and messages would silently stop
        # arriving here.
        await self.send_json(
            {
                "type": "order.status",
                "order_id": self.order_id,
                "old_status": event["old_status"],
                "new_status": event["new_status"],
            }
        )

    @staticmethod
    async def user_owns_order(user_id, order_id):
        # Imported inside the function (not at the top of the file) and
        # wrapped with @database_sync_to_async - Django's normal database
        # code is NOT async-aware, so it can't be called directly from an
        # "async def" method like connect() above. database_sync_to_async
        # is the bridge that lets this async WebSocket code safely run a
        # normal, synchronous database query without blocking everything
        # else the server is doing at the same time.
        from channels.db import database_sync_to_async

        from apps.orders.models import Order

        @database_sync_to_async
        def check():
            # The actual ownership check, in one line: does an Order exist
            # with BOTH this exact id AND this exact user? If someone tries
            # another user's order_id, this simply returns False - no
            # separate "fetch the order, then check who owns it" step that
            # could be gotten wrong.
            return Order.objects.filter(pk=order_id, user_id=user_id).exists()

        return await check()
