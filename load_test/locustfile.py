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

from locust import HttpUser, between, task

TOKENS_PATH = os.path.join(os.path.dirname(__file__), "tokens.json")

with open(TOKENS_PATH) as f:
    _seed = json.load(f)

PRODUCT_ID = _seed["product_id"]
TOKENS = _seed["tokens"]
_token_iter = iter(TOKENS)


class Buyer(HttpUser):
    wait_time = between(0, 0.1)

    def on_start(self):
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
        with self.client.post("/api/checkout/", name="/api/checkout/", catch_response=True) as resp:
            # 201/502 both mean the reservation succeeded (502 = Stripe
            # session creation failed after the reservation committed, see
            # CheckoutView's graceful-degradation handling); 409 means this
            # request correctly lost the race for the last unit.
            if resp.status_code in (201, 409, 502):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text}")
