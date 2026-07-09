from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_CODE_DIR = "/Users/chenlintao/paper-crawler-ops/literature_research"
DEFAULT_DATA_DIR = "/Users/chenlintao/paper-crawler-ops/literature_data"


class LiteratureResearchService:
    def __init__(
        self,
        *,
        code_dir: str | None = None,
        data_dir: str | None = None,
        import_research: bool = True,
    ) -> None:
        self.code_dir = Path(code_dir or os.getenv("LITERATURE_RESEARCH_CODE_DIR") or DEFAULT_CODE_DIR).expanduser()
        self.data_dir = Path(data_dir or os.getenv("LITERATURE_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
        self.default_scope = os.getenv("LITERATURE_SEARCH_DEFAULT_SCOPE", "library")
        self.default_retrieval = os.getenv("LITERATURE_SEARCH_DEFAULT_RETRIEVAL", "hybrid")
        self._imports_ready = False
        if import_research:
            self._load_research_modules()

    def _load_research_modules(self) -> None:
        if not self.code_dir.exists():
            raise FileNotFoundError(f"research code dir does not exist: {self.code_dir}")
        code = str(self.code_dir)
        if code not in sys.path:
            sys.path.insert(0, code)

        from research.analysis import AnalysisBundleBuilder
        from research.evidence import EvidenceBridge
        from research.extract import MetricExtractor
        from research.indexer import ResearchIndexer
        from research.notes import ResearchNotesBuilder
        from research.pack import EvidencePacker
        from research.paper import PaperStore
        from research.paths import ResearchPaths
        from research.quality import ResearchQualityAuditor
        from research.run import ResearchRunManager
        from research import search as research_search_module
        from research.search import ResearchSearch
        from research.selfcheck import ResearchSelfCheck
        from research.synthesize import ResearchSynthesizer
        from research.task import ResearchTaskPlanner, ResearchTaskRunner
        from research.vector import VectorStore
        from research.verify import AnswerVerifier

        self.ResearchPaths = ResearchPaths
        self.ResearchSelfCheck = ResearchSelfCheck
        self.ResearchIndexer = ResearchIndexer
        self.ResearchSearch = _bounded_research_search_class(ResearchSearch, research_search_module)
        self.PaperStore = PaperStore
        self.EvidenceBridge = EvidenceBridge
        self.EvidencePacker = EvidencePacker
        self.ResearchTaskPlanner = ResearchTaskPlanner
        self.ResearchTaskRunner = ResearchTaskRunner
        self.ResearchRunManager = ResearchRunManager
        self.MetricExtractor = MetricExtractor
        self.AnalysisBundleBuilder = AnalysisBundleBuilder
        self.AnswerVerifier = AnswerVerifier
        self.ResearchNotesBuilder = ResearchNotesBuilder
        self.ResearchSynthesizer = ResearchSynthesizer
        self.ResearchQualityAuditor = ResearchQualityAuditor
        self.VectorStore = VectorStore
        self._imports_ready = True

    @property
    def paths(self):
        self._require_imports()
        return self.ResearchPaths(self.data_dir)

    def _require_imports(self) -> None:
        if not self._imports_ready:
            raise RuntimeError("research modules are not loaded")

    def selfcheck(self) -> dict:
        return self.ResearchSelfCheck(self.paths).run()

    def index_status(self) -> dict:
        status = self.ResearchIndexer(self.paths).status()
        return status.__dict__ if hasattr(status, "__dict__") else status

    def index_health(self) -> dict:
        return self.ResearchIndexer(self.paths).health(details=True)

    def vector_status(self) -> dict:
        return self.VectorStore(self.paths).status()

    def index_build(self, *, progress=None) -> dict:
        """Incrementally (re)build the research index for changed/new papers.

        ``progress`` is forwarded to the underlying indexer and invoked once per
        catalog article with ``{current, total, indexed_articles, documents, ...}``.
        """
        result = self.ResearchIndexer(self.paths).build(progress=progress)
        return result.__dict__ if hasattr(result, "__dict__") else result

    def vector_build(
        self,
        *,
        provider: str = "local",
        model: str | None = None,
        kinds: list[str] | None = None,
        include_table_rows: bool = False,
    ) -> dict:
        return self.VectorStore(self.paths).build(
            provider_name=provider,
            model=model,
            kinds=kinds,
            include_table_rows=include_table_rows,
        )

    def search(self, query: str, **options) -> dict:
        return self.ResearchSearch(self.paths).search(
            query,
            limit=int(options.get("limit") or options.get("top_k") or 10),
            evidence_per_article_limit=int(options.get("evidence_per_article_limit") or 3),
            year_from=options.get("year_from"),
            year_to=options.get("year_to"),
            site=options.get("site"),
            journal=options.get("journal"),
            collection=options.get("collection"),
            scope=options.get("scope") or self.default_scope,
            profile=options.get("profile") or "default",
            section=options.get("section"),
            kind=options.get("kind"),
            retrieval=options.get("retrieval") or self.default_retrieval,
            expand_assets=bool(options.get("expand_assets", False)),
        )

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options) -> dict:
        """Block 2: wrap raw search into an auditable EvidenceAcquisitionPacket.

        Does not reimplement retrieval — it calls :meth:`search` and adds intent
        detection, deterministic rewrite, bounded no-hit recovery, normalized
        evidence candidates, deterministic selection, and a coverage judgment.
        """
        from modules.literature_search.retrieval import build_packet

        packet = build_packet(self.search, query, has_history=has_history, options=options)
        return packet.as_dict()

    # --- index-native evidence grounding helpers (Block 2/3 §index) -------------
    # The research-index `documents` table holds ONE row per chunk/abstract/table/
    # figure, each with a stable `id` == the search evidence_id `E{id}`. So a real,
    # citable id already exists for every readable sentence — these helpers align
    # full-text content to that id instead of letting the model fabricate one.

    def _open_index_ro(self):
        import sqlite3

        conn = sqlite3.connect(f"file:{self.paths.index_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _documents_query(self, where: str, params: tuple, *, limit: int) -> list[dict[str, Any]]:
        sql = (
            "select d.id, d.paper_id, p.doi, d.kind, d.section, d.heading_norm, "
            "d.section_id, d.chunk_index, d.source_path, d.text, p.title, p.year, p.journal "
            f"from documents d left join papers p on p.paper_id = d.paper_id where {where} limit ?"
        )
        try:
            with self._open_index_ro() as conn:
                rows = conn.execute(sql, (*params, int(limit))).fetchall()
        except Exception:  # noqa: BLE001 - never break a tool/grounding over the index
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "evidence_id": f"E{r['id']}",
                    "paper_id": r["paper_id"],
                    "doi": r["doi"],
                    "title": r["title"],
                    "year": r["year"],
                    "journal": r["journal"],
                    "kind": r["kind"],
                    "section": r["section"] or r["heading_norm"],
                    "section_id": r["section_id"],
                    "chunk_index": r["chunk_index"],
                    "source_path": r["source_path"],
                    "snippet": (r["text"] or "")[:900],
                    "text": r["text"],
                    "confidence": "medium",
                }
            )
        return out

    def paper_text_documents(
        self, *, doi: str | None = None, paper_id: str | None = None, article_id: int | None = None,
        section: str | None = None, limit: int = 60,
    ) -> list[dict[str, Any]]:
        """Full-text chunks for a paper read straight from the `documents` table, so
        each carries its real citable `E{documents.id}` (L1). The `paper_chunks`
        table uses a different id space; this is the citable one."""
        conds: list[str] = ["d.kind = 'section_chunk'"]
        params: list[Any] = []
        if paper_id:
            conds.append("d.paper_id = ?"); params.append(paper_id)
        elif doi:
            conds.append("p.doi = ?"); params.append(doi)
        elif article_id is not None:
            conds.append("d.article_id = ?"); params.append(int(article_id))
        else:
            return []
        if section:
            conds.append("lower(d.section) like ?"); params.append(f"%{section.strip().lower()}%")
        rows = self._documents_query(" and ".join(conds), tuple(params), limit=limit)
        rows.sort(key=lambda r: (r.get("section_id") or "", r.get("chunk_index") or 0))
        return rows

    def find_supporting_evidence(self, paper_ids: list[str], terms: list[str], *, limit: int = 10) -> list[dict[str, Any]]:
        """FTS the index `documents` (scoped to the given papers) for distinctive
        answer terms, returning evidence rows with the real `E{documents.id}` (L2
        re-alignment substrate) — finds the chunk that actually contains a claim's
        number/term so grounding can verify it instead of deleting it."""
        papers = [p for p in (paper_ids or []) if p]
        clean = _fts_terms(terms)
        if not papers or not clean:
            return []
        match = " OR ".join(f'"{t}"' for t in clean[:16])
        placeholders = ",".join("?" for _ in papers)
        sql = (
            "select d.id, d.paper_id, p.doi, d.kind, d.section, d.heading_norm, "
            "d.section_id, d.chunk_index, d.source_path, d.text, p.title, p.year, p.journal "
            "from documents d join documents_fts on documents_fts.rowid = d.id "
            "left join papers p on p.paper_id = d.paper_id "
            f"where documents_fts match ? and d.paper_id in ({placeholders}) limit ?"
        )
        try:
            with self._open_index_ro() as conn:
                rows = conn.execute(sql, (match, *papers, int(limit))).fetchall()
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "evidence_id": f"E{r['id']}",
                "paper_id": r["paper_id"],
                "doi": r["doi"],
                "title": r["title"],
                "year": r["year"],
                "journal": r["journal"],
                "kind": r["kind"],
                "section": r["section"] or r["heading_norm"],
                "section_id": r["section_id"],
                "chunk_index": r["chunk_index"],
                "source_path": r["source_path"],
                "snippet": (r["text"] or "")[:900],
                "confidence": "medium",
            }
            for r in rows
        ]

    def paper_show(self, **kwargs) -> dict:
        return self.PaperStore(self.paths).show(**_lookup_kwargs(kwargs))

    def paper_sections(self, **kwargs) -> dict:
        return self.PaperStore(self.paths).sections(**_lookup_kwargs(kwargs))

    def paper_chunks(self, **kwargs) -> dict:
        lookup = _lookup_kwargs(kwargs)
        lookup["section"] = kwargs.get("section")
        return self.PaperStore(self.paths).chunks(**lookup)

    def evidence_expand(self, **kwargs) -> dict:
        return self.EvidenceBridge(self.paths).expand(**_clean_none(kwargs))

    def pack(self, query: str, **kwargs) -> dict:
        return self.EvidencePacker(self.paths).pack(query, **_clean_none(kwargs))

    def task_plan(self, question: str, *, budget: int = 20000, scope: str = "library") -> dict:
        return self.ResearchTaskPlanner(self.paths).plan(question, budget=budget, scope=scope)

    def task_run(self, question: str, *, budget: int = 20000, scope: str = "library") -> dict:
        return self.ResearchTaskRunner(self.paths).run(question, budget=budget, scope=scope)

    def run(self, question: str, **kwargs) -> dict:
        return self.ResearchRunManager(self.paths).run(question, **_clean_none(kwargs))

    def run_show(self, run_id: str) -> dict:
        return self.ResearchRunManager(self.paths).show(run_id)

    def run_list(self, *, limit: int = 20) -> dict:
        return self.ResearchRunManager(self.paths).list_runs(limit=limit)

    def run_resume(self, run_id: str) -> dict:
        return self.ResearchRunManager(self.paths).resume(run_id)

    def extract(self, query: str, **kwargs) -> dict:
        return self.MetricExtractor(self.paths).extract(query, **_clean_none(kwargs))

    def compare(self, query: str, **kwargs) -> dict:
        return self.MetricExtractor(self.paths).compare(query, **_clean_none(kwargs))

    def analysis_bundle(self, **kwargs) -> dict:
        return self.AnalysisBundleBuilder(self.paths).bundle(**_clean_none(kwargs))

    def analysis_show(self, bundle_id: str) -> dict:
        return self.AnalysisBundleBuilder(self.paths).show(bundle_id)

    def verify_answer(
        self,
        *,
        answer_text: str | None = None,
        answer_path: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        pack_path: str | None = None,
    ) -> dict:
        cleanup: Path | None = None
        if answer_text and not answer_path:
            fd, path = tempfile.mkstemp(prefix="literature-answer-", suffix=".md")
            cleanup = Path(path)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(answer_text)
            answer_path = str(cleanup)
        if not answer_path:
            raise ValueError("answer_text or answer_path is required")
        try:
            return self.AnswerVerifier(self.paths).verify_answer(
                answer_path,
                run_id=run_id,
                task_id=task_id,
                pack_path=pack_path,
            )
        finally:
            if cleanup:
                cleanup.unlink(missing_ok=True)

    def notes_build(self, run_id: str) -> dict:
        return self.ResearchNotesBuilder(self.paths).build(run_id)

    def notes_show(self, run_id: str) -> dict:
        return self.ResearchNotesBuilder(self.paths).show(run_id)

    def synthesize(self, **kwargs) -> dict:
        return self.ResearchSynthesizer(self.paths).synthesize(**_clean_none(kwargs))

    def quality(self, **kwargs) -> dict:
        return self.ResearchQualityAuditor(self.paths).audit(**_clean_none(kwargs))

    def to_chat_papers(self, payload: dict) -> list[dict[str, Any]]:
        results = payload.get("results") or []
        max_score = max([float(item.get("score") or 0) for item in results] or [1.0]) or 1.0
        papers: list[dict[str, Any]] = []
        for item in results:
            evidence = item.get("evidence") or []
            first_evidence = evidence[0] if evidence else {}
            doi = item.get("doi") or ""
            # Canonical identity (Block 0): the underlying index already stamps
            # paper_id onto every evidence row; surface it at the paper level so
            # Search/Evidence/Artifact/Report/Memory all reference the same id.
            paper_id = item.get("paper_id") or first_evidence.get("paper_id") or ""
            retrieval_sources = item.get("ranking_features", {}).get("retrieval_sources") or []
            confidence = (item.get("evidence_summary") or {}).get("confidence")
            matched_terms = item.get("matched_terms") or []
            tags = []
            for value in [item.get("site"), *retrieval_sources, confidence, *matched_terms[:4]]:
                if value and value not in tags:
                    tags.append(str(value))
            papers.append(
                {
                    "id": doi or str(item.get("article_id") or item.get("title") or ""),
                    "paper_id": paper_id or None,
                    "index_version": item.get("index_version") or first_evidence.get("index_version"),
                    "title": item.get("title") or "Untitled",
                    "authors": item.get("authors") or [],
                    "year": _to_int(item.get("year")),
                    "venue": item.get("journal"),
                    "citation_count": None,
                    "relevance_score": round(float(item.get("score") or 0) / max_score, 4),
                    "abstract": item.get("abstract"),
                    "snippet": first_evidence.get("snippet") or item.get("snippet"),
                    "source_path": first_evidence.get("source_path") or item.get("source_path"),
                    "url": f"https://doi.org/{doi}" if doi else None,
                    "tags": tags,
                    "doi": doi or None,
                    "article_id": _to_int(item.get("article_id")),
                    "evidence": evidence,
                    "evidence_summary": item.get("evidence_summary"),
                    "matched_terms": matched_terms,
                    "retrieval_sources": retrieval_sources,
                }
            )
        return papers

    def answer_from_search(self, question: str, papers: list[dict], search_payload: dict | None = None) -> str:
        if not papers:
            return f"本地文献库没有为「{question}」返回可展示的候选文献。建议放宽检索词或检查索引状态。"
        query_plan = (search_payload or {}).get("query_plan") or {}
        retrieval = query_plan.get("retrieval_used") or (search_payload or {}).get("retrieval") or "unknown"
        fallback = query_plan.get("vector_unavailable_reason") or ""
        lines = [
            f"已在本地文献库中检索「{question}」，当前检索路径为 {retrieval}。",
        ]
        if fallback:
            lines.append(f"语义/向量检索未完全可用，已记录降级原因：{fallback}。")
        lines.append("")
        lines.append("Top 文献与证据片段：")
        for index, paper in enumerate(papers[:5], 1):
            evidence = paper.get("evidence") or []
            best = evidence[0] if evidence else {}
            cite = best.get("evidence_id") or f"P{index}"
            year = f" ({paper['year']})" if paper.get("year") else ""
            venue = f", {paper['venue']}" if paper.get("venue") else ""
            snippet = best.get("snippet") or paper.get("snippet") or "暂无证据片段"
            lines.append(f"{index}. [{cite}] {paper['title']}{year}{venue}: {snippet}")
        lines.append("")
        lines.append("以上是基于检索证据片段的快速摘要；如需可审计的多阶段研究流程，请在 Run 或 Task 标签页生成 artifact。")
        return "\n".join(lines)


def _lookup_kwargs(kwargs: dict) -> dict:
    return {
        "doi": kwargs.get("doi"),
        "paper_id": kwargs.get("paper_id"),
        "article_id": kwargs.get("article_id"),
    }


def _clean_none(kwargs: dict) -> dict:
    return {
        key: value
        for key, value in kwargs.items()
        if value is not None and key not in {"session_id", "turn_id"}
    }


def _fts_terms(terms: list[str]) -> list[str]:
    """Sanitize answer-derived tokens into FTS-safe terms (drop punctuation/short)."""
    import re

    out: list[str] = []
    seen: set[str] = set()
    for raw in terms or []:
        for tok in re.findall(r"[A-Za-z0-9]+", str(raw)):
            low = tok.lower()
            if len(tok) >= 3 and low not in seen:
                seen.add(low)
                out.append(tok)
    return out


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded_research_search_class(base_cls, search_module):
    class BoundedResearchSearch(base_cls):
        def _route_rows(
            self,
            *,
            query: str,
            constraints: str,
            params: list,
            candidate_limit: int,
            section_filter: str | None,
            kind_filter: str | None,
        ) -> tuple[list[dict], dict]:
            return _bounded_route_rows(
                self,
                search_module,
                query=query,
                constraints=constraints,
                params=params,
                candidate_limit=candidate_limit,
                section_filter=section_filter,
                kind_filter=kind_filter,
            )

    BoundedResearchSearch.__name__ = f"Bounded{getattr(base_cls, '__name__', 'ResearchSearch')}"
    return BoundedResearchSearch


def _bounded_route_rows(
    search_instance,
    search_module,
    *,
    query: str,
    constraints: str,
    params: list,
    candidate_limit: int,
    section_filter: str | None,
    kind_filter: str | None,
) -> tuple[list[dict], dict]:
    """Run external FTS recall routes while avoiding the slow broad fallback.

    The upstream search route order is phrase -> core_terms -> fallback_or. On
    the large local FTS index, fallback_or can be very slow because it joins and
    BM25-ranks huge OR matches. If the earlier high-precision routes have already
    filled the candidate pool, the fallback cannot improve the bounded top-K
    recall enough to justify the latency risk. If the pool is still short, we
    keep fallback_or for no-hit and sparse-hit recovery.
    """
    section_clause = "and d.heading_norm = ?" if section_filter else ""
    kind_clause = "and d.kind = ?" if kind_filter else ""
    sql = f"""
        select
            d.id as document_id,
            d.kind,
            d.source_path,
            d.label,
            d.section,
            d.paper_id,
            d.section_id,
            d.chunk_index,
            d.heading_norm,
            d.token_estimate,
            d.text,
            ai.article_id,
            ai.doi,
            ai.title,
            ai.journal,
            ai.year,
            ai.site,
            bm25(documents_fts) as score
        from documents_fts
        join documents d on d.id = documents_fts.rowid
        join article_index ai on ai.article_id = d.article_id
        where documents_fts match ?
        {constraints}
        {section_clause}
        {kind_clause}
        order by score asc
        limit ?
    """
    merged: dict[int, sqlite3.Row | dict] = {}
    route_summaries: list[dict[str, Any]] = []
    with search_instance._connect() as conn:
        for route in search_module._recall_routes(query):
            if route.get("name") == "fallback_or" and len(merged) >= candidate_limit:
                route_summaries.append(
                    {
                        "name": route["name"],
                        "matched_documents": 0,
                        "match": route["match"],
                        "skipped": True,
                        "skip_reason": "candidate_limit_satisfied_before_fallback",
                    }
                )
                continue
            sql_params = [route["match"], *params]
            if section_filter:
                sql_params.append(section_filter)
            if kind_filter:
                sql_params.append(kind_filter)
            sql_params.append(candidate_limit)
            rows = conn.execute(sql, sql_params).fetchall()
            route_summaries.append(
                {
                    "name": route["name"],
                    "matched_documents": len(rows),
                    "match": route["match"],
                }
            )
            for row in rows:
                document_id = int(row["document_id"])
                current = merged.get(document_id)
                adjusted = search_module._row_with_score(row, float(row["score"]) + route["score_offset"])
                if current is None or adjusted["score"] < current["score"]:
                    merged[document_id] = adjusted
    rows = sorted(merged.values(), key=lambda row: row["score"])[:candidate_limit]
    for index, row in enumerate(rows, 1):
        row["fts_rank"] = index
        row["fts_score"] = float(row["score"])
        row["retrieval_sources"] = ["fts"]
    return rows, {
        "rewrite_applied": False,
        "routes": route_summaries,
        "merged_candidate_documents": len(merged),
        "returned_articles": 0,
    }
