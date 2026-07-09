export const ROUTE_LABELS = {
  plain_help: "能力说明",
  plain_chat: "普通问答",
  attachment_only: "基于上传附件回答",
  attachment_missing: "缺少可用附件",
  library_count: "文献库状态查询",
  library_indexed_count: "文献库状态查询",
  library_year_coverage: "文献库状态查询",
  library_journal_distribution: "文献库状态查询",
  library_recent_imports: "文献库状态查询",
  research: "文献检索问答",
};

export const FAILURE_LABELS = {
  library_not_empty_but_no_query_hit: "文献库非空，但本轮主题没有命中。",
  no_candidate_papers: "没有找到候选论文。",
  no_usable_evidence: "找到的信息不足以支撑回答。",
  empty_or_unavailable_corpus: "文献库为空或索引不可用。",
  attachment_missing: "当前会话没有可用附件。",
  attachment_parse_failed: "附件解析失败。",
  tool_timeout_recovered: "工具曾超时但已恢复。",
  tool_timeout_failed: "工具超时导致本轮失败。",
  llm_required_for_research: "文献检索问答需要可用模型。",
  llm_runtime_unavailable: "模型调用失败，无法生成文献检索回答。",
  plain_chat_no_retrieval_needed: "普通问答无需检索。",
};

export function routeLabel(route, fallback = "") {
  return ROUTE_LABELS[route] || fallback || route || "未记录";
}

export function failureLabel(code, fallback = "") {
  return fallback || FAILURE_LABELS[code] || code || "暂无失败说明。";
}

export function routeEmptyReason(route, failureCode, failureMessage) {
  if (failureCode) return failureLabel(failureCode, failureMessage);
  if (route === "attachment_only") return "本轮基于上传附件回答，附件不是正式文献证据。";
  if (route === "attachment_missing") return failureLabel("attachment_missing", failureMessage);
  if (route?.startsWith("library_")) return "本轮读取文献库统计，没有生成正式文献证据，也没有执行主题检索。";
  if (route === "plain_help" || route === "plain_chat") return "本轮是普通问答，无需检索文献库或生成正式文献证据。";
  return "本轮暂未形成可用于复核的正式文献证据。";
}

export function paperEmptyReason(route, failureCode, failureMessage) {
  if (failureCode) return failureLabel(failureCode, failureMessage);
  if (route === "attachment_only") return "本轮基于上传附件回答，未检索文献库。";
  if (route === "attachment_missing") return "当前会话没有可用附件，本轮未检索文献库。";
  if (route?.startsWith("library_")) return "本轮查询文献库状态，未执行主题检索。";
  if (route === "plain_help" || route === "plain_chat") return "本轮是普通问答，未检索文献库。";
  return "本轮没有返回候选文献；这不等于文献库为空。";
}
