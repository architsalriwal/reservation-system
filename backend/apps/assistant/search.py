# This file is the "RAG" (retrieval-augmented generation) half of the AI
# assistant - finding products by MEANING instead of exact keyword
# matching. "something for a morning run" can match a product literally
# named "Trail Runner Shoes" even though neither phrase shares a single
# word with the other, because both get converted to coordinates on the
# same "meaning map" (see catalog/models.py's `embedding` field for more on
# what that map actually is).

from pgvector.django import CosineDistance

from apps.assistant.embeddings import embed_query_text
from apps.catalog.models import Product


def semantic_search(query, limit=5):
    """RAG retrieval: embeds the query and returns the closest products by
    cosine distance over their precomputed embeddings. Products without an
    embedding yet (not yet backfilled) are excluded rather than erroring.
    """
    # Turns the plain search text into the SAME kind of 768-number
    # coordinates every product's `embedding` field already holds - see
    # embeddings.py for how this conversion actually happens (it calls
    # Gemini's embedding model, the same one used to embed every product
    # ahead of time).
    query_vector = embed_query_text(query)
    return list(
        Product.objects
        # Skip products that were never embedded (e.g. added before the
        # backfill ran) instead of erroring on them - a missing embedding
        # just means "this product can't currently be found by meaning
        # search," not a bug to crash over.
        .filter(is_active=True, embedding__isnull=False)
        # CosineDistance measures how "close together" two sets of
        # coordinates are on that meaning-map - a SMALLER number means
        # MORE similar meaning. .annotate(...) attaches this computed
        # distance as an extra, queryable value on each result row, and
        # .order_by("distance") then sorts so the closest (most relevant)
        # matches come first.
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[:limit]
    )
