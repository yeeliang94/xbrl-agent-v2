// Run-screen answers in the shapes of docs/api-contract.md, for the tests.
import { run } from "../../test-utils";
import type { RunDetail } from "../../api";
import type { Cell, Check, Comment, Guidance, NeedsYou, Round, RoundReport, RunEvent, ScopeQuestion, Statement, StatementRow } from "../../api";

const cell = (figure_id: number | null, value: number | null, over: Partial<Cell> = {}): Cell => ({
  figure_id, concept_uuid: "", value, printed: value, stated: null, certainty: "sure", reason: "", edited: false,
  origin: figure_id ? "agent" : null, writable: true, agent_writable: true, lines_sum: null, ...over,
});

const row = (over: Partial<StatementRow> & Pick<StatementRow, "label" | "concept_uuid">): StatementRow => ({
  kind: "line", field_label: over.label, printed_label: over.label, sheet: "SOFP-CuNonCu", row: 1, page: 7, print_order: 1,
  cells: {}, status: null, certainty: "sure", reason: "", edited: false, ...over,
});

function withConcept(r: StatementRow): StatementRow {
  return { ...r, cells: Object.fromEntries(Object.entries(r.cells).map(([k, c]) => [k, { ...c, concept_uuid: r.concept_uuid }])) };
}

export const sofp: Statement = {
  run_id: 1, statement: "SOFP", variant: "CuNonCu", template_id: "mfrs-company-sofp-cunoncu-v1", order: "report",
  columns: [
    { key: "Company:CY", label: "This year", entity_scope: "Company", period: "CY", matrix_col: null },
    { key: "Company:PY", label: "Last year", entity_scope: "Company", period: "PY", matrix_col: null },
  ],
  rows: [
    row({ kind: "heading", label: "Current assets", concept_uuid: "h-ca", cells: {} }),
    row({
      label: "Other receivables, deposits and prepayments", field_label: "Other receivables", concept_uuid: "orecv",
      cells: { "Company:CY": cell(18, 318450, { certainty: "unsure", reason: "Note 11 includes 42,000 due from a director." }), "Company:PY": cell(19, 276900) },
      status: "unsure", certainty: "unsure", reason: "Note 11 includes 42,000 due from a director.",
    }),
    row({ label: "Cash and bank balances", field_label: "Cash and cash equivalents", concept_uuid: "cash", cells: { "Company:CY": cell(7, 1264900), "Company:PY": cell(8, 986750) } }),
    row({ label: "Other payables and accruals", field_label: "Other payables", concept_uuid: "opay", cells: { "Company:CY": cell(30, 512750), "Company:PY": cell(31, 389200) } }),
    row({ kind: "total", label: "Total equity and liabilities", concept_uuid: "tel", cells: { "Company:CY": cell(40, 11272400, { writable: false }), "Company:PY": cell(41, 10029100, { writable: false }) }, status: "does_not_tally" }),
  ].map(withConcept),
};

export const checks: Check[] = [
  {
    name: "sofp_balance", title: "Total assets equal total equity and liabilities", entity_scope: "Company", status: "failed", period: "PY",
    message: "For the Company, last year, Total assets is 10,038,100 and Total equity and liabilities is 10,029,100, a difference of 9,000.",
    comparands: [{ label: "Total assets", statement: "SOFP", period: "PY" }], target_concept_uuid: "tel",
  },
];

export const needs: NeedsYou = {
  items: [
    { kind: "failed_check", title: "Total assets equal total equity and liabilities", message: checks[0].message, check: "sofp_balance", statement: "SOFP", concept_uuid: "tel", period: "PY", entity_scope: "Company", figure_id: 41 },
    { kind: "unsure", title: "Other receivables, this year", message: "Note 11 includes 42,000 due from a director.", statement: "SOFP", concept_uuid: "orecv", period: "CY", entity_scope: "Company", figure_id: 18 },
    {
      kind: "alike", title: "1 line filed under a different name", message: "For example “Cash and bank balances” filed as Cash and cash equivalents.", count: 1,
      lines: [{ figure_id: 7, printed_label: "Cash and bank balances", field_label: "Cash and cash equivalents", statement: "SOFP", concept_uuid: "cash", period: "CY", entity_scope: "Company" }],
    },
  ],
  passed: 214,
};

export const comment = (over: Partial<Comment> = {}): Comment => ({
  id: 4, run_id: 1, author_kind: "person", author_name: "aina@firm.my",
  target: { kind: "figure", statement: "SOFP", concept_uuid: "opay", period: "PY", entity_scope: "Company", dimension_key: "", field_label: "Other payables", figure_id: 31 },
  text: "Page 7 prints 398,200 for last year.", scope: "figure", status: "open", outcome: null, answer: null, proposed_guidance: null,
  round_id: null, created_at: "2026-11-22T09:00:00Z", updated_at: "2026-11-22T09:00:00Z", ...over,
});

export const round = (over: Partial<Round> = {}): Round => ({
  id: 2, run_id: 1, number: 1, status: "done", sent_by: "aina@firm.my", sent_at: "2026-11-22T09:01:00Z", started_at: "2026-11-22T09:01:01Z",
  finished_at: "2026-11-22T09:02:00Z", summary: "Used page 7's payables.", error: null, stop_requested: false, comment_ids: [4, 5], ...over,
});

export const report: RoundReport = {
  round_id: 2,
  comments: [
    {
      comment_id: 4, outcome: "changed", answer: "Used 398,200 as page 7 prints.", changed: true, verified: true,
      figures: [{ figure_id: 31, statement: "SOFP", concept_uuid: "opay", field_label: "Other payables", period: "PY", entity_scope: "Company", dimension_key: "", was: 389200, is_now: 398200, changed: true, served: [4], differences: ["certainty sure → unsure", "reason changed"] }],
    },
    { comment_id: 5, outcome: "question", answer: "Which lines should change?", changed: false, verified: false, figures: [] },
  ],
  other: [{ figure_id: 50, statement: "SOFP", concept_uuid: "tcl", field_label: "Total current liabilities", period: "PY", entity_scope: "Company", dimension_key: "", was: 1, is_now: 2, changed: true, served: [] }],
  totals_recalculated: [],
  counts: { comments: 2, changed: 1, other: 1, totals_recalculated: 0 },
};

export const event = (id: number, message: string, over: Partial<RunEvent> = {}): RunEvent => ({
  id, job_id: 3, source: "extraction", kind: "notice", message, created_at: `2026-11-22T09:00:${String(id).padStart(2, "0")}Z`, has_data: false, ...over,
});

export const scopeQuestion = (over: Partial<ScopeQuestion> = {}): ScopeQuestion => ({
  id: 3, run_id: 1, stage: "extract", asked_by: "figures", field: "standard", statement: null,
  question: "This looks like an MPERS filing. Which standard applies?",
  evidence: [{ text: "“…the Malaysian Private Entities Reporting Standard…”", page: 3 }, { text: "“…Malaysian Financial Reporting Standards…”", page: 13 }],
  choices: [
    { label: "MPERS", value: "MPERS", effect: "Restarts extraction with the MPERS templates", suggested: true },
    { label: "MFRS, as set up", value: "MFRS", effect: "Carries on", suggested: false },
  ],
  setup_value: "MFRS", status: "open", asked_at: "2026-11-22T09:00:30Z", answer: null, ...over,
});

export const guidance = (lines: string[], version = 1, company_id: number | null = 4): Guidance => ({
  company_id, version, lines, saved_by: "aina@firm.my", saved_at: "2026-11-22T09:00:00Z", source: "typed", comment_id: null, restored_from: null,
});

export const runDetail = (over: Partial<RunDetail> = {}): RunDetail => ({
  ...run({ id: 1 }),
  statements: [{ statement: "SOFP", name: "statement of financial position", layout: "CuNonCu", layout_label: "Current and non-current", pages: [7] }],
  failure: null, working_on: null, open_question_id: null,
  stages: [{ name: "extract", status: "done", started_at: "2026-11-22T09:00:00Z", finished_at: "2026-11-22T09:01:00Z", error: null }],
  ...over,
});
