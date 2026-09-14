from django.db import models
from pgvector.django import HnswIndex, VectorField

EMBEDDING_DIMENSIONS = 768


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    """Catalog entry with the inventory counters the concurrency logic relies on.

    `stock` and `reserved` are the only fields any code may write to, and only
    through apps.orders.services — never directly from another app. `available`
    is deliberately not stored: it's always `stock - reserved`, so it can never
    drift out of sync with the two fields it's derived from.
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

    stock = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)

    # Populated by apps.assistant.embeddings (Gemini's embedding model) via
    # the backfill_embeddings management command. Null until embedded - the
    # RAG search excludes products with no embedding rather than erroring.
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
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
        return self.stock - self.reserved

    def __str__(self):
        return self.name
