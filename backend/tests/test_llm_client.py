from __future__ import annotations

from core.llm.client import OpenAIClient


def test_max_tokens_omitted_when_non_positive():
    """max_tokens<=0 means 'use the model's maximum' → omit it from the request."""
    client = OpenAIClient(api_key="x", model="m", max_tokens=0)
    kwargs = client._request_kwargs([{"role": "user", "content": "hi"}], None)
    assert "max_tokens" not in kwargs
    assert kwargs["model"] == "m"
    assert kwargs["stream"] is True


def test_max_tokens_included_when_positive():
    client = OpenAIClient(api_key="x", model="m", max_tokens=2048)
    kwargs = client._request_kwargs([], [{"type": "function", "function": {"name": "f"}}])
    assert kwargs["max_tokens"] == 2048
    assert kwargs["tool_choice"] == "auto"
