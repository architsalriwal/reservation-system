# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# "Semantic search" means searching by MEANING instead of exact keyword
# match - an "embedding" is a list of numbers (768 of them here) that
# represents what a piece of text is actually about, produced by an AI
# model. Two pieces of text about similar things end up with similar
# number-lists; two unrelated pieces of text end up with very different
# ones. "Cosine distance" is just the math formula for measuring how
# similar two of these number-lists are - pgvector (a Postgres extension)
# can sort rows by that distance directly in a database query.
#
# These tests don't call the real Gemini AI model to generate embeddings
# (that would be slow, cost money, and make tests non-deterministic) -
# they fake embed_query_text() to return a hand-picked vector instead, so
# what's actually being tested is the database/ranking logic, not whether
# Gemini is good at understanding language.
# ============================================================================

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
    # e.g. _vector(0, 1) makes a vector pointing in the "0 and 1" direction,
    # and _vector(500, 501) points in a totally different direction - cosine
    # distance between those two is large (far apart in meaning), while two
    # vectors built from the SAME dimensions are identical (distance zero) -
    # which is exactly what lets these tests predict, with certainty, which
    # product should rank first without needing real AI-generated embeddings.
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
