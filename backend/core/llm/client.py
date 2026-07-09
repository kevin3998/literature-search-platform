"""Provider-agnostic streaming chat client with tool/function calling.

Configuration (provider / model / base_url / temperature / ...) is read from the
current user's PostgreSQL-backed settings/profile stores. API key resolution
keeps environment variables first, then the active user profile, then the user's
stored provider secret.

The client exposes a single coroutine `stream_chat(messages, tools)` returning an
async iterator of deltas. Each delta is one of:

    {"type": "content", "text": str}                  # streamed answer fragment
    {"type": "tool_call", "id": str, "name": str, "arguments": dict}

Content deltas stream live (typewriter effect); tool calls are accumulated and
emitted once complete, after the model finishes the turn.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class LLMUnavailable(RuntimeError):
    """Raised when no usable LLM is configured."""


class LLMClient(ABC):
    """Minimal streaming chat interface the agent loop depends on.

    Tests inject a scripted subclass; production uses :class:`OpenAIClient`.
    """

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 0,
        timeout_seconds: int = 60,
        retry_count: int = 2,
    ) -> None:
        # Imported lazily so the backend still boots without the dependency when
        # the agent path is disabled; a missing SDK degrades to retrieval summary.
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMUnavailable(
                "openai SDK 未安装：请在后端环境运行 pip install -r requirements.txt"
            ) from exc

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout_seconds,
            max_retries=retry_count,
        )

    def _request_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
        }
        # max_tokens caps the model's OUTPUT length. A non-positive value means
        # "no explicit cap" — omit it so the provider uses the model's own maximum
        # (there is no portable way to query a model's max output, and omitting is
        # the standard way to let the model decide).
        if isinstance(self.max_tokens, int) and self.max_tokens > 0:
            kwargs["max_tokens"] = self.max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs = self._request_kwargs(messages, tools)

        # Accumulate streamed tool-call fragments keyed by their stream index.
        pending: dict[int, dict[str, Any]] = {}
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if getattr(delta, "content", None):
                yield {"type": "content", "text": delta.content}
            for call in getattr(delta, "tool_calls", None) or []:
                slot = pending.setdefault(
                    call.index,
                    {"id": None, "name": "", "arguments": ""},
                )
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["name"] = call.function.name
                if call.function and call.function.arguments:
                    slot["arguments"] += call.function.arguments

        for slot in pending.values():
            if not slot.get("name"):
                continue
            yield {
                "type": "tool_call",
                "id": slot.get("id") or slot["name"],
                "name": slot["name"],
                "arguments": _safe_json(slot.get("arguments")),
            }


def _safe_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except (json.JSONDecodeError, TypeError):
        return {}


def build_llm_client(settings_store, *, strong: bool = False, user_id: str | None = None) -> LLMClient:
    """Construct an :class:`LLMClient` from current settings.

    Raises :class:`LLMUnavailable` when the configuration cannot produce a usable
    client (provider ``none``, missing key, unsupported provider, ...).
    """
    if not settings_store.llm_enabled(user_id=user_id):
        raise LLMUnavailable("LLM is not enabled (provider=none, agent disabled, or missing API key)")

    config = settings_store.model_config(user_id=user_id)
    provider = config["provider"]
    model = config["strong_model"] if strong and config.get("strong_model") else config["chat_model"]
    if not model:
        raise LLMUnavailable("no chat model configured (Settings → Models → chat_model)")

    if provider in {"openai", "openai_compatible", "deepseek", "ollama"}:
        api_key = _resolve_api_key(settings_store, provider, user_id=user_id)
        base_url = config.get("base_url") or _default_base_url(provider)
        return OpenAIClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=_as_float(config.get("temperature"), 0.2),
            max_tokens=_as_int(config.get("max_tokens"), 0),
            timeout_seconds=_as_int(config.get("timeout_seconds"), 60),
            retry_count=_as_int(config.get("retry_count"), 2),
        )

    raise LLMUnavailable(f"provider '{provider}' is not supported by the agent yet")


def resolve_api_key(provider: str, *, user_id: str | None = None) -> str | None:
    """Resolve a provider's API key.

    Precedence: env var → active model profile's key → per-provider stored key →
    ``ollama`` dummy. Returns None when nothing is configured.
    """
    from core.secret_store import secret_store
    from core.settings_store import SECRET_ENV_BY_PROVIDER

    for name in SECRET_ENV_BY_PROVIDER.get(provider, ["LITERATURE_LLM_API_KEY"]):
        value = os.getenv(name)
        if value:
            return value

    from core.model_profiles import model_profile_store

    active = model_profile_store.active(user_id=user_id)
    if active and active.get("provider") == provider:
        key = model_profile_store.active_api_key(user_id=user_id)
        if key:
            return key

    stored = secret_store.get(provider, user_id=user_id)
    if stored:
        return stored
    if provider == "ollama":
        return "ollama"
    return None


def _resolve_api_key(settings_store, provider: str, *, user_id: str | None = None) -> str:
    value = resolve_api_key(provider, user_id=user_id)
    if value:
        return value
    raise LLMUnavailable(f"missing API key for provider '{provider}' (set env var or save it in Settings)")


def test_chat_completion(*, provider: str, model: str, base_url: str | None, api_key: str, timeout: int = 15) -> dict:
    """Issue one minimal completion to verify key + base_url + model are live.

    Always returns a result dict (never raises) so the test endpoint can't 500 —
    missing SDK / network / auth errors come back as ``available: false``.
    """
    import time

    try:
        from openai import OpenAI
    except ImportError:
        return {
            "available": False,
            "provider": provider,
            "model": model,
            "message": "未安装 openai 依赖：请在后端环境运行 pip install -r requirements.txt 后重启。",
        }

    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except Exception:  # noqa: BLE001 - keep working if SDK internals move
        APIConnectionError = APITimeoutError = APIStatusError = ()  # type: ignore[assignment]

    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout, max_retries=0)
        # Use a natural-looking minimal chat; probe-style requests (max_tokens=1,
        # content "ping") are often blocked by relay anti-abuse/WAF filters.
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=16,
        )
        latency_ms = int((time.time() - started) * 1000)
        return {
            "available": True,
            "reached_server": True,
            "provider": provider,
            "model": resp.model or model,
            "latency_ms": latency_ms,
        }
    except APITimeoutError as exc:
        return _fail(provider, model, started, "timeout", str(exc), reached_server=False,
                     message="连接超时：服务端在超时时间内未响应。")
    except APIConnectionError as exc:
        return _fail(provider, model, started, "connection", str(exc), reached_server=False,
                     message="无法连接到服务端：检查 base_url 是否正确、网络是否可达。")
    except APIStatusError as exc:
        status = getattr(exc, "status_code", None)
        return _fail(provider, model, started, "api_status", str(exc), reached_server=True, status_code=status,
                     message=f"已连接到服务端，但请求被拒绝（HTTP {status}）；延迟为往返到该响应的耗时。"
                             "常见原因：密钥无效/额度不足、模型名不被该服务商支持，或服务商风控拦截。")
    except Exception as exc:  # noqa: BLE001 - report any other provider error verbatim
        return _fail(provider, model, started, "other", str(exc), reached_server=False)


def _fail(provider, model, started, kind, error, *, reached_server, status_code=None, message=None) -> dict:
    import time

    result = {
        "available": False,
        "reached_server": reached_server,
        "provider": provider,
        "model": model,
        "latency_ms": int((time.time() - started) * 1000),
        "error_kind": kind,
        "error": error,
    }
    if status_code is not None:
        result["status_code"] = status_code
    if message:
        result["message"] = message
    return result


def _default_base_url(provider: str) -> str | None:
    return {
        "deepseek": "https://api.deepseek.com/v1",
        "ollama": "http://127.0.0.1:11434/v1",
    }.get(provider)


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
