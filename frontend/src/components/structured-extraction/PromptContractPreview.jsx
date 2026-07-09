import React, { useMemo, useState } from "react";
import { ChevronDown, Copy } from "lucide-react";
import { buildPromptContractSections, stringify, summarizePromptContract } from "./promptContractViewModel";

export default function PromptContractPreview({ contract }) {
  const [openSections, setOpenSections] = useState({});
  const [copiedKey, setCopiedKey] = useState("");
  const summary = useMemo(() => summarizePromptContract(contract), [contract]);
  const sections = useMemo(() => buildPromptContractSections(contract), [contract]);

  const toggle = (key) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const copySection = async (section) => {
    await navigator.clipboard?.writeText(section.copyText || "");
    setCopiedKey(section.key);
    window.setTimeout(() => setCopiedKey(""), 1200);
  };

  if (!contract) {
    return (
      <section className="rounded-lg border border-line bg-paper-0 p-5 text-center text-[13px] text-ink-500">
        尚未编译提示词契约
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line bg-paper-0">
      <div className="border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">提示词契约预览</h2>
            <div className="mt-1 text-[12px] text-ink-500">{contract.promptContractVersion || "-"} · {fmtDate(contract.createdAt)}</div>
          </div>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-5">
          {summary.map(([label, value]) => (
            <div key={label} className="rounded-md border border-line bg-paper-50 px-3 py-2">
              <div className="text-[11px] text-ink-400">{label}</div>
              <div className="mt-1 truncate font-mono text-[12px] text-ink-800">{value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="divide-y divide-line">
        {sections.map((section) => {
          const open = !!openSections[section.key];
          return (
            <div key={section.key}>
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <button type="button" onClick={() => toggle(section.key)} className="flex min-w-0 items-center gap-2 text-left">
                  <ChevronDown size={15} className={`flex-shrink-0 text-ink-400 transition-transform ${open ? "" : "-rotate-90"}`} />
                  <span className="text-[13px] font-medium text-ink-800">{section.title}</span>
                  {section.count !== undefined && <span className="rounded bg-paper-100 px-1.5 py-0.5 text-[10.5px] text-ink-500">{section.count}</span>}
                </button>
                <button type="button" onClick={() => copySection(section)} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1.5 text-[11.5px] text-ink-600 hover:bg-paper-100">
                  <Copy size={12} />
                  {copiedKey === section.key ? "已复制" : "复制"}
                </button>
              </div>
              {open && (
                <div className="border-t border-line bg-paper-50 px-4 py-3">
                  <SectionBody section={section} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SectionBody({ section }) {
  if (section.kind === "rules") {
    const rules = section.data || [];
    return rules.length ? (
      <ol className="space-y-2 text-[12.5px] text-ink-700">
        {rules.map((rule, index) => <li key={`${rule}-${index}`}>{index + 1}. {rule}</li>)}
      </ol>
    ) : (
      <div className="text-[12.5px] text-ink-500">暂无抽取规则</div>
    );
  }
  if (section.kind === "fields") {
    return <FieldContractTable fields={section.data || []} />;
  }
  return <JsonPreview value={section.data} />;
}

function FieldContractTable({ fields }) {
  if (!fields.length) return <div className="text-[12.5px] text-ink-500">暂无字段契约</div>;
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-paper-0">
      <table className="min-w-full border-collapse text-left text-[12px]">
        <thead className="bg-paper-100 text-[10.5px] uppercase text-ink-400">
          <tr>
            <th className="min-w-[150px] px-3 py-2">字段键</th>
            <th className="min-w-[140px] px-3 py-2">名称</th>
            <th className="px-3 py-2">类型</th>
            <th className="px-3 py-2">分组</th>
            <th className="px-3 py-2">必填</th>
            <th className="px-3 py-2">证据</th>
            <th className="px-3 py-2">单位</th>
            <th className="min-w-[240px] px-3 py-2">抽取指令</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.key} className="border-t border-line align-top">
              <td className="px-3 py-2 font-mono text-ink-800">{field.key || "-"}</td>
              <td className="px-3 py-2 text-ink-800">{field.label || "-"}</td>
              <td className="px-3 py-2 font-mono text-ink-700">{field.type || "-"}</td>
              <td className="px-3 py-2 font-mono text-ink-700">{field.groupKey || "-"}</td>
              <td className="px-3 py-2 text-ink-700">{field.required ? "是" : "否"}</td>
              <td className="px-3 py-2 text-ink-700">{field.evidenceRequired ? "需要" : "不需要"}</td>
              <td className="px-3 py-2 text-ink-700">{field.unit || "-"}</td>
              <td className="px-3 py-2 text-ink-600">{field.extractionInstruction || field.description || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonPreview({ value }) {
  return (
    <pre className="max-h-[360px] overflow-auto rounded-md border border-line bg-paper-0 p-3 text-[11.5px] leading-relaxed text-ink-700">
      {stringify(value)}
    </pre>
  );
}

function fmtDate(value) {
  if (!value) return "暂无时间";
  return new Date(value * 1000).toLocaleString("zh-CN");
}
