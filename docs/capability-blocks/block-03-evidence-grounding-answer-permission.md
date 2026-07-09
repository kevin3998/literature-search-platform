# Block 3: Evidence Grounding / Claim-level Citation / Answer Permission

## Goal

确保 Agent 的每个关键判断都有证据支持，并根据证据强弱决定允许回答到什么程度。

更精确地说，Block 3 是生成侧的越界控制层：在 Block 2 已经完成证据获取、coverage 判断和 evidence boundary 之后，Block 3 检查最终答案是否超过这些证据实际允许表达的范围。

Block 3 不重新判断“是否检索充分”，而是判断“答案是否答过头”。

## Scope

包含：

- evidence id。
- `[E#]` 引用。
- citation audit。
- claim extraction。
- claim-evidence matrix。
- support / partial support / no support。
- conflicting evidence。
- answer permission policy。
- unsupported claim 降级或删除。
- citation fit：引用是否真的支持对应 claim。
- claim scope control：防止局部证据被写成总体结论。
- evidence strength language control：根据证据强弱约束措辞。
- corpus boundary labeling：区分“本地库未检索到支持”和“现实中不存在”。
- final grounding summary。

不包含：

- 检索算法本身。
- turn-level coverage / evidence sufficiency 判断；这属于 Block 2。
- artifact 管理。
- 报告排版。

## Current State

当前 AgentLoop 已有 citation audit：会检查答案中的 `[E#]` 是否对应本轮可用 evidence，并标记 missing ids 或有证据但未引用的情况。前端 MessageBubble 已支持 citation footer。

## Target Capability

从 citation-level 升级到 strict claim-level grounding gate。

当前 citation audit 只能确认 `[E#]` 是否存在。Block 3 的目标是确认：

- 这个 `[E#]` 是否真的支持它前面的 claim。
- claim 的范围是否超过 evidence。
- claim 的措辞是否匹配 evidence 强度。
- unsupported claim 是否被删除、降级或转为 evidence gap。
- 用户是否能区分本地 corpus 边界与现实事实边界。

### Claim Grounding Unit

每个关键 claim 应被归入结构化 grounding unit：

```text
claim
claim_type
support_status: supported | partially_supported | unsupported | conflicting | inference
evidence_ids
source_paths
confidence
permission
scope_notes
rewrite_action
```

其中：

- `supported`：证据直接支持该 claim。
- `partially_supported`：证据支持一部分，但 claim 有外推或缺口。
- `unsupported`：当前 evidence boundary 内没有证据支持。
- `conflicting`：不同证据对该 claim 给出相互冲突的信息。
- `inference`：claim 是基于证据的推断、假设或综合判断，而不是证据直接陈述。

### Strict Answer Permission Policy

Block 3 默认采用严格模式：

- unsupported claim 默认不得进入最终答案。
- unsupported claim 必须被删除、降级，或转为 evidence gap。
- partially supported claim 可以保留，但必须使用限制性措辞。
- inference 可以保留，但必须明确标注为推断 / hypothesis。
- conflicting evidence 必须并列呈现，不允许单边总结。
- citation 不仅要合法，还必须与 claim 匹配。

回答权限策略：

- 强证据：可以给明确结论，必须 citation。
- 部分证据：只能给 tentative answer，并说明限制。
- 无证据：不硬答，只说明本地库未检索到支持证据。
- 证据冲突：列出不同证据，避免单边结论。
- 用户要求推测：明确标注 hypothesis / inference。
- 超出 corpus：说明超出本地文献库范围。

### Final Answer Permission

每个 assistant answer 最终输出一个整体权限状态：

```text
answer_permission: grounded | partially_grounded | hypothesis | conflicting | not_answerable
```

含义：

| Permission | Meaning | Required User-facing Behavior |
|---|---|---|
| `grounded` | 主要结论都有直接证据支持 | 可以明确回答，每个关键结论带 citation |
| `partially_grounded` | 可以回答一部分，但存在限制 | 回答 supported parts，并显式说明缺口 |
| `hypothesis` | 主要内容是基于证据的推断 | 必须标注为推断 / hypothesis，不当作事实 |
| `conflicting` | 证据之间冲突 | 并列呈现冲突证据，避免单边结论 |
| `not_answerable` | 当前证据不允许事实性回答 | 不生成事实结论，只说明本地库未检索到支持 |

### Scope Control Examples

Block 3 应重点压制以下生成侧越界：

| Overclaim | Required Downgrade |
|---|---|
| 单篇论文结果写成“该领域普遍认为” | “本轮检索到的证据中，某研究/部分研究支持……” |
| 小样本实验写成“已经证明” | “该实验报告了……但证据范围有限” |
| 某一任务表现好写成“整体优于” | “在该任务/数据集/设置下表现更好” |
| 本地库结果写成“当前所有研究” | “在本地库本轮检索范围内……” |
| abstract 证据写成实验细节结论 | 限定为背景/摘要层面的支持，或要求进一步 evidence |

### User-visible Product Behavior

用户默认看到自然答案，但答案应自动具备这些纪律：

- 每个关键结论带引用。
- 结论不超过证据范围。
- 证据不足时主动收缩措辞。
- 有冲突时并列说明。
- 有推测时显式标注。
- 无证据时拒绝硬答。
- 永远区分“本地库未检索到支持”与“现实中不存在”。

答案底部应有轻量 grounding summary：

```text
Grounding: partially grounded
Claims: 6 checked · 4 supported · 2 limited
Evidence used: 5
Warnings: 1 scope limitation
```

完整 claim audit 进入 audit record、research record 和 report export，不应默认打断阅读流。

## Design Questions

- claim extraction 是 answer 后处理，还是要求 LLM 同时输出 structured claims？
- citation audit warning 是否阻止最终答案，还是只标记？默认严格模式下，missing citation / unsupported claim 应阻止原样输出，改为降级或重写后的答案。
- unsupported claim 是否自动删除、重写，还是提示用户？已定：默认自动删除、降级或转为 evidence gap，不允许原样进入最终答案。
- 证据冲突如何在 UI 展示？
- “本地库未检索到”与“现实中不存在”如何区分？已定：默认只能说前者，除非 evidence 明确支持后者。

## Interfaces And Data Concerns

可能需要新增 per-turn grounding metadata：

```text
citation_status
cited_ids
missing_ids
available_count
claims
answer_permission
warnings
unsupported_or_limited_claims
conflicting_claims
corpus_boundary_notes
rewrite_actions
```

可存入 assistant message metadata，也可独立建 grounding/audit 表。

建议最终 metadata 形态：

```text
grounding:
  answer_permission
  citation_status
  cited_ids
  missing_ids
  available_count
  claims:
    - claim_text
      claim_type
      support_status
      evidence_ids
      confidence
      permission
      scope_notes
      rewrite_action
  unsupported_or_limited_claims
  conflicting_claims
  warnings
  corpus_boundary_notes
```

## Test And Acceptance

最小验收：

- 答案引用不存在 evidence id 时被标记 warning。
- 有 evidence 但完全无引用时被标记 warning。
- no-evidence 问题不会硬答。
- conflicting evidence 场景能展示两侧证据。
- report 中能输出 citation audit summary。

成品验收：

- supported claim 可以保留，并带匹配 citation。
- partially supported claim 必须使用限制性措辞。
- unsupported claim 默认不得进入最终答案，必须删除、降级或转为 evidence gap。
- inference claim 必须显式标注为推断 / hypothesis。
- citation id 合法但不支持对应 claim 时，必须触发 grounding warning 或改写。
- 单篇/局部证据不得被写成领域级、普遍性、确定性结论。
- evidence conflict 不得被单边总结为确定结论。
- answer_permission 能准确反映最终答案状态。
- UI 能展示轻量 grounding summary。
- audit record / report 能输出 claim-level grounding summary。
- 系统永远区分“本地库未检索到支持”与“现实中不存在”。

## Open Discussion

- 是否需要 claim-level audit 作为 Deep Research 的质量门禁？
- 是否允许用户关闭 enforce citations？建议允许高级用户关闭或降为 warn，但默认 strict。
- 是否把 answer permission policy 写入 system prompt，还是作为后处理规则？
