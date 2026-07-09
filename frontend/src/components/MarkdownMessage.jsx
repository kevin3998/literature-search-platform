import React from "react";
import clsx from "clsx";
import { citationAriaLabel, citationOrdinalLabel, evidenceIdLabel } from "./citationLabels.js";

// Lightweight Markdown renderer for agent answers. Covers the subset the
// research agent actually emits — headings, bold, inline code, blockquotes,
// horizontal rules, ordered/unordered lists, and GFM tables — while keeping the
// platform's [E#] citation highlighting. Intentionally dependency-free.

// Match both half-width [E#] and full-width 【E#】 citations (Chinese-output models
// emit 【E#】). slice(1, -1) strips one bracket char on each side either way.
const CITATION_RE = /([[【][A-Za-z]+\d+[\]】])|(\*\*[^*]+\*\*)|(`[^`]+`)/g;
const CITATION_ID_RE = /[[【]([A-Za-z]+\d+)[\]】]/g;

// Map each distinct evidence id to a stable sequential number by first
// appearance (paper convention — the same id always reuses its number).
export function buildCitationNumbers(text) {
  const map = new Map();
  let n = 0;
  let m;
  CITATION_ID_RE.lastIndex = 0;
  while ((m = CITATION_ID_RE.exec(text || "")) !== null) {
    if (!map.has(m[1])) map.set(m[1], ++n);
  }
  return map;
}

// id -> used-evidence entry (for the hover tooltip), keyed by every id a merged
// entry covers.
export function buildEvidenceById(citation) {
  const map = new Map();
  for (const e of citation?.used_evidence || []) {
    for (const id of e.evidence_ids || [e.evidence_id]) {
      if (id) map.set(id, e);
    }
  }
  return map;
}

function clampSnippet(text, n = 170) {
  if (!text) return "";
  const t = String(text).replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

// Inline citation as a small numbered badge that reveals the source on hover/focus.
function CitationChip({ id, n, ev, unverified }) {
  const label = unverified ? "未核验" : citationOrdinalLabel(n);
  return (
    <span className="group relative inline-block align-super leading-none">
      <button
        type="button"
        aria-label={unverified ? `未核验引用，${evidenceIdLabel(id)}` : citationAriaLabel(id, n)}
        title={unverified ? "未找到对应证据（可能是模型虚构的引用）" : undefined}
        className={clsx(
          "inline-flex items-center justify-center min-w-[30px] h-[16px] px-1.5 ml-0.5 rounded-[7px] text-[9.5px] font-medium transition-colors cursor-default",
          unverified
            ? "bg-red-50 text-red-600 border border-red-200"
            : "bg-amber-50 text-amber-700 hover:bg-amber-100"
        )}
      >
        {label}
      </button>
      {ev && (
        <span className="absolute left-1/2 -translate-x-1/2 bottom-full mb-1.5 z-30 hidden w-64 group-hover:block group-focus-within:block">
          <span className="block rounded-md border border-line bg-paper-0 shadow-lg px-3 py-2 text-left">
            <span className="block text-[11.5px] text-ink-800 leading-snug">{ev.title || ev.doi || "证据"}</span>
            {(ev.section || ev.year || ev.journal) && (
              <span className="block text-[10.5px] text-ink-400 mt-0.5">
                {[ev.section, ev.year, ev.journal].filter(Boolean).join(" · ")}
              </span>
            )}
            {ev.snippet && <span className="block text-[11px] text-ink-500 mt-1 leading-snug">{clampSnippet(ev.snippet, 170)}</span>}
            <span className="block font-mono text-[10px] text-ink-300 mt-1">{evidenceIdLabel(id)}</span>
          </span>
        </span>
      )}
    </span>
  );
}

function renderInline(text, keyBase = "", ctx = {}) {
  const { missing, numbers, evidenceById } = ctx;
  const nodes = [];
  let last = 0;
  let m;
  let i = 0;
  CITATION_RE.lastIndex = 0;
  while ((m = CITATION_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(<React.Fragment key={`${keyBase}-t${i++}`}>{text.slice(last, m.index)}</React.Fragment>);
    if (m[1]) {
      const id = m[1].slice(1, -1);
      nodes.push(
        <CitationChip
          key={`${keyBase}-c${i++}`}
          id={id}
          n={numbers ? numbers.get(id) : undefined}
          ev={evidenceById ? evidenceById.get(id) : undefined}
          unverified={!!(missing && missing.has(id))}
        />
      );
    } else if (m[2]) {
      nodes.push(<strong key={`${keyBase}-b${i++}`} className="font-semibold text-ink-900">{m[2].slice(2, -2)}</strong>);
    } else if (m[3]) {
      nodes.push(<code key={`${keyBase}-k${i++}`} className="font-mono text-[12.5px] bg-paper-100 rounded px-1 py-0.5">{m[3].slice(1, -1)}</code>);
    }
    last = CITATION_RE.lastIndex;
  }
  if (last < text.length) nodes.push(<React.Fragment key={`${keyBase}-t${i++}`}>{text.slice(last)}</React.Fragment>);
  return nodes;
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

const isTableSep = (line) => /^\s*\|?[\s:\-]*-[\s:\-|]*\|?\s*$/.test(line) && line.includes("-");
const isHeading = (line) => /^#{1,6}\s+/.test(line);
const isHr = (line) => /^\s*([-*_])\1{2,}\s*$/.test(line);
const isUl = (line) => /^\s*[-*+]\s+/.test(line);
const isOl = (line) => /^\s*\d+\.\s+/.test(line);
const isQuote = (line) => /^\s*>\s?/.test(line);

export default function MarkdownMessage({ text, missingIds, numbers, evidenceById }) {
  const missing = missingIds && missingIds.length ? new Set(missingIds) : null;
  const ctx = { missing, numbers: numbers || buildCitationNumbers(text), evidenceById: evidenceById || null };
  const inline = (t, k) => renderInline(t, k, ctx);
  const lines = (text || "").split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") { i++; continue; }

    if (isHr(line)) { blocks.push({ type: "hr" }); i++; continue; }

    if (isHeading(line)) {
      const mm = line.match(/^(#{1,6})\s+(.*)$/);
      blocks.push({ type: "heading", level: mm[1].length, text: mm[2] });
      i++;
      continue;
    }

    // GFM table: header row followed by a separator row
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const header = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    if (isQuote(line)) {
      const buf = [];
      while (i < lines.length && isQuote(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      blocks.push({ type: "quote", text: buf.join("\n") });
      continue;
    }

    if (isUl(line) || isOl(line)) {
      const ordered = isOl(line);
      // Honor the authored start number. The agent often writes a numbered list
      // whose items are separated by nested "- ..." sub-bullets or by ### section
      // headings, which split it into multiple <ol> blocks; without `start` every
      // block would restart at 1 (the reported "编号问题": all items showed "1.").
      const start = ordered ? parseInt(line.match(/^\s*(\d+)\./)[1], 10) : undefined;
      const items = [];
      while (i < lines.length && (ordered ? isOl(lines[i]) : isUl(lines[i]))) {
        items.push(lines[i].replace(ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered, items, start });
      continue;
    }

    // paragraph: gather consecutive plain lines
    const buf = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !isHeading(lines[i]) && !isHr(lines[i]) && !isUl(lines[i]) && !isOl(lines[i]) && !isQuote(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: "p", lines: buf });
  }

  const HEADING_CLS = {
    1: "font-serif text-[17px] font-semibold text-ink-900 mt-3.5 first:mt-0",
    2: "font-serif text-[15.5px] font-semibold text-ink-900 mt-3.5 first:mt-0",
    3: "text-[14px] font-semibold text-ink-900 mt-3",
    4: "text-[13.5px] font-semibold text-ink-800 mt-2.5",
    5: "text-[13px] font-semibold text-ink-800 mt-2",
    6: "text-[13px] font-semibold text-ink-700 mt-2",
  };

  return (
    <div>
      {blocks.map((b, bi) => {
        if (b.type === "hr") return <hr key={bi} className="my-3 border-t border-line" />;
        if (b.type === "heading") {
          const Tag = `h${Math.min(b.level, 6)}`;
          return <Tag key={bi} className={HEADING_CLS[b.level] || HEADING_CLS[6]}>{inline(b.text, `h${bi}`)}</Tag>;
        }
        if (b.type === "quote") {
          return (
            <blockquote key={bi} className="mt-2.5 border-l-2 border-amber/40 pl-3 text-ink-600 text-[13.5px]">
              {b.text.split("\n").map((l, li) => (
                <React.Fragment key={li}>{li > 0 && <br />}{inline(l, `q${bi}-${li}`)}</React.Fragment>
              ))}
            </blockquote>
          );
        }
        if (b.type === "list") {
          const Tag = b.ordered ? "ol" : "ul";
          return (
            <Tag
              key={bi}
              start={b.ordered && b.start && b.start !== 1 ? b.start : undefined}
              className={clsx("mt-2 pl-5 space-y-1", b.ordered ? "list-decimal" : "list-disc")}
            >
              {b.items.map((it, ii) => <li key={ii}>{inline(it, `l${bi}-${ii}`)}</li>)}
            </Tag>
          );
        }
        if (b.type === "table") {
          return (
            <div key={bi} className="mt-2.5 overflow-x-auto">
              <table className="w-full text-[12.5px] border-collapse">
                <thead>
                  <tr>
                    {b.header.map((h, hi) => (
                      <th key={hi} className="border border-line bg-paper-100 px-2.5 py-1.5 text-left font-semibold text-ink-800">
                        {inline(h, `th${bi}-${hi}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, ri) => (
                    <tr key={ri}>
                      {row.map((cell, ci) => (
                        <td key={ci} className="border border-line px-2.5 py-1.5 align-top text-ink-700">
                          {inline(cell, `td${bi}-${ri}-${ci}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        // paragraph
        return (
          <p key={bi} className="mt-2.5 first:mt-0">
            {b.lines.map((l, li) => (
              <React.Fragment key={li}>{li > 0 && <br />}{inline(l, `p${bi}-${li}`)}</React.Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
