"""Block 0 acceptance: canonical paper_id identity + Research Index Health."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def _build_index(data_dir: Path) -> Path:
    """Create a tiny research_index.sqlite mirroring the real schema subset."""
    agent_dir = data_dir / "research_agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    db_path = agent_dir / "research_index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table papers (
            paper_id text primary key, article_id integer not null unique, doi text,
            title text, authors_json text not null default '[]', year text, journal text,
            site text, article_dir text not null, md_path text, abstract_path text,
            parse_quality real not null default 0, library_tags_json text not null default '[]',
            metadata_json text not null default '{}', indexed_at text not null,
            mtime real not null default 0, index_version integer not null default 0
        );
        create table paper_sections (
            id integer primary key autoincrement, paper_id text not null, section_id text not null,
            source_path text not null
        );
        create table paper_chunks (
            id integer primary key autoincrement, paper_id text not null, source_path text not null
        );
        create table paper_assets (
            id integer primary key autoincrement, paper_id text not null, kind text not null,
            source_path text not null, label text
        );
        create table vector_records (document_id integer primary key, paper_id text);
        """
    )
    article_dir = "articles/wiley/_library/10.1-x"
    md_path = f"{article_dir}/parsed/fulltext.md"
    conn.execute(
        "insert into papers values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "10.1/x", 12, "10.1/X", "A Membrane Paper", json.dumps(["Jane Doe"]), "2025",
            "Journal of Tests", "wiley", article_dir, md_path, f"{article_dir}/parsed/abstract.txt",
            0.9, "[]", json.dumps({"keywords": ["membrane"]}), "2026-05-25T11:11:01", 1777281194.0, 3,
        ),
    )
    conn.execute(
        "insert into paper_sections(paper_id, section_id, source_path) values (?,?,?)",
        ("10.1/x", "results", md_path),
    )
    conn.execute(
        "insert into paper_assets(paper_id, kind, source_path, label) values (?,?,?,?)",
        ("10.1/x", "figure", f"{article_dir}/assets/figures/fig_001.txt", "Figure 1"),
    )
    conn.commit()
    conn.close()

    # md + abstract exist on disk; the figure asset deliberately does NOT.
    abs_md = data_dir / md_path
    abs_md.parent.mkdir(parents=True, exist_ok=True)
    abs_md.write_text("# fulltext\n", encoding="utf-8")
    (data_dir / article_dir / "parsed" / "abstract.txt").write_text("abstract\n", encoding="utf-8")
    return db_path


class _FakeService:
    def __init__(self, data_dir: Path, index_db: Path):
        self.data_dir = data_dir
        self._index_db = index_db

    class _Paths:
        def __init__(self, index_db):
            self.index_db = index_db

    @property
    def paths(self):
        return self._Paths(self._index_db)

    def index_status(self):
        return {"papers": 1, "documents": 2, "sections": 1, "chunks": 0, "warnings": 0, "errors": []}

    def vector_status(self):
        return {"vector_index_exists": False, "missing_vectors": 0, "stale_vectors": 0}


@pytest.fixture()
def corpus(tmp_path):
    from modules.literature_search.corpus import CorpusService

    data_dir = tmp_path / "data"
    db = _build_index(data_dir)
    return CorpusService(_FakeService(data_dir, db), index_db_path=db, data_dir=data_dir)


def test_doi_resolves_to_canonical_paper_id(corpus):
    ref = corpus.resolve(doi="10.1/X")  # case-insensitive
    assert ref["paper_id"] == "10.1/x"
    assert ref["article_id"] == 12
    assert ref["index_version"] == 3
    assert ref["matched_on"] == "doi"
    assert ref["authors"] == ["Jane Doe"]


def test_article_id_and_source_path_resolve_to_same_paper_id(corpus):
    by_article = corpus.resolve(article_id=12)
    by_path = corpus.resolve(source_path="articles/wiley/_library/10.1-x/parsed/fulltext.md")
    assert by_article["paper_id"] == by_path["paper_id"] == "10.1/x"
    assert by_path["matched_on"] in {"md_path", "section_path"}


def test_missing_paths_are_detected(corpus):
    report = corpus.check_paths(paper_id="10.1/x")
    assert report["ok"] is False
    assert report["missing_count"] == 1
    missing = report["missing"][0]
    assert missing["role"] == "figure"
    # the markdown file exists, only the figure asset is missing
    assert any(f["role"] == "markdown" and f["exists"] for f in report["files"])


def test_coverage_counts_report_assets_and_index_version(corpus):
    counts = corpus.coverage_counts()
    assert counts["papers"] == 1
    assert counts["sections"] == 1
    assert counts["assets"]["figure"] == 1
    assert counts["vector_records"] == 0
    assert counts["index_versions"] == {"3": 1}


def test_dashboard_surfaces_vector_warning_and_role(corpus):
    dash = corpus.dashboard(role="admin")
    assert dash["index_available"] is True
    assert dash["vector"]["built"] is False
    assert dash["vector"]["reason"] == "vector_index_not_built"
    assert dash["capabilities"]["can_maintain"] is True
    assert "vector_build" in dash["capabilities"]["maintenance_actions"]
    assert dash["coverage"]["papers"] == 1

    viewer = corpus.dashboard(role="viewer")
    assert viewer["capabilities"]["can_maintain"] is False
    assert viewer["capabilities"]["maintenance_actions"] == []


def test_dashboard_reports_running_maintenance_without_scanning_index(corpus):
    dash = corpus.dashboard(
        role="admin",
        recent_jobs=[{"job_id": "job_x", "job_type": "index_refresh", "status": "running"}],
    )
    assert dash["overall_status"] == "updating"
    assert dash["running_maintenance"]["job_id"] == "job_x"
    assert dash["warnings"] == ["index_refresh_running"]
    assert dash["coverage"] == {}


def test_unknown_doi_raises_not_found(corpus):
    from modules.literature_search.corpus import PaperNotFound

    with pytest.raises(PaperNotFound):
        corpus.resolve(doi="10.9/nope")
