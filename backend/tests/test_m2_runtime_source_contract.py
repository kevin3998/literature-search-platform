from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_agent_tools_do_not_import_legacy_memory_db() -> None:
    source = (ROOT / "modules/literature_search/agent/tools.py").read_text()

    assert "core.memory_db" not in source


def test_model_profile_reveal_endpoint_does_not_return_plaintext_key() -> None:
    source = (ROOT / "api/settings_router.py").read_text()
    start = source.index('def reveal_model_profile')
    end = source.index('@router.post("/model-profiles/{profile_id}/test")')
    reveal_source = source[start:end]

    assert '"api_key"' not in reveal_source
    assert ".reveal(" not in reveal_source


def test_workflow_runtime_does_not_import_legacy_memory_db() -> None:
    paths = [
        ROOT / "modules/workflow/store.py",
        ROOT / "modules/workflow/orchestrator.py",
        ROOT / "modules/workflow/query_lang.py",
        ROOT / "modules/workflow/runners/corpus_stage.py",
        ROOT / "modules/workflow/runners/agent_step.py",
        ROOT / "modules/workflow/runners/research_controller.py",
    ]

    offenders = [str(path.relative_to(ROOT)) for path in paths if "core.memory_db" in path.read_text()]

    assert offenders == []


def test_structured_extraction_runtime_does_not_import_legacy_memory_db() -> None:
    paths = sorted((ROOT / "modules/structured_extraction").glob("*.py"))

    offenders = [str(path.relative_to(ROOT)) for path in paths if "core.memory_db" in path.read_text()]

    assert offenders == []


def test_readme_describes_postgres_runtime_not_legacy_sqlite() -> None:
    source = (ROOT.parent / "README.md").read_text(encoding="utf-8")

    forbidden = [
        "Settings 的普通配置保存在同一个 SQLite memory DB 中",
        "会话、消息、turn、检索结果、evidence、job events、artifact 链接会持久化到 SQLite",
        "完整明文仅在",
        "会话 SQLite",
        "SQLite settings",
    ]

    offenders = [text for text in forbidden if text in source]
    assert offenders == []
