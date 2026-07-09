from __future__ import annotations

from modules.workflow.external_novelty.arxiv import normalize_arxiv_id, parse_atom
from modules.workflow.external_novelty.models import PaperCandidate
from modules.workflow.external_novelty.openalex import parse_work
from modules.workflow.external_novelty.query_builder import build_query_packet
from modules.workflow.external_novelty.semantic_scholar import parse_paper
from modules.workflow.external_novelty.service import ExternalNoveltySearchService
from modules.workflow.external_novelty.verifier import verify_candidates


def test_query_builder_filters_template_terms_and_keeps_domain_anchors():
    packet = build_query_packet(
        "大语言模型在材料科学领域的应用",
        "### Idea 1：LLM 驱动的多模态材料表征融合\n"
        "- prior_work: [UNVERIFIED]\n"
        "- so_what: materials microscopy XRD SEM with GPT-4\n"
        "- 风险：MEDIUM",
    )

    flat = " ".join(q for qs in packet.queries_by_idea.values() for q in qs).lower()
    assert "prior_work" not in flat
    assert "so_what" not in flat
    assert "unverified" not in flat
    assert "medium" not in flat
    assert "materials science" in flat
    assert any("xrd" in q.lower() or "sem" in q.lower() for qs in packet.queries_by_idea.values() for q in qs)
    assert {"prior_work", "so_what", "unverified", "medium"} <= set(packet.dropped_template_terms)


def test_arxiv_parser_normalizes_versioned_ids():
    raw = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2401.11052v2</id>
        <title>Mining experimental data from Materials Science literature with Large Language Models</title>
        <summary>LLMs for materials science extraction.</summary>
        <published>2024-01-19T00:00:00Z</published>
        <updated>2024-05-30T00:00:00Z</updated>
        <author><name>Alice</name></author>
        <category term="cs.CL" />
      </entry>
    </feed>"""

    assert normalize_arxiv_id("https://arxiv.org/abs/2401.11052v2") == "2401.11052"
    parsed = parse_atom(raw, query="materials llm")
    assert parsed[0].arxiv_id == "2401.11052"
    assert parsed[0].verification == "verify_pending"
    assert parsed[0].source == "arxiv"
    assert parsed[0].year == 2024


def test_semantic_scholar_parser_extracts_identifiers_and_venue():
    paper = parse_paper(
        {
            "paperId": "abc",
            "title": "Materials language models",
            "abstract": "A paper.",
            "year": 2025,
            "venue": "Nature Materials",
            "externalIds": {"DOI": "10.1234/example", "ArXiv": "2501.00001"},
            "citationCount": 12,
        },
        query="materials llm",
    )

    assert paper.doi == "10.1234/example"
    assert paper.arxiv_id == "2501.00001"
    assert paper.venue == "Nature Materials"
    assert paper.citation_count == 12


def test_openalex_parser_reconstructs_inverted_abstract():
    paper = parse_work(
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.5555/demo",
            "display_name": "LLM agents for materials",
            "publication_year": 2026,
            "primary_location": {"source": {"display_name": "Open Journal", "type": "journal"}},
            "abstract_inverted_index": {"Large": [0], "models": [2], "language": [1]},
            "cited_by_count": 9,
        },
        query="materials agents",
    )

    assert paper.abstract == "Large language models"
    assert paper.doi == "10.5555/demo"
    assert paper.venue == "Open Journal"


def test_verifier_applies_arxiv_doi_title_and_pending_statuses():
    candidates = [
        PaperCandidate(id="a", title="A", source="arxiv", arxiv_id="2401.11052"),
        PaperCandidate(id="d", title="D", source="openalex", doi="10.1000/demo"),
        PaperCandidate(id="t", title="Known Materials LLM Paper", source="semantic_scholar"),
        PaperCandidate(id="p", title="Pending Paper", source="semantic_scholar"),
    ]

    result = verify_candidates(
        candidates,
        arxiv_lookup=lambda ids: {"2401.11052": "verified"},
        doi_lookup=lambda doi: "verified" if doi == "10.1000/demo" else "unverified",
        title_lookup=lambda title: "verified" if title.startswith("Known") else "verify_pending",
    )

    statuses = {paper.id: paper.verification for paper in result.papers}
    assert statuses == {"a": "verified", "d": "verified", "t": "verified", "p": "verify_pending"}
    assert result.verdict == "WARN"
    assert result.pending_rate == 0.25


def test_external_novelty_service_returns_verified_packet_and_query_quality():
    def arxiv_source(query, year_from, year_to, limit):
        return [PaperCandidate(id="arxiv-1", title="Materials Science literature with Large Language Models", source="arxiv", arxiv_id="2401.11052", year=2024, query=query)]

    service = ExternalNoveltySearchService(
        sources={"arxiv": arxiv_source},
        arxiv_lookup=lambda ids: {"2401.11052": "verified"},
        doi_lookup=lambda doi: "unverified",
        title_lookup=lambda title: "unverified",
    )

    packet = service.search(
        "大语言模型在材料科学领域的应用",
        "Idea 1：materials science LLM extraction prior_work unverified so_what",
    )

    assert packet.candidates[0].verification == "verified"
    assert packet.verification_summary.verdict == "PASS"
    assert packet.query_quality["dropped_template_terms"]
    assert packet.source_status["arxiv"]["status"] == "ok"


def test_external_novelty_service_uses_settings_defaults_and_stored_source_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))

    from core.settings_store import SettingsStore
    import core.secret_store as secret_module

    secrets = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    secrets.set("external:semantic_scholar", "s2-stored-key")
    store = SettingsStore(db_path=tmp_path / "memory.sqlite")
    store.patch({
        "external_sources": {
            "arxiv_enabled": False,
            "semantic_scholar_enabled": True,
            "openalex_enabled": False,
            "exa_enabled": False,
            "default_year_window": 2,
            "per_source_limit": 3,
        }
    })

    calls = []

    def semantic_source(query, year_from, year_to, limit):
        calls.append((query, year_from, year_to, limit))
        return [PaperCandidate(id="s2-1", title="Known Materials LLM Paper", source="semantic_scholar", query=query)]

    service = ExternalNoveltySearchService(
        sources={"semantic_scholar": semantic_source},
        settings_store=store,
        secret_store=secrets,
        title_lookup=lambda title: "verified",
    )
    packet = service.search("materials LLM", "Idea 1: materials science LLM extraction", current_year=2026)

    assert calls
    assert calls[0][1:] == (2024, 2026, 3)
    assert packet.source_status["semantic_scholar"]["api_key_configured"] is True
    assert packet.candidates[0].verification == "verified"
