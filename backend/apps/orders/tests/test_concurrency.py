# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This is the actual proof behind "overselling can't happen" - not a unit
# test that mocks the database, but a REAL concurrency test: 20 separate
# Python threads, each with its OWN real database connection, all trying to
# buy the one remaining unit of a product AT THE SAME TIME.
#
# Why threads instead of just calling begin_checkout() 20 times in a for
# loop? A for loop runs everything one at a time, in order - there's no
# actual race, so it could never catch a concurrency bug. Real threads
# running simultaneously are what actually exercise the row-locking
# (select_for_update) code path the same way real simultaneous shoppers
# would in production.
#
# What a passing test proves: exactly 1 of the 20 gets a real order, and
# the other 19 get a clean "out of stock" - never 2 successes (that would
# mean overselling), never 0 successes (that would mean the lock itself is
# broken and falsely rejecting a legitimate winner).
# ============================================================================

"""Proof for hard feature #1 (README: Concurrent overselling prevention).

Fires N concurrent begin_checkout() calls at a product with exactly one unit
of stock. Asserts exactly one succeeds and the rest get a clean OutOfStock —
never two successes (overselling) and never zero (a false rejection due to a
deadlock or lost update).
"""

import threading

import pytest
from django import db

from apps.orders.exceptions import OutOfStock
from apps.orders.services import begin_checkout
from apps.orders.tests.factories import ProductFactory, UserFactory

# transaction=True is required here, not optional - the default pytest-django
# test setup wraps each test in one big transaction that gets rolled back at
# the end, which means every thread would secretly share that SAME
# transaction and never actually race against each other. transaction=True
# makes this test use real, separately-committing transactions instead, so
# the 20 threads below are genuinely racing, the way real users would.
@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_last_unit_only_one_winner():
    # Exactly 1 unit of stock, 20 different shoppers all trying to buy it.
    product = ProductFactory(stock=1, reserved=0)
    users = [UserFactory() for _ in range(20)]

    # results collects the outcome ("success" or "out_of_stock") from every
    # thread. A plain Python list isn't safe to append to from multiple
    # threads at once without protection - that's what `lock` below is for.
    results = []
    lock = threading.Lock()

    def attempt(user):
        # This whole function is what ONE thread runs - i.e. what ONE
        # simulated shopper does: try to check out, and note whether it
        # succeeded or got rejected as out of stock.
        try:
            begin_checkout(user, [(product.id, 1)])
            outcome = "success"
        except OutOfStock:
            outcome = "out_of_stock"
        finally:
            # Each thread needs to close its own database connection when
            # it's done - Django doesn't automatically clean up connections
            # opened by background threads the way it does for normal
            # request/response connections, so skipping this would leak a
            # connection per thread.
            db.connections.close_all()
        # `with lock:` means "only one thread can be inside this block at a
        # time" - this is the thing that makes results.append() itself safe
        # to call from 20 threads simultaneously, separate from (and much
        # simpler than) the actual database locking being tested above.
        with lock:
            results.append(outcome)

    # Create all 20 threads first, THEN start them all, so they begin as
    # close to simultaneously as possible - if you created and started them
    # one at a time in the same loop, the earlier ones could finish before
    # the later ones even start, which would defeat the whole point.
    threads = [threading.Thread(target=attempt, args=(user,)) for user in users]
    for t in threads:
        t.start()
    for t in threads:
        # .join() blocks until that specific thread has fully finished -
        # this loop is what makes the test wait for all 20 shoppers to be
        # done before checking the results below, instead of checking too
        # early while some threads are still mid-checkout.
        t.join()

    # The actual proof: exactly one winner, everyone else cleanly rejected.
    assert results.count("success") == 1
    assert results.count("out_of_stock") == len(users) - 1

    # Double-check the real database state agrees with what the threads
    # reported - reserved went up by exactly 1, and available (stock minus
    # reserved) correctly shows 0 left, not something negative (which would
    # mean more was reserved than actually existed - the literal definition
    # of overselling).
    product.refresh_from_db()
    assert product.reserved == 1
    assert product.available == 0
