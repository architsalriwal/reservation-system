"""Event-driven order processing, scoped to what's actually safe to
decouple.

Inventory deduction deliberately stays OUT of this - it happens
synchronously inside confirm_reservation()'s locked transaction, not as an
event consumer. That's not an oversight: the entire point of this project
is that stock changes happen under a Postgres row lock so two concurrent
requests can never both win the last unit. Moving inventory deduction into
an async consumer would mean a request could return "paid" before stock is
actually decremented, reopening exactly the race this system exists to
close. Only side effects that AREN'T correctness-critical to the stock
guarantee - notifying the customer, progressing fulfillment - are event
consumers here.

dispatch_order_placed() is called once, from confirm_reservation(), after
an order is confirmed paid. It enqueues two independent Celery tasks. They
share no state and don't call each other: a broken email provider can never
block or fail fulfillment, and a bug in the fulfillment simulation can never
block the confirmation email. Each is retried independently by Celery.
"""

from django.db import transaction


def dispatch_order_placed(order_id):
    def _enqueue():
        from apps.orders.tasks import send_order_confirmation_email, start_fulfillment

        send_order_confirmation_email.delay(order_id)
        start_fulfillment.delay(order_id)

    # Deferred to commit for the same reason transition_order_status defers
    # its WebSocket publish: a rolled-back "mark paid" transaction must
    # never fire a confirmation email for a payment that didn't actually
    # land.
    transaction.on_commit(_enqueue)
