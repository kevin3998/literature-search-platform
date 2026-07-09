"""Compatibility facade for platform-native external novelty search."""
from __future__ import annotations

from .external_novelty.service import render_external_context, search_external_sources
from .external_novelty.query_builder import build_query_packet


def build_query_plan(topic: str, idea_text: str, *, max_queries: int = 3) -> list[str]:
    packet = build_query_packet(topic, idea_text, max_queries_per_idea=max_queries)
    return packet.flat_queries[:max_queries]


__all__ = ["build_query_plan", "search_external_sources", "render_external_context"]
