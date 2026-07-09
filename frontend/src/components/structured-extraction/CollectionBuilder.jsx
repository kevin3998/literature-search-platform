import React, { useEffect, useMemo, useState } from "react";
import { Bot, Check, HelpCircle, Loader2, Lock, RefreshCcw, RotateCcw, Search, Sparkles, X } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const EXCLUDE_REASONS = [
  ["not_relevant", "不相关"],
  ["review_article", "综述"],
  ["no_full_text", "无全文"],
  ["not_target_material", "非目标材料"],
  ["not_target_method", "非目标方法"],
  ["not_target_application", "非目标应用"],
  ["duplicate", "重复"],
  ["insufficient_data", "数据不足"],
  ["non_experimental", "非实验"],
  ["non_english_or_non_chinese", "非中英"],
  ["other", "其他"],
];

const LIMIT_OPTIONS = [
  ["20", "20"],
  ["50", "50"],
  ["100", "100"],
  ["200", "200"],
  ["all", "全部结果"],
];

function fmtScore(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(2);
}

function limitToPayload(value) {
  return value === "all" ? null : Number(value) || 50;
}

function limitToForm(value) {
  return value === null || value === undefined || value === 0 ? "all" : String(value);
}

export default function CollectionBuilder({ task }) {
  const collection = useAppStore((s) => s.structuredExtraction.collection);
  const loadCandidates = useAppStore((s) => s.loadExtractionCandidates);
  const searchCollection = useAppStore((s) => s.searchExtractionCollection);
  const setDecision = useAppStore((s) => s.setExtractionCandidateDecision);
  const bulkDecision = useAppStore((s) => s.bulkExtractionCandidateDecision);
  const expandQuestion = useAppStore((s) => s.expandExtractionQuestion);
  const screenCandidates = useAppStore((s) => s.screenExtractionCandidates);
  const freezeCollection = useAppStore((s) => s.freezeExtractionCollection);
  const loadVersions = useAppStore((s) => s.loadExtractionCollectionVersions);
  const loadFilterOptions = useAppStore((s) => s.loadExtractionCollectionFilterOptions);
  const setFilters = useAppStore((s) => s.setExtractionCollectionFilters);
  const toggleSelection = useAppStore((s) => s.toggleExtractionCandidateSelection);

  const [form, setForm] = useState({ query: "", year_from: "", year_to: "", journal: "", site: "", limit: "50", source: "metadata_search" });
  const [question, setQuestion] = useState("");
  const [screenPrompt, setScreenPrompt] = useState("");
  const [bulkReason, setBulkReason] = useState("not_relevant");

  useEffect(() => {
    if (!task?.taskId) return;
    loadCandidates(task.taskId).catch(() => {});
    loadVersions(task.taskId).catch(() => {});
    loadFilterOptions(task.taskId).catch(() => {});
  }, [task?.taskId]);

  const selectedIds = useMemo(
    () => Object.keys(collection.selectedCandidateIds || {}).filter((id) => collection.selectedCandidateIds[id]),
    [collection.selectedCandidateIds]
  );
  const counts = useMemo(() => {
    const base = { total: collection.candidates.length, include: 0, exclude: 0, uncertain: 0, candidate: 0, duplicate: 0 };
    for (const item of collection.candidates) {
      base[item.userDecision] = (base[item.userDecision] || 0) + 1;
      if (item.duplicateGroupId) base.duplicate += 1;
    }
    return base;
  }, [collection.candidates]);
  const allSelected = collection.candidates.length > 0 && selectedIds.length === collection.candidates.length;
  const yearOptions = useMemo(() => [...(collection.filterOptions.years || [])].sort((a, b) => b - a), [collection.filterOptions.years]);

  const updateForm = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));
  const normalizedSearchPayload = (patch = {}) => ({
    query: form.query.trim(),
    limit: limitToPayload(form.limit),
    year_from: form.year_from ? Number(form.year_from) : null,
    year_to: form.year_to ? Number(form.year_to) : null,
    journal: form.journal.trim(),
    site: form.site.trim(),
    source: form.source || "metadata_search",
    ...patch,
  });

  const runSearch = async (payload = null) => {
    await searchCollection(task.taskId, payload || normalizedSearchPayload());
  };

  const runExpansionQuery = (item) => {
    const payload = {
      query: item.query,
      limit: item.limit === undefined ? 50 : item.limit,
      year_from: item.yearFrom ?? null,
      year_to: item.yearTo ?? null,
      journal: item.journal || "",
      site: item.site || "",
      source: item.source || "question_expansion",
    };
    setForm({
      query: payload.query,
      year_from: payload.year_from || "",
      year_to: payload.year_to || "",
      journal: payload.journal,
      site: payload.site,
      limit: limitToForm(payload.limit),
      source: payload.source,
    });
    runSearch(payload);
  };

  const selectAll = () => {
    for (const item of collection.candidates) {
      toggleSelection(item.candidateId, !allSelected);
    }
  };

  const runBulk = async (decision) => {
    if (selectedIds.length === 0) return;
    await bulkDecision(task.taskId, {
      candidateIds: selectedIds,
      decision,
      excludeReason: decision === "exclude" ? bulkReason : null,
    });
  };

  const toggleDecision = async (item, decision) => {
    const nextDecision = item.userDecision === decision ? "candidate" : decision;
    await setDecision(task.taskId, item.candidateId, {
      decision: nextDecision,
      excludeReason: nextDecision === "exclude" ? bulkReason : null,
    });
  };

  return (
    <div className="space-y-4">
      {collection.error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {collection.error}
        </div>
      )}

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">文献来源 / 收集</h2>
            <div className="mt-1 text-[12px] text-ink-500">本地研究索引元数据检索</div>
          </div>
          <button
            type="button"
            onClick={() => loadCandidates(task.taskId)}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100"
          >
            <RefreshCcw size={13} />
            刷新
          </button>
        </div>

        <div className="space-y-3 p-4">
          <div className="grid gap-2 lg:grid-cols-[minmax(260px,1.6fr)_160px_160px_160px]">
            <input
              value={form.query}
              onChange={(e) => updateForm("query", e.target.value)}
              className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber"
              placeholder="关键词、DOI、paper_id"
            />
            <select value={form.year_from} onChange={(e) => updateForm("year_from", e.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber">
              <option value="">起始年份</option>
              {yearOptions.map((year) => <option key={`from-${year}`} value={year}>{year}</option>)}
            </select>
            <select value={form.year_to} onChange={(e) => updateForm("year_to", e.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber">
              <option value="">结束年份</option>
              {yearOptions.map((year) => <option key={`to-${year}`} value={year}>{year}</option>)}
            </select>
            <select value={form.limit} onChange={(e) => updateForm("limit", e.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber">
              {LIMIT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>

          <div className="grid gap-2 lg:grid-cols-[minmax(220px,1fr)_minmax(220px,1fr)_180px_auto]">
            <select value={form.journal} onChange={(e) => updateForm("journal", e.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber">
              <option value="">全部期刊</option>
              {(collection.filterOptions.journals || []).map((journal) => <option key={journal} value={journal}>{journal}</option>)}
            </select>
            <select value={form.site} onChange={(e) => updateForm("site", e.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber">
              <option value="">全部来源站点</option>
              {(collection.filterOptions.sites || []).map((site) => <option key={site} value={site}>{site}</option>)}
            </select>
            <select
              value={collection.filters.decision}
              onChange={(e) => {
                setFilters({ decision: e.target.value });
                loadCandidates(task.taskId, { ...collection.filters, decision: e.target.value });
              }}
              className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber"
            >
              <option value="">全部决策</option>
              <option value="candidate">候选</option>
              <option value="include">纳入</option>
              <option value="exclude">排除</option>
              <option value="uncertain">不确定</option>
            </select>
            <button type="button" onClick={() => runSearch()} disabled={collection.loading} className="inline-flex items-center justify-center gap-1.5 rounded-md bg-ink-900 px-4 py-2 text-[13px] text-white disabled:opacity-60">
              {collection.loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
              检索
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <div className="flex min-w-[240px] flex-1 items-center gap-2">
              <Sparkles size={15} className="text-amber" />
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                className="min-w-0 flex-1 rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber"
                placeholder="研究问题扩展"
              />
              <button type="button" onClick={() => expandQuestion(task.taskId, { question, limit: 5 })} disabled={!question.trim() || collection.loading} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
                生成检索式
              </button>
            </div>
            <input
              value={collection.filters.q}
              onChange={(e) => setFilters({ q: e.target.value })}
              onBlur={() => loadCandidates(task.taskId)}
              className="min-w-[220px] rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber"
              placeholder="筛选标题 / DOI / 期刊"
            />
          </div>

          {collection.filterOptions.available === false && (
            <div className="text-[12px] text-ink-500">本地研究索引暂不可用，筛选选项为空。</div>
          )}

          {collection.expansion?.available === false && <div className="text-[12px] text-ink-500">LLM 暂不可用</div>}
          {collection.expansion?.queries?.length > 0 && (
            <div className="grid gap-2 md:grid-cols-2">
              {collection.expansion.queries.map((item, index) => (
                <button key={`${item.query}-${index}`} type="button" onClick={() => runExpansionQuery(item)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-left text-[12.5px] text-ink-700 hover:border-amber">
                  {item.query}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-6">
        <Metric label="候选" value={counts.total} />
        <Metric label="纳入" value={counts.include} />
        <Metric label="排除" value={counts.exclude} />
        <Metric label="不确定" value={counts.uncertain} />
        <Metric label="重复组" value={counts.duplicate} />
        <Metric label="版本" value={task.currentCollectionVersion || "-"} />
      </div>

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={selectAll} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">
              {allSelected ? "取消全选" : "全选"}
            </button>
            <button type="button" onClick={() => runBulk("candidate")} disabled={selectedIds.length === 0} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
              <RotateCcw size={13} />
              恢复候选
            </button>
            <button type="button" onClick={() => runBulk("include")} disabled={selectedIds.length === 0} className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 px-2.5 py-1.5 text-[12px] text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">
              <Check size={13} />
              纳入所选
            </button>
            <button type="button" onClick={() => runBulk("uncertain")} disabled={selectedIds.length === 0} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
              <HelpCircle size={13} />
              不确定
            </button>
            <select value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} className="rounded-md border border-line bg-paper-50 px-2 py-1.5 text-[12px] outline-none">
              {EXCLUDE_REASONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <button type="button" onClick={() => runBulk("exclude")} disabled={selectedIds.length === 0} className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-2.5 py-1.5 text-[12px] text-red-600 hover:bg-red-50 disabled:opacity-50">
              <X size={13} />
              排除所选
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={screenPrompt} onChange={(e) => setScreenPrompt(e.target.value)} className="w-[220px] rounded-md border border-line bg-paper-50 px-2.5 py-1.5 text-[12px] outline-none focus:border-amber" placeholder="LLM 筛选提示" />
            <button type="button" onClick={() => screenCandidates(task.taskId, { candidateIds: selectedIds, prompt: screenPrompt })} disabled={selectedIds.length === 0 || collection.screening} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
              {collection.screening ? <Loader2 size={13} className="animate-spin" /> : <Bot size={13} />}
              LLM 筛选
            </button>
            <button type="button" onClick={() => freezeCollection(task.taskId)} disabled={counts.include === 0 || collection.freezing} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-1.5 text-[12px] text-white disabled:opacity-50">
              {collection.freezing ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}
              冻结集合
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-[12.5px]">
            <thead className="bg-paper-50 text-[11px] uppercase text-ink-400">
              <tr>
                <th className="w-10 px-3 py-2"></th>
                <th className="min-w-[340px] px-3 py-2">文献</th>
                <th className="px-3 py-2">年份</th>
                <th className="px-3 py-2">期刊</th>
                <th className="px-3 py-2">匹配</th>
                <th className="px-3 py-2">评分</th>
                <th className="px-3 py-2">LLM</th>
                <th className="px-3 py-2">决策</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {collection.candidates.map((item) => (
                <tr key={item.candidateId} className="border-t border-line align-top hover:bg-paper-50">
                  <td className="px-3 py-3">
                    <input type="checkbox" checked={!!collection.selectedCandidateIds[item.candidateId]} onChange={(e) => toggleSelection(item.candidateId, e.target.checked)} />
                  </td>
                  <td className="px-3 py-3">
                    <div className="font-medium leading-5 text-ink-900">{item.title || "未命名文献"}</div>
                    <div className="mt-1 max-w-[560px] truncate text-[11.5px] text-ink-500">{item.authors.join(", ")} {item.doi ? `· ${item.doi}` : ""}</div>
                    {item.duplicateGroupId && <div className="mt-1 text-[11.5px] text-amber">重复 · 主记录 {item.canonicalPaperId}</div>}
                  </td>
                  <td className="px-3 py-3 text-ink-700">{item.year || "-"}</td>
                  <td className="max-w-[190px] px-3 py-3 text-ink-700">{item.journal || "-"}</td>
                  <td className="px-3 py-3 text-ink-600">{item.matchedFields.join(", ") || "-"}</td>
                  <td className="px-3 py-3 font-mono text-ink-700">{fmtScore(item.metadataScore)}</td>
                  <td className="px-3 py-3">
                    <div className="text-ink-700">{item.llmDecision || "-"}</div>
                    {item.llmReason && <div className="mt-1 max-w-[180px] truncate text-[11px] text-ink-500">{item.llmReason}</div>}
                  </td>
                  <td className="px-3 py-3">
                    <span className={`rounded px-2 py-1 text-[11.5px] ${decisionClass(item.userDecision)}`}>{decisionText(item.userDecision)}</span>
                    {item.excludeReason && <div className="mt-1 text-[11px] text-ink-500">{item.excludeReason}</div>}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex gap-1">
                      <button title={item.userDecision === "include" ? "恢复候选" : "纳入"} type="button" onClick={() => toggleDecision(item, "include")} className={`rounded-md border p-1.5 ${item.userDecision === "include" ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-emerald-200 text-emerald-700 hover:bg-emerald-50"}`}>
                        <Check size={13} />
                      </button>
                      <button title={item.userDecision === "uncertain" ? "恢复候选" : "不确定"} type="button" onClick={() => toggleDecision(item, "uncertain")} className={`rounded-md border p-1.5 ${item.userDecision === "uncertain" ? "border-amber/40 bg-amber/10 text-amber" : "border-line text-ink-700 hover:bg-paper-100"}`}>
                        <HelpCircle size={13} />
                      </button>
                      <button title={item.userDecision === "exclude" ? "恢复候选" : "排除"} type="button" onClick={() => toggleDecision(item, "exclude")} className={`rounded-md border p-1.5 ${item.userDecision === "exclude" ? "border-red-300 bg-red-50 text-red-600" : "border-red-200 text-red-600 hover:bg-red-50"}`}>
                        <X size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {collection.candidates.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-[13px] text-ink-500">
                    暂无候选文献
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-line bg-paper-0 px-3 py-3">
      <div className="text-[11px] text-ink-400">{label}</div>
      <div className="mt-1 truncate font-mono text-[18px] text-ink-900">{value}</div>
    </div>
  );
}

function decisionText(value) {
  return {
    candidate: "候选",
    include: "纳入",
    exclude: "排除",
    uncertain: "不确定",
  }[value] || value;
}

function decisionClass(value) {
  if (value === "include") return "bg-emerald-50 text-emerald-700";
  if (value === "exclude") return "bg-red-50 text-red-600";
  if (value === "uncertain") return "bg-amber/10 text-amber";
  return "bg-paper-100 text-ink-600";
}
