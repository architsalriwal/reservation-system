"""Proof for the RAG half: a product's embedding is precomputed, a query is
embedded the same way at request time, and pgvector's cosine distance ranks
the closer match first. The embedding call itself is mocked (no real Gemini
call in the test suite) - what's under test is that semantic_search wires
the query embedding into a real pgvector ORDER BY correctly, not whether
Gemini's embeddings are good.
"""

from unittest.mock import patch

import pytest

from apps.assistant.search import semantic_search
from apps.orders.tests.factories import ProductFactory


def _vector(*nonzero_dims):
    """A 768-dim vector that's 1.0 in the given dimensions, 0 elsewhere -
    easy to reason about under cosine distance."""
    v = [0.0] * 768
    for d in nonzero_dims:
        v[d] = 1.0
    return v


@pytest.mark.django_db
def test_semantic_search_ranks_closer_embedding_first():
    running_shoe = ProductFactory(name="Trail Runner", embedding=_vector(0, 1))
    coffee_mug = ProductFactory(name="Ceramic Mug", embedding=_vector(500, 501))

    with patch("apps.assistant.search.embed_query_text", return_value=_vector(0, 1)):
        results = semantic_search("shoes for running", limit=5)

    assert results[0].id == running_shoe.id
    assert results[-1].id == coffee_mug.id


@pytest.mark.django_db
def test_semantic_search_excludes_products_without_an_embedding():
    ProductFactory(name="Not yet embedded", embedding=None)
    embedded = ProductFactory(name="Embedded", embedding=_vector(0))

    with patch("apps.assistant.search.embed_query_text", return_value=_vector(0)):
        results = semantic_search("anything", limit=5)

    assert [p.id for p in results] == [embedded.id]


@pytest.mark.django_db
def test_semantic_search_excludes_delisted_products():
    ProductFactory(name="Delisted", embedding=_vector(0), is_active=False)
    active = ProductFactory(name="Active", embedding=_vector(0))

    with patch("apps.assistant.search.embed_query_text", return_value=_vector(0)):
        results = semantic_search("anything", limit=5)

    assert [p.id for p in results] == [active.id]
