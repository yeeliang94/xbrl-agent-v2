// Notes answers in the shapes of docs/api-contract.md "Step 6b" and
// "Step 6e". Made-up figures from
// prototypes/review-prototype-v4.html. Used by the tests; free of test code
// so a dev server can serve them too.
import type {
  CellLook,
  Note,
  NoteBlock,
  NoteField,
  NoteFigures,
  NoteReport,
  NoteReview,
  NoteSummary,
  StatementRow,
  TableBlock,
  TableRow,
  TextLook,
} from "../../api";

export const textLook = (over: Partial<TextLook> = {}): TextLook => ({ bold: false, italic: false, underline: false, align: null, indent: 0, unsure: [], ...over });
export const cellLook = (over: Partial<CellLook> = {}): CellLook => ({ bold: false, italic: false, underline: false, align: null, valign: null, unsure: [], ...over });

export const heading = (page: number, block: number, text: string, level = 1): NoteBlock => ({ kind: "heading", id: `p${page}b${block}`, source: { page, block }, level, text, look: textLook() });
export const paragraph = (page: number, block: number, text: string, over: Partial<TextLook> = {}): NoteBlock => ({
  kind: "paragraph", id: `p${page}b${block}`, source: { page, block }, text, look: textLook(over),
});

type RowSpec = { cells: string[]; role?: TableRow["role"]; line?: TableRow["line_below"]; unsure?: string[]; indent?: number; cellUnsure?: Record<number, string[]> };

/** A table whose first column is labels and the rest amounts, with a heading row. */
export function table(page: number, block: number, head: string[], rows: RowSpec[]): TableBlock {
  const width = head.length;
  const amounts = [...Array(width - 1).keys()].map((i) => i + 1);
  return {
    kind: "table", id: `p${page}b${block}`, source: { page, block },
    columns: head.map((_, i) => ({ role: i === 0 ? "label" : "amount", width: null, align: null, unsure: [] })),
    rows: [
      { role: "heading", cells: head.map((t) => ({ text: t, look: cellLook() })), indent: 0, bold: false, shaded: false, line_below: { style: "single", columns: amounts }, unsure: [] },
      ...rows.map((r) => ({
        role: r.role ?? "item",
        cells: r.cells.map((t, i) => ({ text: t, look: cellLook({ unsure: r.cellUnsure?.[i] ?? [] }) })),
        indent: r.indent ?? 0, bold: r.role === "subtotal", shaded: false, line_below: r.line ?? null, unsure: r.unsure ?? [],
      })),
    ],
    frame: "none", font_pt: null, unsure: [],
  };
}

const AMOUNT_LINE = (width: number, style: "single" | "double" = "single") => ({ style, columns: [...Array(width - 1).keys()].map((i) => i + 1) });

// The run's note fields ------------------------------------------------------

const field = (template: string, template_name: string, field_id: string, label: string, over: Partial<NoteField> = {}): NoteField => ({
  field_id, template, template_name, template_id: `mfrs-company-${template.toLowerCase()}-v1`, label, path: [], heading: false, mandatory: false, catch_all: false, ...over,
});

export const noteFields: NoteField[] = [
  field("CORP_INFO", "Corporate information", "f-corp", "Corporate information", { mandatory: true }),
  field("ACC_POLICIES", "Accounting policies", "h-pol", "Significant accounting policies", { heading: true }),
  field("ACC_POLICIES", "Accounting policies", "f-basis", "Basis of preparation", { path: ["Significant accounting policies"] }),
  field("ACC_POLICIES", "Accounting policies", "f-jud", "Significant accounting judgements and estimates", { path: ["Significant accounting policies"], mandatory: true }),
  field("LIST_OF_NOTES", "List of notes", "f-rev", "Disclosure of revenue"),
  field("LIST_OF_NOTES", "List of notes", "f-tr", "Disclosure of trade and other receivables"),
  field("LIST_OF_NOTES", "List of notes", "f-bor", "Disclosure of borrowings"),
  field("LIST_OF_NOTES", "List of notes", "f-fi", "Disclosure of financial instruments"),
  field("LIST_OF_NOTES", "List of notes", "f-other", "Disclosure of other notes", { catch_all: true }),
  field("ISSUED_CAPITAL", "Issued capital", "f-cap", "Disclosure of issued capital"),
  field("RELATED_PARTY", "Related parties", "f-rpt", "Related party transactions"),
  field("RELATED_PARTY", "Related parties", "f-kmp", "Key management personnel compensation"),
];

const placed = (id: string) => {
  const f = noteFields.find((x) => x.field_id === id)!;
  return { template_id: f.template_id, field: { node_uuid: f.field_id, label: f.label } };
};

// Notes ------------------------------------------------------------------------

const base = (over: Partial<Note> & Pick<Note, "id" | "number" | "title" | "pages" | "blocks">): Note => ({
  template_id: null, field: null, part: 1, parts: 1, position: 0,
  format_state: "fine", format_reason: "", has_unsure: false, certainty: "sure", certainty_reason: "",
  confirmed_by: null, confirmed_at: null, revision: 1, updated_by: "notes agent", updated_at: "2026-11-23T09:00:00Z",
  fit: { tier: "full", chars: 1800, limit: 32767 }, figures: null, ...over,
});

let nextFigure = 900;

const figureRow = (label: string, printed: string, concept: string, cy: number | null, py: number | null, over: Partial<StatementRow> = {}): StatementRow => ({
  kind: "line", label, field_label: label, printed_label: printed, concept_uuid: concept, sheet: "Notes", row: 1, page: 25, print_order: 1, status: null, certainty: "sure", reason: "", edited: false,
  cells: Object.fromEntries(
    ([["Company:CY", cy], ["Company:PY", py]] as const).map(([key, value]) => [
      key,
      { figure_id: value === null ? null : nextFigure++, concept_uuid: concept, value, printed: value, stated: null, certainty: "sure", reason: "", edited: false, origin: value === null ? null : "agent", writable: true, agent_writable: true, lines_sum: null },
    ]),
  ),
  ...over,
});

const columns = [
  { key: "Company:CY", label: "2025", entity_scope: "Company" as const, period: "CY" as const, matrix_col: null },
  { key: "Company:PY", label: "2024", entity_scope: "Company" as const, period: "PY" as const, matrix_col: null },
];

export const capitalFigures: NoteFigures = {
  columns,
  unsure: 0,
  rows: [
    figureRow("Ordinary shares", "Ordinary shares", "h-ord", null, null, { kind: "heading" }),
    figureRow("Number of shares issued", "Number of shares at 31 December", "num", 2000000, 2000000),
    figureRow("Issued capital", "RM at 31 December", "amt", 2000000, 2000000),
  ],
};

const unsureAdvance = figureRow("Amounts due from directors", "Advance to a director", "adv", 42000, null, { certainty: "unsure", reason: "Page 30 does not say whether the advance is a loan or a trade balance." });
unsureAdvance.cells["Company:CY"] = { ...unsureAdvance.cells["Company:CY"], certainty: "unsure", reason: "Page 30 does not say whether the advance is a loan or a trade balance. Filed under amounts due from directors." };

export const relatedFigures: NoteFigures = {
  columns,
  unsure: 1,
  rows: [figureRow("Directors", "Directors", "h-dir", null, null, { kind: "heading" }), figureRow("Rental expense, directors", "Rental paid to a director", "rent", 96000, 96000), unsureAdvance],
};

export const corp = base({
  id: 1, number: "1", title: "Corporate information", pages: [12], ...placed("f-corp"),
  blocks: [
    heading(12, 0, "1. Corporate information"),
    paragraph(12, 1, "The Company is a private limited liability company, incorporated and domiciled in Malaysia. The principal activity of the Company is the trading of industrial hardware and building materials."),
    paragraph(12, 2, "The registered office and principal place of business is located at Lot 14, Jalan Perusahaan 3, 43000 Kajang, Selangor."),
  ],
});

export const revenue = base({
  id: 2, number: "17", title: "Revenue", pages: [27], ...placed("f-rev"), format_state: "not_sure", has_unsure: true,
  format_reason: "The scan is faint on page 27, so the line above the total is drawn as a single line.",
  blocks: [
    heading(27, 0, "17. Revenue"),
    paragraph(27, 1, "Revenue is recognised at a point in time when control of the goods passes to the customer.", { unsure: ["align"] }),
    table(27, 2, ["", "2025", "2024"], [
      { cells: ["Sale of hardware", "11,930,400", "10,412,900"] },
      { cells: ["Sale of building materials", "6,711,900", "5,792,900"], line: AMOUNT_LINE(3), unsure: ["line_below"] },
      { cells: ["", "18,642,300", "16,205,800"], role: "total", line: AMOUNT_LINE(3, "double") },
    ]),
  ],
});

export const receivables = base({
  id: 3, number: "9", title: "Trade receivables", pages: [24], ...placed("f-tr"), position: 0,
  blocks: [
    heading(24, 0, "9. Trade receivables"),
    paragraph(24, 1, "The normal credit terms granted to customers range from 30 to 90 days. The ageing of trade receivables at the end of the year is as follows:"),
    table(24, 2, ["", "2025", "2024"], [
      { cells: ["Not past due", "1,684,200", "1,512,800"] },
      { cells: ["1 to 30 days past due", "402,900", "355,100"] },
      { cells: ["31 to 60 days past due", "186,300", "149,600"] },
    ]),
  ],
});

export const borrowings = base({
  id: 4, number: "14", title: "Borrowings", pages: [26], ...placed("f-bor"), fit: { tier: "lite", chars: 31940, limit: 32767 },
  blocks: [
    heading(26, 0, "14. Borrowings"),
    paragraph(26, 1, "The term loan is secured by a legal charge over the buildings of the Company and bears interest at 4.65% (2024: 4.80%) a year."),
    table(26, 2, ["", "2025", "2024"], [
      { cells: ["Secured", "", ""], role: "subtotal" },
      { cells: ["Term loan", "1,870,000", "1,910,000"] },
      { cells: ["Non-current", "1,450,000", "1,680,000"], indent: 1 },
      { cells: ["Current", "420,000", "230,000"], indent: 1, line: AMOUNT_LINE(3) },
      { cells: ["", "1,870,000", "1,910,000"], role: "total", line: AMOUNT_LINE(3, "double") },
    ]),
  ],
});

export const instruments = base({
  id: 5, number: "20", title: "Financial instruments", pages: [28, 29], ...placed("f-fi"), fit: { tier: "too_long", chars: 38412, limit: 32767 },
  blocks: [
    heading(28, 0, "20. Financial instruments"),
    paragraph(28, 1, "The table below analyses the financial instruments in the statement of financial position by the class of financial instrument to which they are assigned."),
    table(28, 2, ["", "Carrying amount", "Amortised cost"], [
      { cells: ["Trade receivables", "2,385,600", "2,385,600"] },
      { cells: ["Cash and bank balances", "1,264,900", "1,264,900"] },
    ]),
    paragraph(29, 0, "The maturity analysis, the credit risk tables and the sensitivity analysis continue for six pages, to page 33."),
  ],
});

export const contingent = base({
  id: 6, number: "24", title: "Contingent liabilities", pages: [31], fit: null,
  blocks: [heading(31, 0, "24. Contingent liabilities"), paragraph(31, 1, "The Company has given a bank guarantee of RM150,000 to a utility provider. The directors are of the opinion that no loss is expected to arise.")],
});

export const capital = base({
  id: 7, number: "12", title: "Share capital", pages: [25], ...placed("f-cap"), figures: capitalFigures,
  blocks: [
    heading(25, 0, "12. Share capital"),
    table(25, 1, ["", "Number of shares", "RM"], [
      { cells: ["Ordinary shares, issued and fully paid", "", ""], role: "subtotal" },
      { cells: ["At 1 January and 31 December", "2,000,000", "2,000,000"], role: "total", line: AMOUNT_LINE(3, "double") },
    ]),
  ],
});

export const related1 = base({
  id: 8, number: "22", title: "Related parties", pages: [30], ...placed("f-rpt"), part: 1, parts: 2, figures: relatedFigures,
  blocks: [
    heading(30, 0, "22. Related parties"),
    paragraph(30, 1, "(a) Significant transactions with directors during the year were as follows:"),
    table(30, 2, ["", "2025", "2024"], [{ cells: ["Rental paid to a director", "96,000", "96,000"] }, { cells: ["Advance to a director", "42,000", "-"] }]),
  ],
});

export const related2 = base({
  id: 9, number: "22", title: "Related parties", pages: [30], ...placed("f-kmp"), part: 2, parts: 2,
  blocks: [
    heading(30, 3, "(b) Compensation of key management personnel", 2),
    table(30, 4, ["", "2025", "2024"], [
      { cells: ["Salaries and other emoluments", "480,000", "452,000"] },
      { cells: ["Contributions to EPF", "57,600", "54,240"], line: AMOUNT_LINE(3) },
      { cells: ["", "537,600", "506,240"], role: "total", line: AMOUNT_LINE(3, "double") },
    ]),
  ],
});

export const allNotes: Note[] = [corp, revenue, receivables, borrowings, instruments, contingent, capital, related1, related2];

export const summary = (n: Note): NoteSummary => {
  const { blocks: _blocks, figures: _figures, ...rest } = n;
  return rest;
};

export const noteReports: NoteReport[] = [
  {
    id: 31, kind: "source_gap", note_id: 3, node_uuid: null, field_label: null, template_id: null, pages: [24], after_block: "p24b2", status: "open", settled_by: null,
    reason: "Page 24 ends inside the ageing table and page 25 starts with note 10, so the last rows and the total are not in the PDF.",
  },
  {
    id: 32, kind: "missing_mandatory_field", note_id: null, node_uuid: "f-jud", field_label: "Significant accounting judgements and estimates", template_id: noteFields[3].template_id, pages: [13],
    after_block: null, status: "open", settled_by: null,
    reason: "This field is mandatory in the MFRS template. Notes 1 to 24 have no section on judgements or estimates, and note 2 ends at page 20 without one.",
  },
];

// The review text ----------------------------------------------------------------

const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * A small stand-in for the server's review text (app/notes/render): the
 * prepared HTML of one note with its marks. Set looks and the house style
 * are drawn inline as the server draws them; the flat tier draws no style.
 */
export function reviewOf(n: Note, { double = "thick_bottom_border", tier = "full" }: { double?: NoteReview["double_underline"]; tier?: NoteReview["tier"] } = {}): NoteReview {
  const plain = tier === "flat" || tier === "too_long";
  const st = (parts: string[]) => (plain || !parts.length ? "" : ` style="${parts.join("; ")}"`);
  const mark = (i: number) => ` data-note="${n.id}" data-block="${i}"`;
  const strong = (t: string, bold: boolean) => (bold ? `<strong>${esc(t)}</strong>` : esc(t));
  const html = n.blocks.map((b, i) => {
    if (b.kind === "heading") return `<h3${mark(i)}${st(["font-weight: 600"])}>${esc(b.text)}</h3>`;
    if (b.kind === "paragraph") return `<p${mark(i)}${st(["margin: 0 0 3px 0"])}>${strong(b.text, b.look.bold)}</p>`;
    if (b.kind === "list") return `<ul${mark(i)}>${b.items.map((it) => `<li>${esc(it.text)}</li>`).join("")}</ul>`;
    const rows = b.rows.map((row, r) => {
      const cells = row.cells.map((cell, c) => {
        const parts: string[] = [];
        const line = row.line_below;
        if (line && (!line.columns.length || line.columns.includes(c))) {
          parts.push(`border-bottom: ${line.style === "double" && double === "thick_bottom_border" ? "2.5px" : "0.75px"} solid #000000`);
        }
        return `<td data-row="${r}" data-col="${c}"${st(parts)}>${strong(cell.text, row.bold || cell.look.bold)}</td>`;
      });
      return `<tr>${cells.join("")}</tr>`;
    });
    return `<table${mark(i)}><tbody>${rows.join("")}</tbody></table>`;
  });
  const body = plain ? html.join("") : `<div style="font-family: Arial, sans-serif; font-size: 10pt; text-align: justify;">${html.join("")}</div>`;
  return { note_id: n.id, node_uuid: n.field?.node_uuid ?? null, revision: `r${n.revision}`, tier, html: body, double_underline: double };
}
