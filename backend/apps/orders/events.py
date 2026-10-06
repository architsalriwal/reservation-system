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

BEGINNER NOTE: this whole file only ever does ONE cheap thing -
"registering" two background jobs to run later. It does NOT send an email
and does NOT run fulfillment itself - those happen in apps/orders/tasks.py,
run by a completely separate background process (the Celery worker),
whenever it gets to them. Confusing "scheduling work" with "doing work" is
an easy trap here: everything in this file finishes in a fraction of a
millisecond, no matter how slow the actual email-sending or fulfillment
steps end up being.
"""

from django.db import transaction


def dispatch_order_placed(order_id):
    def _enqueue():
        # Imported HERE, inside the function, instead of at the top of the
        # file with the other imports. This is deliberate, not a mistake:
        # apps/orders/tasks.py itself imports FROM apps/orders/services.py,
        # and services.py imports FROM this file (events.py) - importing
        # tasks.py at the very top of this file would create a loop
        # (A needs B needs C needs A) that Python can't resolve at startup.
        # Waiting to import until this inner function actually runs sidesteps
        # that loop entirely. This pattern is called a "circular import," and
        # a local import like this is the standard, simple fix for it.
        from apps.orders.tasks import send_order_confirmation_email, start_fulfillment

        # .delay(order_id) does NOT run send_order_confirmation_email right
        # now. It just drops a note in a queue - "someone please run this
        # function with this order_id, whenever you get a chance" - for the
        # separate Celery worker process to pick up on its own schedule.
        send_order_confirmation_email.delay(order_id)
        start_fulfillment.delay(order_id)

    # Deferred to commit for the same reason transition_order_status defers
    # its WebSocket publish: a rolled-back "mark paid" transaction must
    # never fire a confirmation email for a payment that didn't actually
    # land. Concretely: transaction.on_commit(_enqueue) means "don't call
    # _enqueue() yet - wait until the surrounding database transaction has
    # definitely, successfully saved, THEN call it." If the transaction
    # instead fails and rolls back, _enqueue() is simply never called at
    # all - no email gets queued for a payment that didn't really go through.
    transaction.on_commit(_enqueue)
