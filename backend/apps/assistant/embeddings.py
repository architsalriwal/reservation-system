"""Text -> vector for RAG product search.

A product's embedding is computed once (see the backfill_embeddings
management command) from its name/category/description and stored on
Product.embedding (pgvector). A search query is embedded the same way at
request time and compared by cosine distance - see search() in services.py.

BEGINNER NOTE: "embedding" text just means "ask an AI model to convert this
text into a list of 768 numbers representing its meaning." This file is
the ONLY place in the project that actually calls Gemini's embedding
model - both the one-time product indexing (the management command) and
the live search.py both funnel through the two functions below.
"""

from django.conf import settings
from google.genai import types

from apps.assistant.gemini_client import get_client
from apps.catalog.models import EMBEDDING_DIMENSIONS


def _embed(text, task_type):
    # The actual call out to Gemini's embedding model. `task_type` tells
    # Gemini WHICH of the two functions below is calling it - some
    # embedding models produce slightly better results when they know
    # whether the text being embedded is "a document to be found later"
    # versus "a search query looking for a document," even though both
    # eventually produce the same kind of 768-number output.
    response = get_client().models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            # Explicitly request 768 numbers back, matching
            # catalog/models.py's EMBEDDING_DIMENSIONS - both this call and
            # the database column it eventually gets stored in need to
            # agree on exactly this same size.
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )
    return response.embeddings[0].values


def embed_product_text(text):
    # Used ONCE per product, ahead of time, by the backfill_embeddings
    # management command - turns a product's description into its
    # permanent, stored `embedding` field (catalog/models.py).
    return _embed(text, task_type="RETRIEVAL_DOCUMENT")


def embed_query_text(text):
    # Used EVERY TIME someone searches - see search.py's semantic_search(),
    # called live, on every request, unlike embed_product_text above.
    return _embed(text, task_type="RETRIEVAL_QUERY")


def product_embedding_source(product):
    # Decides exactly what TEXT gets embedded for a product - its name,
    # category, and description, joined together. Whatever text goes in
    # here directly shapes what kind of search queries will successfully
    # match this product later.
    parts = [product.name]
    if product.category:
        parts.append(product.category.name)
    if product.description:
        parts.append(product.description)
    return " — ".join(parts)
