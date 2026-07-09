from __future__ import annotations


def failure_message(code: str, *, query: str | None = None) -> str:
    topic = f"「{query}」" if query else "该主题"
    messages = {
        "library_not_empty_but_no_query_hit": (
            f"当前本地文献库不是空的，但本轮检索没有命中 {topic} 的候选文献。"
            "这只说明本地库在当前检索词下没有匹配结果，不代表现实中不存在相关研究。"
        ),
        "no_candidate_papers": (
            f"本轮没有找到 {topic} 的候选论文。建议换用英文关键词、缩小或放宽主题表述后重试。"
        ),
        "no_usable_evidence": (
            "本轮没有获得可用于支撑回答的本地文献证据。这表示当前查询没有命中可用证据，"
            "不表示文献库为空，也不表示现实中不存在相关研究。"
        ),
        "empty_or_unavailable_corpus": "当前本地文献库不可用或没有可统计的文献记录，请先检查索引状态。",
        "attachment_missing": "当前会话没有可用附件。请先上传 txt 或 pdf 附件，或重新选择需要总结的附件。",
        "attachment_parse_failed": "附件解析失败，当前没有可用的附件文本可以参与回答。",
        "tool_timeout_recovered": "部分检索工具曾超时，但系统已使用其他路径恢复；回答可能覆盖不完整。",
        "tool_timeout_failed": "检索工具超时且未能恢复，本轮无法给出可靠的文献证据回答。",
        "llm_required_for_research": "文献检索问答需要可用 LLM 才能生成证据接地回答。请先在设置中配置并启用可用模型。",
        "llm_runtime_unavailable": "模型调用失败，当前无法生成文献检索回答。请检查模型配置或切换到可用模型后重试。",
        "plain_chat_no_retrieval_needed": "这是普通对话问题，不需要检索本地文献库。",
    }
    return messages.get(code, messages["no_usable_evidence"])
