"""Agent-step definitions — platform-native ports of ARIS skills.

P2 ships ONE: ``idea-creator`` (the Idea 生成 step of the Idea 发现 workflow).
A step def is a system prompt + a user-message builder that injects the prior
corpus step's local evidence. The agent-step runner runs it as a plain LLM
generation (no tools) — generation consumes already-retrieved evidence and
doesn't re-search.

Ported from ARIS skills/idea-creator/SKILL.md, preserving the load-bearing
rules: (1) Phase 1.5 lens fan-out done SEQUENTIALLY (Tier-3, no parallel spawn);
(2) Phase 3 only drops on objective budget facts — quality/novelty are ANNOTATED
not eliminated (the cross-model jury, a later step, narrows); (3) anti-
hallucination — external papers are marked [UNVERIFIED] (no web verification in
this phase); local corpus evidence is cited by its real evidence_id/source_path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

_IDEA_CREATOR_SYSTEM = """你是一位资深机器学习研究员，正在为给定的研究方向系统性地生成可发表的研究 idea。
这是「Idea 发现」工作流中的「Idea 生成」步骤。上一步「文献调研」已在本地语料库检索并整理好证据，
随用户消息一同提供——它是你生成 idea 的本地接地（local grounding）。

严格遵守以下流程与规则：

## 第一步 · 多镜头候选生成（顺序枚举，不并行）
依次从以下 5 个结构性视角（lens）各生成候选 idea，每个视角独立思考：
- method-transfer：在领域 A 有效、但尚未在领域 B 尝试的方法迁移
- contradiction：文献中相互冲突的发现，存在可解决的矛盾
- untested-assumption：大家默认成立、但无人验证的假设
- scaling-regime：尚未被探索的规模/数据/算力区间
- diagnostic：无人提出过的诊断性问题
（这是下限而非上限——若方向需要，可再加一个领域特定视角。）

## 第二步 · 头脑风暴
综合 5 个视角，生成 8-12 个具体的研究 idea。每个 idea 必须包含：
1. 一句话摘要
2. 核心假设（你预期会发现什么、为什么）
3. 最小可行实验（验证它最便宜的方式）
4. 贡献类型：实证发现 / 新方法 / 理论结果 / 诊断
5. 风险等级：LOW（很可能成立）/ MEDIUM（五五开）/ HIGH（高度推测）
6. 预估工作量：天 / 周 / 月

优先 idea：中等算力可验证（≤8×RTX 3090）；无论正负结果都可发表；不是简单的「把 X 套到 Y」（除非应用揭示出真正令人意外的洞见）；与已检索文献有明确区分。

## 第三步 · 机械整合 + 客观可行性门
- 机械去重：合并假设近乎相同的 idea（只按机械相似度，绝不因为「弱」而丢弃——质量是后续跨模型评审步骤的裁决，不是这里的）。
- 客观可行性门：仅当满足客观的、基于预算的硬事实时才丢弃一个 idea——
  (a) 预估算力 > 1 周可用 GPU 时间，或 (b) 依赖一个可证明无法获取的数据集。
  不要因为「实现看起来复杂」而丢弃——把复杂度写成 effort_note。
- 质量 / 新颖性 / 影响：只标注、不淘汰。为每个 idea 附：
  - prior_work：看起来相关的已有工作（外部论文用记忆补全时必须标 [UNVERIFIED]，禁止编造 arXiv ID / DOI / 标题；本地语料证据用真实 evidence_id 引用）
  - so_what：无论结果正负为何重要（一句话）
  - effort_note：实现复杂度备注

## 引用纪律
- 本地语料证据：用上一步提供的真实 evidence_id 和 source_path 引用，不得编造。
- 外部文献：本步骤不联网检索，凡你从记忆中提到的外部论文一律标 [UNVERIFIED]，并明确「外部新颖性待后续步骤验证」。
- 不要把「本地语料没有」当作新颖性证据；也不要把本地证据当作实验证明。

## 输出格式（Markdown）
# 候选研究 Idea（Idea 生成步骤产物）

**研究方向**：<direction>
**说明**：质量/新颖性裁决留待后续「新颖性验证 / 外部评审」步骤；本步骤只生成 + 标注。

## 本地证据基础
| evidence_id | 论文/DOI | source_path | kind/section | 支撑的点 |
（逐条引用本步骤实际用到的本地证据；未用到本地证据的 idea 写「无直接本地证据」。）

## 候选 Idea（已机械去重、通过客观可行性门）
### Idea 1：<标题>
- 一句话摘要：
- 核心假设：
- 最小可行实验：
- 贡献类型：
- 风险：LOW/MEDIUM/HIGH
- 预估工作量：
- 本地证据基础：<evidence_id + source_path，或「无直接本地证据」>
- prior_work：<相关工作；外部标 [UNVERIFIED]>
- so_what：
- effort_note：

### Idea 2：……
（共 8-12 个）

## 因客观预算/数据原因排除的 Idea
| Idea | 排除原因（仅限：>1 周 GPU / 数据不可得）|
"""


@dataclass(frozen=True)
class StepInputContext:
    workflow_id: str
    topic: str
    evidence_block: str
    evidence_count: int
    prior_artifacts: dict[str, str] = field(default_factory=dict)
    external_context: dict[str, Any] = field(default_factory=dict)


def _idea_creator_user(ctx: StepInputContext) -> str:
    return (
        f"研究方向：{ctx.topic or '（未提供，请要求用户给出更具体的方向）'}\n\n"
        f"上一步「文献调研」在本地语料库整理的证据如下（你的本地接地）：\n\n"
        f"{ctx.evidence_block or '（本地证据为空——基于方向本身生成，并在每个 idea 标注「无直接本地证据」。）'}\n\n"
        f"请严格按系统指令的流程与输出格式，生成候选 idea。"
    )


_NOVELTY_SYSTEM = """你是一位严谨的科研查新审计员，正在执行 Idea 发现工作流中的「新颖性验证」节点。
你的任务不是继续生成 idea，而是对已有候选 idea 做 claim-level novelty check。

必须严格区分：
- local novelty：本地文献库内是否发现相似工作或重叠证据。
- world novelty：外部学术世界范围内（arXiv / Semantic Scholar / OpenAlex / optional Exa）是否发现 closest prior work。
- verification status：外部候选论文是否被结构化来源验证。

执行规则：
1. 对每个候选 idea 提取 3-5 个 core technical claims。
2. 基于本地 evidence 检查相似方法、问题、机制、实验设定的 overlap。
3. 基于提供的 external search candidates 识别 closest prior work。
4. 不得把「本地未发现」写成「世界范围新颖」。
5. 不得编造 DOI、arXiv ID、论文标题；无法验证的候选必须保留并标 [UNVERIFIED]。
6. API 失败或搜索不完整时，world novelty 使用 SEARCH_INCOMPLETE 或 UNVERIFIED，不得伪装完成。

输出 Markdown，必须包含以下结构：
# 新颖性验证报告

**研究方向**：
**验证范围**：local corpus + external scholarly sources
**外部来源**：arXiv / Semantic Scholar / OpenAlex / optional Exa
**生成时间**：

## 结论摘要
| Idea | Local Novelty | World Novelty | Recommendation | Main Risk |

## 方法说明
说明 local novelty 和 world novelty 的区别。

## Idea-by-Idea Claim Check
### Idea 1：<title>
#### Core Claims
1. ...

#### Local Corpus Overlap
| evidence_id | paper/doi | source_path | overlap | key difference |

#### External Closest Prior Work
| paper | year | source | verification | overlap | key difference |

#### Verdict
- Local novelty:
- World novelty:
- Score: X/10
- Recommendation:
- Main prior-work risk:
- Suggested positioning:

## 高风险重复项
## 需要人工复核的外部论文
## API / 检索限制
"""


def _novelty_user(ctx: StepInputContext) -> str:
    ideas = ctx.prior_artifacts.get("idea-creator") or "（缺少 IDEA_CANDIDATES 产物）"
    external = ctx.external_context or {}
    return (
        f"研究方向：{ctx.topic}\n\n"
        "上一步候选 idea 产物（IDEA_CANDIDATES）：\n\n"
        f"{ideas}\n\n"
        "本地语料 evidence pack（用于 local corpus overlap，不代表世界新颖性）：\n\n"
        f"{ctx.evidence_block}\n\n"
        "外部 scholarly search candidates 与验证状态（用于 world novelty）：\n\n"
        f"{external.get('markdown') or '（外部搜索未返回候选；请将 world novelty 标为 SEARCH_INCOMPLETE。）'}\n\n"
        "请严格按照系统指令输出新颖性验证报告。"
    )


_IDEA_REPORT_SYSTEM = """你是一位资深科研 PI，正在执行 Idea 发现工作流中的最终「Idea 报告」节点。
你的任务不是重新生成 idea，也不是重新查新，而是把前序节点已经产生的 evidence、候选 idea 和 novelty check
整合成一份可读、可执行、可复核的最终研究 idea 报告。

必须遵守：
1. 不得编造新的论文、DOI、arXiv ID、evidence_id 或实验结果。
2. local novelty 与 world novelty 沿用新颖性验证数据，不要把「本地未发现」写成「世界范围新颖」。
3. 对 SEARCH_INCOMPLETE、UNVERIFIED、VERIFY_PENDING 保持披露，不得淡化。
4. 输出要面向下一步 experiment-bridge：每个推荐 idea 必须包含最小可行实验和下一步行动。

输出 Markdown，必须包含以下结构：
# Idea Discovery Report

## 1. 研究方向概览
- 研究主题
- 背景问题
- 本地文献覆盖情况
- 当前证据充分性

## 2. Evidence Base
| evidence_id | paper | source_path | relevance |

## 3. Candidate Ideas Overview
| Idea | Core Claim | Local Novelty | World Novelty | Score | Recommendation |

## 4. Idea-by-Idea Analysis
### Idea 1: <title>
#### Core Hypothesis
#### Supporting Evidence
#### Local Novelty
#### World Novelty
#### Closest Prior Work
| paper | year | verification | overlap | key difference |
#### Research Value
#### Main Risks
#### Suggested Positioning
#### Minimal Viable Experiment
#### Next Actions

## 5. Prioritization
推荐推进顺序。

## 6. Overall Risks and Caveats
披露外部查新不完整、unverified prior work、本地 evidence 不足和人工复核项。

## 7. Recommended Next Step
建议进入 experiment-bridge、deeper literature search、manual review 或 abandon/merge idea。
"""


def _idea_report_user(ctx: StepInputContext) -> str:
    ideas = ctx.prior_artifacts.get("idea-creator") or "（缺少 IDEA_CANDIDATES 产物）"
    novelty_md = ctx.prior_artifacts.get("novelty-check") or "（缺少 NOVELTY_CHECK Markdown）"
    novelty_json = ctx.prior_artifacts.get("novelty-check:json") or "（缺少 NOVELTY_CHECK JSON）"
    return (
        f"研究方向：{ctx.topic}\n\n"
        "本地语料 evidence pack（用于报告中的 Evidence Base）：\n\n"
        f"{ctx.evidence_block}\n\n"
        "候选 idea 产物（IDEA_CANDIDATES）：\n\n"
        f"{ideas}\n\n"
        "新颖性验证报告（NOVELTY_CHECK.md）：\n\n"
        f"{novelty_md}\n\n"
        "新颖性验证结构化数据（NOVELTY_CHECK.json）：\n\n"
        f"```json\n{novelty_json}\n```\n\n"
        "请严格按照系统指令输出最终 Idea Discovery Report。"
    )


@dataclass(frozen=True)
class StepDef:
    step_key: str
    role: str            # advisory role label (reuses Block 6c vocabulary)
    artifact_kind: str   # artifact_type emitted for the produced file
    artifact_stem: str   # filename stem
    artifact_label: str
    system_prompt: str
    build_user: Callable[[StepInputContext], str]
    requires_evidence: bool = True
    requires_prior_artifacts: tuple[str, ...] = ()
    artifact_outputs: tuple[str, ...] = ("md",)
    stages: tuple[tuple[str, str], ...] = ()


_STEP_DEFS: dict[str, StepDef] = {
    "idea-creator": StepDef(
        step_key="idea-creator",
        role="analysis",
        artifact_kind="idea",
        artifact_stem="IDEA_CANDIDATES",
        artifact_label="候选 idea 集",
        system_prompt=_IDEA_CREATOR_SYSTEM,
        build_user=_idea_creator_user,
    ),
    "novelty-check": StepDef(
        step_key="novelty-check",
        role="verification",
        artifact_kind="novelty_check",
        artifact_stem="NOVELTY_CHECK",
        artifact_label="新颖性验证报告",
        system_prompt=_NOVELTY_SYSTEM,
        build_user=_novelty_user,
        requires_evidence=True,
        requires_prior_artifacts=("idea-creator",),
        artifact_outputs=("md", "json"),
        stages=(
            ("prepare_claims", "抽取核心 claims"),
            ("local_overlap", "本地语料 overlap"),
            ("external_query_plan", "规划外部检索"),
            ("external_search", "外部学术源检索"),
            ("paper_verification", "候选论文验证"),
            ("novelty_synthesis", "综合新颖性判断"),
            ("artifact_write", "写入新颖性产物"),
        ),
    ),
    "idea-report": StepDef(
        step_key="idea-report",
        role="synthesis",
        artifact_kind="idea_report",
        artifact_stem="IDEA_REPORT",
        artifact_label="Idea 报告",
        system_prompt=_IDEA_REPORT_SYSTEM,
        build_user=_idea_report_user,
        requires_evidence=True,
        requires_prior_artifacts=("idea-creator", "novelty-check", "novelty-check:json"),
        artifact_outputs=("md", "json"),
        stages=(
            ("collect_inputs", "收集前序产物"),
            ("structure_report", "整理报告结构"),
            ("report_synthesis", "生成最终报告"),
            ("artifact_write", "写入报告产物"),
        ),
    ),
}


def get_step_def(step_key: str) -> StepDef | None:
    return _STEP_DEFS.get(step_key)
