# This file is the "sending end" of the WebSocket flow - see
# apps/realtime/consumers.py (the "receiving end") for the other half.
# The only caller of this function is apps/orders/services.py's
# transition_order_status() - nothing else in the project sends a live
# update directly.

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def publish_order_status(order_id, old_status, new_status):
    """Push a status transition to any client subscribed to this order.

    Callers must invoke this only from transaction.on_commit(...) so a
    rolled-back transition is never announced to a client.
    """
    # get_channel_layer() connects to Redis, which is what actually carries
    # this message from wherever this code happens to be running (could be
    # a Celery background worker, a completely separate process) over to
    # whichever Daphne process is holding the open WebSocket connection for
    # this order. Without Redis in between, a message created in one
    # process would have no way to reach a browser connected to a different
    # process.
    channel_layer = get_channel_layer()
    # channel_layer.group_send(...) is itself an async function, but this
    # file (and transition_order_status, its caller) is normal, synchronous
    # code - async_to_sync(...) is the wrapper that lets synchronous code
    # call an async function and just wait for it to finish, instead of
    # needing to rewrite this whole file as async itself.
    #
    # f"order.{order_id}" is the exact same "radio channel" name
    # consumers.py's connect() tuned a WebSocket into - this is what
    # actually delivers the message to everyone subscribed to it.
    # "type": "order.status" is what Channels uses to decide WHICH METHOD
    # to call on the receiving end (order_status(), in consumers.py) - see
    # that file's own comment on this for the naming convention.
    async_to_sync(channel_layer.group_send)(
        f"order.{order_id}",
        {
            "type": "order.status",
            "old_status": old_status,
            "new_status": new_status,
        },
    )
