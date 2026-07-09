from __future__ import annotations

from modules.literature_search.lightweight_routes import classify_lightweight_route


def test_library_status_routes_are_deterministic() -> None:
    assert classify_lightweight_route("当前文献库中一共有多少文献？").kind == "library_count"
    assert classify_lightweight_route("现在有多少篇文献已经完成索引？").kind == "library_indexed_count"
    assert classify_lightweight_route("当前文献库覆盖哪些年份？").kind == "library_year_coverage"
    assert classify_lightweight_route("当前文献库主要包含哪些期刊？").kind == "library_journal_distribution"
    assert classify_lightweight_route("最近导入了哪些文献？").kind == "library_recent_imports"


def test_help_and_attachment_routes_are_deterministic() -> None:
    assert classify_lightweight_route("What can you do?").kind == "plain_help"
    assert classify_lightweight_route("你是谁？").kind == "plain_help"
    assert classify_lightweight_route("请总结我上传的附件，不需要检索外部文献。", has_attachments=True).kind == "attachment_only"
    assert classify_lightweight_route("请总结我上传的附件，不需要检索外部文献。", has_attachments=False).kind == "attachment_missing"


def test_attachment_plus_literature_stays_research() -> None:
    route = classify_lightweight_route("请先总结附件内容，再结合文献库补充相关研究。", has_attachments=True)
    assert route.kind == "research"
