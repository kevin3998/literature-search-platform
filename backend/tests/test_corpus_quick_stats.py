from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class _Service:
    def __init__(self, data_dir: Path, db_path: Path):
        self.data_dir = data_dir
        self._db_path = db_path

    class _Paths:
        def __init__(self, db_path: Path):
            self.index_db = db_path

    @property
    def paths(self):
        return self._Paths(self._db_path)

    def vector_status(self):
        return {"vector_index_exists": False}


def _build_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "research_index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table article_index(article_id integer primary key, doi text, indexed_at text);
        create table papers (
            paper_id text primary key, article_id integer, doi text, title text,
            authors_json text not null default '[]', year text, journal text,
            site text, article_dir text, md_path text, abstract_path text,
            parse_quality real not null default 0, library_tags_json text not null default '[]',
            metadata_json text not null default '{}', indexed_at text not null,
            mtime real not null default 0, index_version integer not null default 0
        );
        create table paper_sections(id integer primary key, paper_id text, source_path text);
        create table paper_chunks(id integer primary key, paper_id text, source_path text);
        create table paper_assets(id integer primary key, paper_id text, kind text, source_path text);
        create table vector_records(document_id integer primary key, paper_id text);
        """
    )
    rows = [
        ("p1", 1, "10.1/a", "Alpha", "2022", "Journal A", "2026-07-01T10:00:00", 10.0),
        ("p2", 2, "10.1/b", "Beta", "2024", "Journal A", "2026-07-02T10:00:00", 20.0),
        ("p3", 3, "10.1/c", "Gamma", "2024", "Journal B", "2026-07-03T10:00:00", 30.0),
    ]
    for paper_id, article_id, doi, title, year, journal, indexed_at, mtime in rows:
        conn.execute(
            """
            insert into papers(
                paper_id, article_id, doi, title, year, journal, site, article_dir,
                md_path, abstract_path, indexed_at, mtime, index_version
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (paper_id, article_id, doi, title, year, journal, "site", "", "", "", indexed_at, mtime, 3),
        )
        conn.execute("insert into article_index(article_id, doi, indexed_at) values(?,?,?)", (article_id, doi, indexed_at))
        conn.execute("insert into paper_sections(paper_id, source_path) values(?,?)", (paper_id, "s"))
        conn.execute("insert into paper_chunks(paper_id, source_path) values(?,?)", (paper_id, "c"))
    conn.commit()
    conn.close()
    return db_path


def test_quick_stats_returns_metadata_without_dashboard(tmp_path: Path) -> None:
    from modules.literature_search.corpus import CorpusService

    db_path = _build_db(tmp_path)
    stats = CorpusService(_Service(tmp_path, db_path), index_db_path=db_path, data_dir=tmp_path).quick_stats()

    assert stats["index_available"] is True
    assert stats["paper_count"] == 3
    assert stats["article_index_count"] == 3
    assert stats["section_count"] == 3
    assert stats["chunk_count"] == 3
    assert stats["year_range"] == [2022, 2024]
    assert stats["top_years"][0] == {"year": 2024, "count": 2}
    assert stats["top_journals"][0] == {"journal": "Journal A", "count": 2}
    assert stats["recent_imports"][0]["paper_id"] == "p3"
    assert stats["vector_built"] is False


def test_quick_stats_reports_unavailable_index(tmp_path: Path) -> None:
    from modules.literature_search.corpus import CorpusService

    missing = tmp_path / "missing.sqlite"
    stats = CorpusService(_Service(tmp_path, missing), index_db_path=missing, data_dir=tmp_path).quick_stats()

    assert stats["index_available"] is False
    assert stats["paper_count"] == 0
    assert stats["recent_imports"] == []
