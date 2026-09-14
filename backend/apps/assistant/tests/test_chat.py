"""Proof for the function-calling half: Gemini itself is mocked (no real API
call in the suite), but the loop logic - detect a function call, run the
real tool, feed the result back, get a final answer - is exercised for
real. This is what would catch a bug in how we parse Gemini's response
shape or build the follow-up turn, which a purely-mocked-end-to-end test
would hide.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.assistant.chat import run_chat
from apps.catalog.models import Product
from apps.orders.tests.factories import ProductFactory


def _function_call_response(name, args):
    call = SimpleNamespace(name=name, args=args)
    part = SimpleNamespace(function_call=call)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def _text_response(text):
    content = SimpleNamespace(parts=[])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)], text=text)


@pytest.mark.django_db
def test_chat_loop_executes_search_tool_and_returns_final_reply():
    ProductFactory(name="Trail Runner", price=3499, embedding=[0.0] * 768)

    fake_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: responses.pop(0),
        )
    )
    responses = [
        _function_call_response("search_products", {"query": "running shoes"}),
        _text_response("I found the Trail Runner for you at ₹3,499."),
    ]

    with patch("apps.assistant.chat.get_client", return_value=fake_client), patch(
        "apps.assistant.tools.semantic_search",
        return_value=list(Product.objects.all()),
    ):
        result = run_chat("find me running shoes", [], user=None, session={})

    assert result["reply"] == "I found the Trail Runner for you at ₹3,499."
    assert result["tool_calls"][0]["name"] == "search_products"
    assert result["tool_calls"][0]["result"]["products"][0]["name"] == "Trail Runner"


@pytest.mark.django_db
def test_chat_loop_answers_directly_with_no_tool_call_needed():
    fake_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: _text_response("Hi! How can I help you shop today?"))
    )

    with patch("apps.assistant.chat.get_client", return_value=fake_client):
        result = run_chat("hello", [], user=None, session={})

    assert result["reply"] == "Hi! How can I help you shop today?"
    assert result["tool_calls"] == []
