import json

from django.core.management.base import BaseCommand
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.orders.models import Order
from apps.orders.redis_client import write_through_available


class Command(BaseCommand):
    """Seeds a single low-stock product and N users with pre-issued JWTs for
    the load test (load_test/locustfile.py). Load-testing the real Firebase
    sign-in flow isn't meaningful - it would just measure Firebase's
    rate limits, not this project's own concurrency control - so this
    bypasses it and issues SimpleJWT tokens directly, the same tokens the
    app would have handed out after a real login.
    """

    help = "Seed a low-stock product and N users with JWTs for the load test."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=500)
        parser.add_argument("--stock", type=int, default=1)
        parser.add_argument("--out", type=str, default="../load_test/tokens.json")

    def handle(self, *args, **options):
        # A prior run's orders/reservations against this same product must be
        # cleared before resetting `reserved` directly - otherwise `reserved`
        # would drift from the actual set of active reservations, exactly
        # the kind of inconsistency the computed `available` property exists
        # to prevent. Deleting the orders (cascades to their items and
        # reservations) is safe because this product only ever exists for
        # this load test.
        Order.objects.filter(items__product__slug="load-test-product").delete()

        product, _ = Product.objects.update_or_create(
            slug="load-test-product",
            defaults={"name": "Load Test Product", "price": 9.99, "stock": options["stock"], "reserved": 0},
        )

        # begin_checkout's Redis pre-check is a write-through cache - it's
        # only ever updated by a real checkout, never by this reset. Without
        # this, a stale stock:avail:<id> key from a PREVIOUS run (e.g. left
        # at 0 after that run's stock sold out) would silently reject every
        # request in THIS run before it ever reached Postgres, no matter what
        # the DB says - the exact Redis/Postgres drift scenario the design
        # relies on Postgres being the source of truth to recover from, but
        # only once a real request repopulates the cache. Seeding it
        # explicitly here closes that gap for a clean test run.
        write_through_available(product.id, product.available)

        tokens = []
        for i in range(options["users"]):
            user, _ = User.objects.get_or_create(
                username=f"loadtest{i}",
                defaults={"email": f"loadtest{i}@example.com", "firebase_uid": f"loadtest-{i}"},
            )
            tokens.append(str(RefreshToken.for_user(user).access_token))

        with open(options["out"], "w") as f:
            json.dump({"product_id": product.id, "tokens": tokens}, f)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded product {product.id} (stock={product.stock}) and {len(tokens)} users -> {options['out']}"
            )
        )
