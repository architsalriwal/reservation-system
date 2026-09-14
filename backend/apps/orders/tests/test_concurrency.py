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


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_last_unit_only_one_winner():
    product = ProductFactory(stock=1, reserved=0)
    users = [UserFactory() for _ in range(20)]

    results = []
    lock = threading.Lock()

    def attempt(user):
        try:
            begin_checkout(user, [(product.id, 1)])
            outcome = "success"
        except OutOfStock:
            outcome = "out_of_stock"
        finally:
            db.connections.close_all()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=(user,)) for user in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("success") == 1
    assert results.count("out_of_stock") == len(users) - 1

    product.refresh_from_db()
    assert product.reserved == 1
    assert product.available == 0
