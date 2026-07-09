"""Search-query language normalization.

ROOT CAUSE this fixes (found 2026-06-29): the local corpus is English papers,
but a Chinese research direction was passed verbatim to the underlying retrieval,
which matches literally (FTS) → 0 hits → 0 evidence → ungrounded ideas. Verified
by a controlled test: English query "perovskite solar cell stability" → 3 hits,
Chinese "钙钛矿太阳能电池 稳定性" → 0 hits on the same corpus.

So before a corpus retrieval step runs, translate a non-ASCII (e.g. Chinese)
direction into a concise English search query. The display topic stays as the
user wrote it; only the retrieval query is normalized. Degrades to the original
text if no LLM is available (English input is unaffected — it's passed through).
"""
from __future__ import annotations

import asyncio

_SYSTEM = (
    "You convert a research topic into a concise English search query for an "
    "English-only academic paper corpus (keyword-style, no quotes, no boolean "
    "operators, no explanation). Output ONLY the English query on a single line."
)


def needs_translation(text: str | None) -> bool:
    """True if the text contains non-ASCII characters (e.g. CJK)."""
    return any(ord(ch) > 127 for ch in (text or ""))


def _default_llm(user_id: str | None = None):
    from core.settings_store import settings_store
    from core.llm.client import build_llm_client

    return build_llm_client(settings_store, user_id=user_id)


async def _translate(llm, text: str) -> str:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": text},
    ]
    parts: list[str] = []
    async for delta in llm.stream_chat(messages, None):
        if delta.get("type") == "content":
            parts.append(delta.get("text") or "")
    # Keep the first non-empty line only — defends against a chatty model.
    out = "".join(parts).strip()
    return out.splitlines()[0].strip() if out else ""


def to_search_query(topic: str | None, llm_factory=None, *, user_id: str | None = None) -> str:
    """Return an English search query for ``topic``.

    ASCII topics pass through unchanged. Non-ASCII topics are translated via the
    LLM; any failure degrades to the original text (never raises)."""
    topic = topic or ""
    if not needs_translation(topic):
        return topic
    try:
        llm = llm_factory() if llm_factory is not None else _default_llm(user_id)
        translated = asyncio.run(_translate(llm, topic))
        return translated or topic
    except Exception:  # noqa: BLE001 - degrade to the original direction
        return topic
