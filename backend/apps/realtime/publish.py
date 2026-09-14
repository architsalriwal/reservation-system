from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def publish_order_status(order_id, old_status, new_status):
    """Push a status transition to any client subscribed to this order.

    Callers must invoke this only from transaction.on_commit(...) so a
    rolled-back transition is never announced to a client.
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"order.{order_id}",
        {
            "type": "order.status",
            "old_status": old_status,
            "new_status": new_status,
        },
    )
