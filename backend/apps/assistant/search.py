from pgvector.django import CosineDistance

from apps.assistant.embeddings import embed_query_text
from apps.catalog.models import Product


def semantic_search(query, limit=5):
    """RAG retrieval: embeds the query and returns the closest products by
    cosine distance over their precomputed embeddings. Products without an
    embedding yet (not yet backfilled) are excluded rather than erroring.
    """
    query_vector = embed_query_text(query)
    return list(
        Product.objects.filter(is_active=True, embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[:limit]
    )
