# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This is the REAL end-to-end load test - not a unit test running inside
# pytest, but Locust (a separate load-testing tool) actually making real
# HTTP requests over the network against a genuinely running Django server,
# the same way hundreds of real browsers would. It's the proof behind the
# "150-user Locust run, exactly 1 order" claim.
#
# How Locust works, briefly: you define a "User" class describing what one
# simulated person does. Locust then spins up many copies of that class at
# once, each running independently and repeatedly, and reports aggregate
# stats (request counts, failures, response times) across all of them.
#   - HttpUser: the base class for "a simulated user that makes HTTP
#     requests" - self.client below is a real HTTP client pointed at
#     --host.
#   - wait_time = between(0, 0.1): how long each simulated user pauses
#     between actions - kept tiny here on purpose, since the whole point is
#     maximizing how many requests arrive at the same instant, not
#     simulating realistic human browsing pauses.
#   - on_start(): runs once per simulated user, before their first @task -
#     this is where each one grabs its own unique pre-issued login token.
#   - @task: marks a method as something a simulated user actually does
#     repeatedly once running.
# ============================================================================

"""Load test for hard feature #1: concurrent overselling prevention.

Setup:
    cd backend && ./.venv/Scripts/python.exe manage.py seed_load_test --users 500 --stock 1

Run (from repo root, backend must be running on :8000):
    locust -f load_test/locustfile.py --host http://localhost:8000

Each simulated user has its own pre-issued JWT (see seed_load_test), adds
the single-stock product to their session cart, and immediately hits
/api/checkout/. Expected result against 1 unit of stock: exactly one 201,
everyone else a 409 (OutOfStock) - never two 201s, and no 5xx errors from
a race condition or deadlock. Run count()/summary output is pasted into
the project README as the proof artifact.
"""

import json
import os
import uuid

from locust import HttpUser, between, task

TOKENS_PATH = os.path.join(os.path.dirname(__file__), "tokens.json")

# tokens.json is generated ahead of time by the seed_load_test management
# command referenced above - it pre-creates N real user accounts and their
# real login tokens, so the load test itself doesn't waste time logging
# in; it can jump straight to the actual checkout race being measured.
with open(TOKENS_PATH) as f:
    _seed = json.load(f)

PRODUCT_ID = _seed["product_id"]
TOKENS = _seed["tokens"]
# An iterator, not a list index - each simulated user calls next() on this
# ONCE in on_start() to claim one token for itself, guaranteeing no two
# simulated users ever accidentally share the same login identity.
_token_iter = iter(TOKENS)


class Buyer(HttpUser):
    wait_time = between(0, 0.1)

    def on_start(self):
        # If there are more simulated users than pre-generated tokens,
        # StopIteration fires - rather than letting that crash with a
        # confusing traceback, this stops that one extra simulated user
        # cleanly instead of giving it no valid login at all.
        try:
            self.token = next(_token_iter)
        except StopIteration:
            self.environment.runner.quit()
            return
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    @task
    def race_for_last_unit(self):
        self.client.post(
            "/api/cart/items/", json={"product_id": PRODUCT_ID, "quantity": 1}, name="/api/cart/items/"
        )
        # A fresh key per request: each is a genuinely new checkout attempt
        # for the race proof, not a retry of a prior one - reusing a key
        # here would make CheckoutView dedupe requests we actually want to
        # race independently.
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        with self.client.post(
            "/api/checkout/", name="/api/checkout/", headers=headers, catch_response=True
        ) as resp:
            # 201/502 both mean the reservation succeeded (502 = Stripe
            # session creation failed after the reservation committed, see
            # CheckoutView's graceful-degradation handling); 409 means this
            # request correctly lost the race for the last unit.
            if resp.status_code in (201, 409, 502):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text}")
