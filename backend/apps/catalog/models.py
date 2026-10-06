# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# Just two tables: Category (trivial) and Product (the important one). The
# Product model is read from all over the project - the catalog listing
# page, the cart, every stock-locking line in apps/orders/services.py, and
# the AI search in apps/assistant/. The `embedding` field near the bottom is
# what powers "search by meaning" (see apps/assistant/search.py) - everything
# else here is the inventory-tracking fields the overselling-prevention logic
# depends on.
# ============================================================================

from django.db import models
from pgvector.django import HnswIndex, VectorField

# How many numbers make up one product's "meaning embedding" - see the
# `embedding` field below and apps/assistant/search.py for what this is
# used for. 768 is simply the size Gemini's embedding model produces; this
# constant exists so the model field and anything else that needs this
# number never have to repeat the literal value 768 and risk it drifting
# out of sync.
EMBEDDING_DIMENSIONS = 768


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        # Without this, Django's admin site would pluralize "Category" as
        # "Categorys" (just adding an "s") - this fixes the grammar.
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    """Catalog entry with the inventory counters the concurrency logic relies on.

    `stock` and `reserved` are the only fields any code may write to, and only
    through apps.orders.services — never directly from another app. `available`
    is deliberately not stored: it's always `stock - reserved`, so it can never
    drift out of sync with the two fields it's derived from.

    BEGINNER NOTE on stock vs reserved vs available: `stock` is the total
    number ever had (fixed, like a theater's total seat count). `reserved`
    is how many are currently claimed - pending payment OR already paid,
    this field doesn't distinguish between the two. `available` is just the
    subtraction, calculated fresh every single time it's read, which is
    exactly why it's a @property below instead of a real database column -
    a stored, separately-updated column could accidentally drift out of
    sync with the two real numbers it depends on; a computed value never can.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    # TextField rather than URLField: this holds either a real hosted URL or
    # an inline `data:image/svg+xml,...` URI for the built-in icon art (see
    # apps.catalog.demo_icons), and those routinely run well past URLField's
    # default 200-char limit and aren't valid per URLField's URL regex anyway.
    image_url = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    is_active = models.BooleanField(default=True, help_text="Unlisted products stay for order history but drop out of the public catalog.")

    # These three numbers are the entire inventory-tracking system this
    # project is built around. See apps/orders/services.py's begin_checkout()
    # for where `reserved` goes UP, and apps/orders/tasks.py's
    # expire_single_reservation() for the only place it ever goes back DOWN.
    # `stock` itself is never changed anywhere in the real checkout/payment
    # flow at all - only `reserved` moves.
    stock = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    # A counter that increases by 1 every time this product's reserved
    # count changes (see begin_checkout's `product.version += 1`) - kept as
    # a simple audit trail of "how many times has this row been touched,"
    # not something the locking logic itself depends on (the real
    # correctness guarantee is select_for_update(), not this counter).
    version = models.PositiveIntegerField(default=0)

    # Populated by apps.assistant.embeddings (Gemini's embedding model) via
    # the backfill_embeddings management command. Null until embedded - the
    # RAG search excludes products with no embedding rather than erroring.
    #
    # BEGINNER NOTE: an "embedding" is a list of EMBEDDING_DIMENSIONS (768)
    # numbers that represent this product's MEANING as coordinates on a
    # giant imaginary map - products with similar meaning end up with
    # similar numbers, even if they share no words of text at all. See
    # apps/assistant/search.py for how a search query gets turned into the
    # same kind of coordinates and matched against these.
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # An HNSW index is a special structure that lets Postgres find
            # "which products have embeddings closest to this one" quickly,
            # without comparing against every single product in the table
            # one by one - without this index, meaning-based search would
            # get slower and slower as the catalog grows.
            HnswIndex(
                name="product_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    @property
    def available(self):
        # @property means this runs as plain code every time something
        # does `product.available` - it looks like reading a normal field,
        # but it's actually calling this function fresh each time, never
        # reading a stored value.
        return self.stock - self.reserved

    def __str__(self):
        return self.name
