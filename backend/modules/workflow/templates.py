"""Workflow templates for the Research Workflows product surface.

The default gallery now exposes the controlled ``research_agent_controller``
plans only. Older ARIS/free-agent templates remain addressable by id for
historical run compatibility, but they are not returned by ``list_templates()``
and therefore are not part of the new-run entrypoint.

These templates are workflow selections, not ordinary chat defaults.
"""
from __future__ import annotations

from typing import Any

CATEGORIES: list[dict[str, str]] = [
    {"id": "controlled-research", "name": "受控研究"},
]


def _step(key: str, label: str, runner: str, available: bool, note: str = "", params: dict | None = None) -> dict[str, Any]:
    return {
        "step_key": key,
        "label": label,
        "runner": runner,
        "available": available,
        "note": note,
        "params": params or {},
    }


# Convenience builders for the two step kinds used in P1.
def _lit(label: str = "文献调研", note: str = "在本地语料检索并整理证据") -> dict[str, Any]:
    # Base ResearchRunManager run (selfcheck → plan → task → pack) = retrieval +
    # evidence packing — the one ARIS step we can execute today.
    return _step("research-lit", label, "corpus-stage", True, note, params={})


def _agent(key: str, label: str, note: str = "") -> dict[str, Any]:
    return _step(key, label, "agent-step", False, note)


_CONTROLLED_PLAN_STAGES: dict[str, list[tuple[str, str]]] = {
    "minimal": [
        ("retrieve_sources", "检索来源"),
        ("create_evidence_seeds", "创建证据种子"),
        ("extract_evidence_cards", "抽取证据卡片"),
        ("enrich_evidence_cards", "富集证据卡片"),
        ("rank_evidence", "排序代表性证据"),
        ("build_minimal_topic_to_evidence_report", "生成最小证据报告"),
    ],
    "landscape": [
        ("retrieve_sources", "检索来源"),
        ("create_evidence_seeds", "创建证据种子"),
        ("extract_evidence_cards", "抽取证据卡片"),
        ("enrich_evidence_cards", "富集证据卡片"),
        ("rank_evidence", "排序代表性证据"),
        ("build_minimal_topic_to_evidence_report", "生成最小证据报告"),
        ("build_landscape", "构建文献图景"),
    ],
    "gap_mapping": [
        ("retrieve_sources", "检索来源"),
        ("create_evidence_seeds", "创建证据种子"),
        ("extract_evidence_cards", "抽取证据卡片"),
        ("enrich_evidence_cards", "富集证据卡片"),
        ("rank_evidence", "排序代表性证据"),
        ("build_minimal_topic_to_evidence_report", "生成最小证据报告"),
        ("build_landscape", "构建文献图景"),
        ("map_gaps", "映射研究空白"),
    ],
    "idea_generation": [
        ("retrieve_sources", "检索来源"),
        ("create_evidence_seeds", "创建证据种子"),
        ("extract_evidence_cards", "抽取证据卡片"),
        ("enrich_evidence_cards", "富集证据卡片"),
        ("rank_evidence", "排序代表性证据"),
        ("build_minimal_topic_to_evidence_report", "生成最小证据报告"),
        ("build_landscape", "构建文献图景"),
        ("map_gaps", "映射研究空白"),
        ("generate_candidate_ideas", "生成候选想法"),
    ],
    "screening": [
        ("retrieve_sources", "检索来源"),
        ("create_evidence_seeds", "创建证据种子"),
        ("extract_evidence_cards", "抽取证据卡片"),
        ("enrich_evidence_cards", "富集证据卡片"),
        ("rank_evidence", "排序代表性证据"),
        ("build_minimal_topic_to_evidence_report", "生成最小证据报告"),
        ("build_landscape", "构建文献图景"),
        ("map_gaps", "映射研究空白"),
        ("generate_candidate_ideas", "生成候选想法"),
        ("screen_novelty_feasibility_risk", "筛选新颖性 / 可行性 / 风险"),
    ],
}


def _controlled(
    template_id: str,
    name: str,
    plan_kind: str,
    desc: str,
    est: str = "~5-20 分钟",
) -> dict[str, Any]:
    return {
        "id": template_id,
        "category": "controlled-research",
        "name": name,
        "est": est,
        "desc": desc,
        "steps": [
            _step(
                plan_kind,
                name,
                "research-controller",
                True,
                "由 research_agent_controller 受控执行；产物写入研究任务工作区。",
                params={
                    "controller_plan_kind": plan_kind,
                    "stages": [
                        {"stage": stage, "label": label}
                        for stage, label in _CONTROLLED_PLAN_STAGES[plan_kind]
                    ],
                },
            )
        ],
    }


TEMPLATES: list[dict[str, Any]] = [
    _controlled(
        "controlled-minimal-evidence",
        "最小证据报告",
        "minimal",
        "从研究主题开始，按顺序完成证据检索、证据卡片、代表性证据选择和最小证据报告。",
    ),
    _controlled(
        "controlled-landscape",
        "文献图景",
        "landscape",
        "先完成最小证据链，再基于证据卡片和代表性证据构建保守的文献图景。",
    ),
    _controlled(
        "controlled-gap-mapping",
        "研究空白映射",
        "gap_mapping",
        "先完成文献图景，再在其基础上构建证据接地的研究空白图。",
    ),
    _controlled(
        "controlled-idea-generation",
        "候选想法生成",
        "idea_generation",
        "先完成研究空白映射，再从研究空白图、文献图景和证据生成受约束的候选想法。",
    ),
    _controlled(
        "controlled-screening",
        "新颖性 / 可行性 / 风险筛选",
        "screening",
        "先生成候选想法，再执行 P2-M11 保守筛选；不生成实验方案，也不进入 P2-M12。",
    ),
]


LEGACY_TEMPLATES: list[dict[str, Any]] = [
    # ---- 科研工作流 -------------------------------------------------------
    {
        "id": "idea-discovery",
        "category": "research",
        "name": "Idea 发现",
        "est": "~30-60 分钟",
        "desc": "给个研究方向，AI 调研文献 → 头脑风暴 → 验新颖性 → 出可执行 idea 报告",
        "steps": [
            _lit("文献调研"),
            # P2: first agent-step lit up — generates candidate ideas grounded in
            # the prior step's local corpus evidence (ported from ARIS idea-creator).
            _step("idea-creator", "Idea 生成", "agent-step", True, "围绕方向头脑风暴候选 idea（基于本地证据）"),
            _step("novelty-check", "新颖性验证", "agent-step", True, "本地语料 + 外部学术源核查候选 idea 的新颖性"),
            _step("idea-report", "Idea 报告", "agent-step", True, "汇总为可执行 idea 报告"),
        ],
    },
    {
        "id": "experiment-bridge",
        "category": "research",
        "name": "实验桥接",
        "est": "~20-40 分钟",
        "desc": "已有 idea 或实验计划：自动写代码 → 跑实验 → 出论文级图表 + LaTeX 表",
        "steps": [
            _agent("experiment-plan", "实验规划", "把 idea 落成实验计划"),
            _agent("code-gen", "代码生成", "自动生成实验代码"),
            _agent("run-experiment", "跑实验", "执行并收集结果"),
            _agent("figures-latex", "图表 / LaTeX", "出论文级图表与 LaTeX 表"),
        ],
    },
    {
        "id": "auto-review-loop",
        "category": "research",
        "name": "自动审稿循环",
        "est": "~30-60 分钟",
        "desc": "已有论文/实验：AI 当审稿人挑毛病 → 自动修改 → 重审，反复 4 轮至可投稿",
        "steps": [
            _agent("review", "审稿挑错", "扮演审稿人挑毛病"),
            _agent("revise", "自动修改", "按意见修改"),
            _agent("re-review", "重审", "重复评审直至达标（×4 轮）"),
        ],
    },
    {
        "id": "full-pipeline",
        "category": "research",
        "name": "全流程",
        "est": "~2-5 小时",
        "desc": "从零做完整研究：Idea → 实验 → 论文 (PDF/Word) → 评审改进（共 11 步）",
        "steps": [
            _lit("文献调研"),
            _agent("idea-creator", "Idea 生成"),
            _agent("experiment-plan", "实验规划"),
            _agent("run-experiment", "跑实验"),
            _agent("paper-write", "论文写作"),
            _agent("review-improve", "评审改进"),
        ],
    },
    # ---- 学术写作 -------------------------------------------------------
    {
        "id": "paper-write",
        "category": "writing",
        "name": "论文写作",
        "est": "~45-90 分钟",
        "desc": "大纲 → 图表 → LaTeX/Markdown → 编译/Word导出",
        "steps": [
            _agent("outline", "大纲", "生成论文大纲"),
            _agent("figures", "图表", "生成图表"),
            _agent("draft", "LaTeX/Markdown 写作"),
            _agent("export-word", "编译 / Word 导出"),
        ],
    },
    {
        "id": "nature-paper",
        "category": "writing",
        "name": "Nature 论文写作",
        "est": "~60-120 分钟",
        "desc": "Nature 风格：规划 → 分析 → 图表 → 写作 → 编译/Word",
        "steps": [
            _agent("plan", "规划"),
            _agent("analysis", "分析"),
            _agent("figures", "图表"),
            _agent("draft", "写作"),
            _agent("export-word", "编译 / Word"),
        ],
    },
    {
        "id": "proposal",
        "category": "writing",
        "name": "开题报告",
        "est": "~30-60 分钟",
        "desc": "文献调研 → 开题撰写 → 技术路线 → Word导出",
        "steps": [
            _lit("文献调研"),
            _agent("proposal-write", "开题撰写"),
            _agent("tech-route", "技术路线"),
            _agent("export-word", "Word 导出"),
        ],
    },
    {
        "id": "lit-review-writing",
        "category": "writing",
        "name": "文献综述",
        "est": "~30-60 分钟",
        "desc": "文献检索 → 真实性验证 → 主题聚类 → 综述撰写 → Word导出",
        "steps": [
            _lit("文献检索"),
            _agent("fact-check", "真实性验证", "核查引用真实性"),
            _agent("cluster", "主题聚类"),
            _agent("review-write", "综述撰写"),
            _agent("export-word", "Word 导出"),
        ],
    },
    {
        "id": "course-paper",
        "category": "writing",
        "name": "课程论文",
        "est": "~25-50 分钟",
        "desc": "大纲规划 → [可选: 数据分析+图表] → 撰写嵌入图 → 审查 → Word导出",
        "steps": [
            _agent("outline", "大纲规划"),
            _agent("data-figures", "数据分析 + 图表（可选）"),
            _agent("draft-embed", "撰写嵌入图"),
            _agent("review", "审查"),
            _agent("export-word", "Word 导出"),
        ],
    },
    {
        "id": "course-report",
        "category": "writing",
        "name": "课程报告",
        "est": "~25-50 分钟",
        "desc": "事实提取+大纲 → [可选: 数据分析+图表] → [可选: 架构图] → 撰写嵌入图 → 审查 → Word导出",
        "steps": [
            _agent("facts-outline", "事实提取 + 大纲"),
            _agent("data-figures", "数据分析 + 图表（可选）"),
            _agent("arch-diagram", "架构图（可选）"),
            _agent("draft-embed", "撰写嵌入图"),
            _agent("review", "审查"),
            _agent("export-word", "Word 导出"),
        ],
    },
    # ---- 竞赛工作流（占位，细节待补） -----------------------------------
    {
        "id": "competition-pipeline",
        "category": "competition",
        "name": "竞赛工作流",
        "est": "敬请期待",
        "desc": "面向竞赛的端到端流水线（细节待补充）",
        "steps": [
            _agent("comp-plan", "赛题分析"),
            _agent("comp-solve", "方案与实现"),
            _agent("comp-report", "报告产出"),
        ],
    },
    # ---- 已有资料写论文 -------------------------------------------------
    {
        "id": "write-from-materials",
        "category": "from-materials",
        "name": "已有资料写论文",
        "est": "~40-90 分钟",
        "desc": "上传资料 → 事实提取 → 大纲 → 撰写 → Word导出",
        "steps": [
            _agent("ingest", "资料解析"),
            _agent("facts", "事实提取"),
            _agent("outline", "大纲"),
            _agent("draft", "撰写"),
            _agent("export-word", "Word 导出"),
        ],
    },
]

_BY_ID = {t["id"]: t for t in [*TEMPLATES, *LEGACY_TEMPLATES]}


def list_categories() -> list[dict[str, str]]:
    return [dict(c) for c in CATEGORIES]


def list_templates() -> list[dict[str, Any]]:
    return [dict(t) for t in TEMPLATES]


def get_template(template_id: str) -> dict[str, Any] | None:
    tpl = _BY_ID.get(template_id)
    return dict(tpl) if tpl else None
