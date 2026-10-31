import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Category, Product
from apps.catalog.serializers import ProductSerializer

# A dedicated category prefix, so this command's synthetic products never
# collide with the real curated catalog from seed_demo_products.py, and can
# be cleanly identified and removed afterward (see --keep below).
BENCH_CATEGORY_PREFIX = "bench-"


class Command(BaseCommand):
    help = (
        "Measures the real query-count and wall-clock difference the "
        "ProductViewSet's select_related('category') makes (apps/catalog/"
        "views.py), by seeding a realistic number of products, then "
        "serializing them once WITHOUT select_related (the N+1 case) and "
        "once WITH it (the actual, current code path), and reporting both. "
        "Exists to replace an assumed '30% faster' claim with a real, "
        "reproducible number - see reservly-interview-briefing.md."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count", type=int, default=200, help="How many synthetic products to benchmark against."
        )
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Keep the synthetic benchmark products afterward instead of deleting them.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        keep = options["keep"]

        self.stdout.write(f"Seeding {count} synthetic products across 10 categories...")
        categories = [
            Category.objects.get_or_create(
                name=f"{BENCH_CATEGORY_PREFIX}{i}", defaults={"slug": f"{BENCH_CATEGORY_PREFIX}{i}"}
            )[0]
            for i in range(10)
        ]
        products = [
            Product(
                slug=f"{BENCH_CATEGORY_PREFIX}product-{i}",
                name=f"Benchmark Product {i}",
                description="Synthetic product generated for query benchmarking only.",
                category=categories[i % len(categories)],
                price=999,
                currency="INR",
                stock=10,
                reserved=0,
                is_active=True,
                image_url="",
            )
            for i in range(count)
        ]
        Product.objects.bulk_create(products, ignore_conflicts=True)

        base_queryset = Product.objects.filter(slug__startswith=BENCH_CATEGORY_PREFIX)

        naive_queries, naive_seconds = self._measure(base_queryset)
        optimized_queries, optimized_seconds = self._measure(base_queryset.select_related("category"))

        if not keep:
            Product.objects.filter(slug__startswith=BENCH_CATEGORY_PREFIX).delete()
            Category.objects.filter(slug__startswith=BENCH_CATEGORY_PREFIX).delete()
            self.stdout.write("Cleaned up synthetic benchmark products.")

        query_reduction_pct = 100 * (naive_queries - optimized_queries) / naive_queries
        time_reduction_pct = 100 * (naive_seconds - optimized_seconds) / naive_seconds

        self.stdout.write(self.style.SUCCESS("\n--- Results ---"))
        self.stdout.write(f"Products serialized:      {count}")
        self.stdout.write(f"WITHOUT select_related:   {naive_queries} queries, {naive_seconds * 1000:.1f} ms")
        self.stdout.write(f"WITH select_related:      {optimized_queries} queries, {optimized_seconds * 1000:.1f} ms")
        self.stdout.write(
            self.style.SUCCESS(
                f"Query count reduction:    {query_reduction_pct:.1f}%  "
                f"({naive_queries} -> {optimized_queries})"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(f"Wall-clock time reduction: {time_reduction_pct:.1f}%")
        )

    def _measure(self, queryset):
        # Force a completely fresh query each time - .all() clones the
        # queryset and clears any cached results from a previous pass.
        with CaptureQueriesContext(connection) as ctx:
            start = time.perf_counter()
            data = ProductSerializer(queryset.all(), many=True).data
            list(data)  # force full serialization - DRF serializers are lazy until iterated
            elapsed = time.perf_counter() - start
        return len(ctx.captured_queries), elapsed
