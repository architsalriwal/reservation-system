from channels.generic.websocket import AsyncJsonWebsocketConsumer


class OrderConsumer(AsyncJsonWebsocketConsumer):
    """Streams status transitions for a single order to its owner."""

    async def connect(self):
        self.order_id = self.scope["url_route"]["kwargs"]["order_id"]
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=4401)
            return

        if not await self.user_owns_order(user.id, self.order_id):
            await self.close(code=4403)
            return

        self.group_name = f"order.{self.order_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def order_status(self, event):
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
        from channels.db import database_sync_to_async

        from apps.orders.models import Order

        @database_sync_to_async
        def check():
            return Order.objects.filter(pk=order_id, user_id=user_id).exists()

        return await check()
