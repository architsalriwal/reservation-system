"""Text -> vector for RAG product search.

A product's embedding is computed once (see the backfill_embeddings
management command) from its name/category/description and stored on
Product.embedding (pgvector). A search query is embedded the same way at
request time and compared by cosine distance - see search() in services.py.
"""

from django.conf import settings
from google.genai import types

from apps.assistant.gemini_client import get_client
from apps.catalog.models import EMBEDDING_DIMENSIONS


def _embed(text, task_type):
    response = get_client().models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )
    return response.embeddings[0].values


def embed_product_text(text):
    return _embed(text, task_type="RETRIEVAL_DOCUMENT")


def embed_query_text(text):
    return _embed(text, task_type="RETRIEVAL_QUERY")


def product_embedding_source(product):
    parts = [product.name]
    if product.category:
        parts.append(product.category.name)
    if product.description:
        parts.append(product.description)
    return " — ".join(parts)
