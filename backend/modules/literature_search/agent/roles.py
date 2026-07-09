"""Block 6c: specialist roles as profiles over the SINGLE AgentLoop.

A role is NOT an independent agent and adds NO extra planner LLM pass. It is a
three-part profile applied to the same loop:

1. a tool-exposure subset (intersected with the answer_mode's tools in the
   registry) — this is what structurally stops the retrieval role from doing
   analysis/synthesis work (the compare/extract/run tools simply aren't there);
2. a system-prompt fragment that states the role's responsibility + boundary;
3. an advisory ``stage`` label (never a hard gate).

Routing stays lightweight: an explicit capability button sets the role
deterministically; free-form chat uses ``general`` (the full mode-appropriate
tool set, i.e. the pre-6c behaviour) so the LLM still judges which tool to call.
``mode`` lets a role force deep tools (analysis/synthesis/report need the job
tools) regardless of the user's quick/deep toggle.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    label: str  # UI label
    stage: str  # advisory stage this role corresponds to
    mode: str | None  # "quick" | "deep" | None (None → use the user's toggle)
    tools: frozenset[str] | None  # tool-name subset; None → all tools for the mode
    prompt: str  # role-specific system-prompt fragment


# Reusable inspection tools every role may read with.
_INSPECT = {"paper_sections", "paper_chunks", "evidence_expand"}

GENERAL = Role(
    name="general",
    label="自动",
    stage="retrieval",
    mode=None,
    tools=None,  # no restriction — current single-agent behaviour
    prompt="",
)

RETRIEVAL = Role(
    name="retrieval",
    label="检索",
    stage="retrieval",
    mode="quick",
    tools=frozenset({"search", "pack"} | _INSPECT),
    prompt=(
        "当前角色：检索（Retrieval）。你只负责找材料——检索论文、扩展查询、获取证据、"
        "建立候选论文集与 evidence pack，并标记覆盖缺口。"
        "不要承担深度方法对比、理论分析或综述写作。如果用户需要分析或综述，"
        "请在回答末尾提示其切换到分析/综合角色，而不是自己勉强完成。"
    ),
)

EVIDENCE = Role(
    name="evidence",
    label="证据",
    stage="evidence curation",
    mode="quick",
    tools=frozenset({"search", "pack"} | _INSPECT),
    prompt=(
        "当前角色：证据整理（Evidence Curator）。你负责整理、去重、归并证据，"
        "标记证据与论文/章节/片段的关系与可信度，构建可交接给分析或写作的 evidence pack。"
        "不做深度分析或综述写作。"
    ),
)

ANALYSIS = Role(
    name="analysis",
    label="分析",
    stage="analysis",
    mode="deep",
    tools=frozenset({"search", "pack", "extract", "compare"} | _INSPECT),
    prompt=(
        "当前角色：分析（Analysis）。基于已保留论文与 evidence pack，比较论文、"
        "归纳方法差异、识别争议点。默认复用已检索到的证据，不重新承担底层检索职责；"
        "只有在确实缺少证据时才用 search 补充。优先用 extract/compare 形成结构化结论。"
    ),
)

SYNTHESIS = Role(
    name="synthesis",
    label="综合",
    stage="synthesis",
    mode="deep",
    tools=frozenset({"search", "pack", "run", "task_run"} | _INSPECT),
    prompt=(
        "当前角色：综合（Synthesis）。基于分析结论与已接受的证据，组织综述结构、"
        "生成论证链、形成草稿。读取已有材料，不重新发明检索与分析过程。"
    ),
)

REPORT = Role(
    name="report",
    label="报告",
    stage="report",
    mode="deep",
    tools=frozenset({"verify_answer", "quality"} | _INSPECT),
    prompt=(
        "当前角色：报告（Report）。负责核对引用、审计链与研究质量，产出可导出的研究记录。"
        "读取已有状态与产物，不重新发明研究过程。"
    ),
)

ROLES: dict[str, Role] = {
    r.name: r for r in (GENERAL, RETRIEVAL, EVIDENCE, ANALYSIS, SYNTHESIS, REPORT)
}


def get_role(name: str | None) -> Role:
    """Resolve a role name to its profile, defaulting to ``general``."""
    return ROLES.get(name or "general", GENERAL)
