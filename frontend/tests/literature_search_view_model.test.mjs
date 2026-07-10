import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAuditItems,
  buildEvidenceItems,
  buildEvidenceSummary,
  buildFilteredEvidenceItems,
  buildPaperItems,
  buildPaperSummary,
  buildSessionEvidenceItems,
  buildSuggestedActions,
  detailValueText,
  evidenceCitationAlias,
  evidenceIdentityKeys,
  evidenceInternalIds,
  findAudit,
  findEvidence,
  findPaper,
  findSessionEvidence,
  latestAssistantMetadata,
} from "../src/components/literatureSearchViewModel.js";

test("latestAssistantMetadata exposes normalized route, failure, attachment and library metadata", () => {
  const session = {
    messages: [
      { role: "user", content: "当前文献库中一共有多少文献？" },
      {
        role: "assistant",
        content: "当前本地文献库中共有 3 篇文献。",
        metadata: {
          route: "library_count",
          routeLabel: "文献库状态",
          usedLibraryStats: true,
          libraryStats: { paperCount: 3 },
          failureCode: "attachment_missing",
          failureMessage: "当前会话没有可用附件。",
          usedAttachments: { attachmentCount: 1, filenames: ["note.txt"] },
        },
      },
    ],
  };

  const meta = latestAssistantMetadata(session);

  assert.equal(meta.route, "library_count");
  assert.equal(meta.routeLabel, "文献库状态");
  assert.equal(meta.usedLibraryStats, true);
  assert.equal(meta.libraryStats.paperCount, 3);
  assert.equal(meta.failureCode, "attachment_missing");
  assert.equal(meta.usedAttachments.filenames[0], "note.txt");
});

test("buildEvidenceItems keeps uploaded attachments out of formal literature evidence", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "来自上传附件《note.txt》：...",
        metadata: {
          route: "attachment_only",
          routeLabel: "读取上传附件",
          usedAttachments: { attachmentCount: 1, filenames: ["note.txt"] },
        },
      },
    ],
  };

  const evidence = buildEvidenceItems(session);

  assert.equal(evidence.length, 0);
  assert.equal(evidence.summary.sourceKind, "literature_evidence");
  assert.match(evidence.summary.emptyReason, /上传附件/);
});

test("buildPaperItems explains why non-retrieval routes have no candidate papers", () => {
  const session = {
    papers: [],
    messages: [
      {
        role: "assistant",
        content: "当前本地文献库中共有 3 篇文献。",
        metadata: { route: "library_count", routeLabel: "文献库状态" },
      },
    ],
  };

  const papers = buildPaperItems(session);

  assert.equal(papers.length, 0);
  assert.match(papers.summary.emptyReason, /未执行主题检索/);
});

test("buildAuditItems creates readable route, attachment, library and failure audit items", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "当前会话没有可用附件。",
        metadata: {
          route: "attachment_missing",
          routeLabel: "缺少附件",
          failureCode: "attachment_missing",
          failureMessage: "当前会话没有可用附件。",
          usedAttachments: { attachmentCount: 1, filenames: ["note.txt"] },
          usedLibraryStats: true,
          libraryStats: { paperCount: 3, articleIndexCount: 4, yearRange: [2020, 2024] },
        },
      },
    ],
  };

  const items = buildAuditItems(session);

  assert.equal(findAudit(session, "route").label, "意图分流");
  assert.equal(findAudit(session, "attachments").label, "上传附件");
  assert.equal(findAudit(session, "library_status").label, "文献库状态");
  assert.equal(findAudit(session, "failure").severity, "warning");
  assert.match(findAudit(session, "failure").summary, /当前会话没有可用附件/);
});

test("buildSessionEvidenceItems merges current citation evidence with session evidence pool status", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "answer [1]",
        citation: { used_evidence: [{ alias: "1", evidence_id: "E1", title: "Current paper", snippet: "current snippet" }] },
      },
    ],
    researchState: {
      evidence_pool: {
        total: 2,
        status_counts: { accepted: 1, needs_review: 1 },
        recent: [
          { evidence_item_id: "evitem_1", evidence_id: "E1", title: "Current paper", snippet: "pooled snippet", status: "accepted", note: "关键证据" },
          { evidence_item_id: "evitem_2", evidence_id: "E2", title: "Older paper", snippet: "older snippet", status: "needs_review" },
        ],
      },
    },
  };

  const all = buildSessionEvidenceItems(session);
  const current = buildFilteredEvidenceItems(session, "current");
  const accepted = buildFilteredEvidenceItems(session, "accepted");

  assert.equal(all.length, 2);
  assert.equal(current.length, 1);
  assert.equal(current[0].status, "accepted");
  assert.equal(accepted[0].note, "关键证据");
  assert.equal(findSessionEvidence(session, "evitem_2").evidence_id, "E2");
  assert.equal(buildEvidenceSummary(session).accepted, 1);
});

test("citation-only evidence remains selectable by numeric alias", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "answer [11]",
        citation: {
          used_evidence: [
            {
              alias: "11",
              citation_alias: "11",
              title: "Alias paper",
              snippet: "citation snapshot",
              source_path: "articles/example/fulltext.md",
            },
          ],
        },
      },
    ],
    researchState: { evidence_pool: { recent: [] } },
  };

  const items = buildSessionEvidenceItems(session);
  const found = findEvidence(session, "11");

  assert.equal(items[0].id, "11");
  assert.equal(items[0].alias, "11");
  assert.equal(found.title, "Alias paper");
});

test("current citation merges with pooled evidence by physical source id", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "answer [4]",
        citation: {
          used_evidence: [
            {
              alias: "4",
              citation_alias: "4",
              evidence_id: "4",
              source_evidence_id: "E42",
              equivalent_source_evidence_ids: ["E43"],
              title: "Canonical paper",
              snippet: "citation snapshot",
              source_path: "articles/example/parsed/abstract.txt",
            },
          ],
        },
      },
    ],
    researchState: {
      evidence_pool: {
        recent: [
          {
            evidence_item_id: "evitem_42",
            evidence_id: "E42",
            title: "Canonical paper",
            status: "accepted",
            source_path: "articles/example/parsed/abstract.txt",
          },
        ],
      },
    },
  };

  const items = buildSessionEvidenceItems(session);

  assert.equal(items.length, 1);
  assert.equal(items[0].id, "evitem_42");
  assert.equal(items[0].citationAlias, "4");
  assert.equal(items[0].isCurrent, true);
  assert(evidenceIdentityKeys(items[0]).includes("source:research_index:E42"));
});

test("buildEvidenceItems carries real aliases without synthesizing list ordinals", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        citation: {
          used_evidence: [
            { alias: "4", source_evidence_id: "E40" },
            { citation_alias: "9", source_evidence_id: "E90" },
          ],
        },
      },
    ],
  };

  const items = buildEvidenceItems(session);

  assert.deepEqual(items.map((item) => item.citationAlias), ["4", "9"]);
  assert(items.every((item) => !("ordinal" in item)));
});

test("different fulltext chunks do not merge by source path alone", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        citation: {
          used_evidence: [
            {
              alias: "5",
              evidence_id: "5",
              source_evidence_id: "E50",
              section_id: "s0004-results",
              chunk_index: 1,
              source_path: "articles/example/parsed/fulltext.md",
            },
          ],
        },
      },
    ],
    researchState: {
      evidence_pool: {
        recent: [
          {
            evidence_item_id: "evitem_51",
            evidence_id: "E51",
            section_id: "s0004-results",
            chunk_index: 2,
            source_path: "articles/example/parsed/fulltext.md",
          },
        ],
      },
    },
  };

  const items = buildSessionEvidenceItems(session);

  assert.equal(items.length, 2);
});

test("same physical id from different namespaces does not merge", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        citation: {
          used_evidence: [
            {
              alias: "1",
              source_namespace: "research_index",
              source_evidence_id: "E1",
            },
          ],
        },
      },
    ],
    researchState: {
      evidence_pool: {
        recent: [
          {
            evidence_item_id: "pack_e1",
            source_namespace: "evidence_pack",
            evidence_id: "E1",
          },
        ],
      },
    },
  };

  assert.equal(buildSessionEvidenceItems(session).length, 2);
});

test("evidence detail helpers tolerate malformed citation identity fields", () => {
  const evidence = {
    alias: "11",
    evidence_id: "11",
    evidence_ids: { primary: "E123", extra: "E456" },
    source_evidence_id: "E789",
  };

  assert.equal(evidenceCitationAlias(evidence), "11");
  assert.deepEqual(evidenceInternalIds(evidence), ["E123", "E456", "E789"]);
  assert.equal(detailValueText({ source: "articles/example.md" }), '{"source":"articles/example.md"}');
});

test("evidence without a citation alias does not invent one", () => {
  assert.equal(evidenceCitationAlias({ evidence_id: "E123" }), null);
});

test("buildPaperItems and buildPaperSummary use research state candidate papers", () => {
  const session = {
    papers: [{ id: "p_current", title: "Current hit" }],
    researchState: {
      candidate_papers: [
        { key: "p1", paper_id: "p1", title: "Accepted paper", status: "accepted", evidence_count: 2 },
        { key: "p2", paper_id: "p2", title: "Excluded paper", status: "excluded", evidence_count: 1 },
      ],
      paper_status_counts: { accepted: 1, excluded: 1 },
    },
  };

  const papers = buildPaperItems(session);
  const summary = buildPaperSummary(session);

  assert.equal(papers.length, 2);
  assert.equal(papers[0].status, "accepted");
  assert.equal(summary.total, 2);
  assert.equal(summary.accepted, 1);
  assert.equal(summary.current, 1);
});

test("buildPaperItems enriches research state candidate papers with current retrieval snippets", () => {
  const session = {
    papers: [
      {
        id: "ui_result_1",
        paper_id: "p1",
        title: "Current retrieval title",
        snippet: "This is the readable matched snippet from the current retrieval.",
        abstract: "Long abstract text.",
        authors: ["A. Author"],
        year: 2024,
        venue: "Journal of Testing",
      },
    ],
    researchState: {
      candidate_papers: [
        {
          key: "p1",
          paper_id: "p1",
          title: "State title",
          status: "accepted",
          evidence_count: 2,
          note: "keep this",
        },
      ],
      paper_status_counts: { accepted: 1 },
    },
  };

  const papers = buildPaperItems(session);
  const found = findPaper(session, "p1");

  assert.equal(papers.length, 1);
  assert.equal(papers[0].status, "accepted");
  assert.equal(papers[0].snippet, "This is the readable matched snippet from the current retrieval.");
  assert.equal(papers[0].abstract, "Long abstract text.");
  assert.deepEqual(papers[0].authors, ["A. Author"]);
  assert.equal(papers[0].year, 2024);
  assert.equal(papers[0].venue, "Journal of Testing");
  assert.equal(papers[0].title, "State title");
  assert.equal(papers[0].isCurrent, true);
  assert.equal(found.snippet, papers[0].snippet);
});

test("buildSuggestedActions creates Chinese action suggestions from failures and review debt", () => {
  const session = {
    messages: [
      {
        role: "assistant",
        content: "当前会话没有可用附件。",
        metadata: { route: "attachment_missing", failureCode: "attachment_missing" },
        citation: { audit_status: "unverified", missing_ids: ["99"], used_evidence: [] },
      },
    ],
    researchState: {
      evidence_pool: { status_counts: { needs_review: 1 }, recent: [] },
      paper_status_counts: { needs_review: 1 },
    },
  };

  const actions = buildSuggestedActions(session);

  assert(actions.some((action) => action.id === "upload_attachment"));
  assert(actions.some((action) => action.id === "switch_evidence_mode"));
  assert(actions.some((action) => action.id === "review_pending_items"));
});
