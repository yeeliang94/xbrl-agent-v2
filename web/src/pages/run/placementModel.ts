// The placement map (prototypes/notes-placement-prototype-v2.html): where every note sits, which ones need a
// look and which field reads closest. Free and instant: words are matched in the browser, no model is called.
// No React here.
import type { NoteField, NoteSummary } from "../../api";

/** A note field as the map shows it: its name without mTool's repeated opening words. */
export interface PlaceField {
  id: string;
  label: string;
  short: string;
  template: string;
  templateId: string;
  templateName: string;
  depth: number;
  heading: boolean;
  mandatory: boolean;
  catchAll: boolean;
  words: string[];
  /** Everyday words a report uses for this field ("debtors" for trade receivables). */
  alsoWords: string[];
}

export const POLICIES = "ACC_POLICIES";

export function shortName(label: string): string {
  const s = label
    .replace(/^\*/, "")
    .replace(/^Disclosure of /i, "")
    .replace(/^Description of accounting policy for /i, "")
    .replace(
      /^Description of other material accounting policies.*/i,
      "Other material accounting policies",
    )
    .replace(/^Description of /i, "")
    .replace(/^Explanation of reasons for /i, "Reasons for ");
  return s ? s[0].toUpperCase() + s.slice(1) : label;
}

const STOP = new Set(
  "of and the to for in on a an or from under at its by with".split(" "),
);
const stem = (w: string) => w.replace(/ies$/, "y").replace(/([^s])s$/, "$1");
export const words = (s: string) => [
  ...new Set(
    s
      .toLowerCase()
      .replace(/[^a-z\- ]/g, " ")
      .split(/\s+/)
      .filter((w) => w && !STOP.has(w))
      .map(stem),
  ),
];

/**
 * Everyday words reports use for a field, by its short name. A starting list, to be tuned on real reports
 * (owner, 24 November 2026). Without it, "Directors' remuneration" never finds key management personnel.
 */
const ALSO: Record<string, string> = {
  "Cash and cash equivalents": "cash and bank balances fixed deposits",
  Leases: "right-of-use assets lease liabilities hire purchase",
  "Key management personnel compensation": "directors remuneration",
  "Revenue from contract customers": "sales turnover",
  "Revenue from contracts with customers": "sales turnover",
  Borrowings: "term loans overdraft",
  "Trade and other receivables": "debtors",
  "Trade and other payables": "creditors",
  "Income tax expense": "taxation",
  "Events after reporting period": "subsequent events",
  "Transactions between related parties": "related party disclosures",
  "Impairment of other assets": "non-financial assets",
};

export function placeFields(fields: NoteField[]): PlaceField[] {
  return fields.map((f) => {
    const short = shortName(f.label);
    return {
      id: f.field_id,
      label: f.label.replace(/^\*/, ""),
      short,
      template: f.template,
      templateId: f.template_id,
      templateName: f.template_name,
      depth: f.path.length,
      heading: f.heading,
      mandatory: f.mandatory,
      catchAll: f.catch_all,
      words: words(short),
      alsoWords: words(ALSO[short] ?? ""),
    };
  });
}

/** What the note is about: a split part by its own heading, or "Related parties, part 2" when it has none. */
export const noteTitle = (n: NoteSummary) =>
  n.parts < 2 ? n.title : n.part_title || `${n.title}, part ${n.part}`;

/** The words a note is matched by. A split part with no heading of its own has none: its note's title says
 * what the whole note is about, not the part. */
const matchWords = (n: NoteSummary) =>
  n.parts > 1 && !n.part_title ? [] : words(noteTitle(n));

// Each fields list is indexed once, however many notes are matched against it.
const indexes = new WeakMap<PlaceField[], Map<string, PlaceField>>();
function fieldIndex(fields: PlaceField[]) {
  let byId = indexes.get(fields);
  if (!byId)
    indexes.set(fields, (byId = new Map(fields.map((f) => [f.id, f]))));
  return byId;
}

/** How closely a note's words read like the field's name, 0 to 1. Policies match policy fields only. */
function score(t: string[], f: PlaceField, policy: boolean | null): number {
  if (!t.length || f.heading || f.catchAll) return 0;
  if (policy !== null && (f.template === POLICIES) !== policy) return 0;
  const plain =
    t.filter((w) => f.words.includes(w)).length /
    new Set([...t, ...f.words]).size;
  const viaAlso =
    f.alsoWords.length &&
    t.every((w) => f.alsoWords.includes(w) || f.words.includes(w))
      ? 1
      : 0;
  return Math.max(plain, viaAlso);
}

function ranked(
  n: NoteSummary,
  fields: PlaceField[],
  policy: boolean | null,
  k: number,
) {
  const t = matchWords(n);
  return fields
    .map((f) => ({ f, s: score(t, f, policy) }))
    .filter((x) => x.s > 0 && x.f.id !== n.field?.node_uuid)
    .sort((a, b) => b.s - a.s)
    .slice(0, k);
}

/** The fields whose names read closest to the note's title, best first. */
export function suggest(
  n: NoteSummary,
  fields: PlaceField[],
  k = 4,
): PlaceField[] {
  const here = n.field ? fieldIndex(fields).get(n.field.node_uuid) : undefined;
  return ranked(n, fields, here ? here.template === POLICIES : null, k).map(
    (x) => x.f,
  );
}

export type Flag =
  | { kind: "not_placed"; why: string }
  | { kind: "check"; why: string; better?: PlaceField }
  | { kind: "confirmed" }
  | { kind: "placed" };

const NOT_PLACED_WHY =
  "This note is in no field, so it would be left out of the mTool file.";
const UNSURE_WHY =
  "The notes agent was not sure this note belongs in this field.";

/** Whether a note needs a look, and why. A person who confirmed or moved it settled its field. */
export function flagOf(n: NoteSummary, fields: PlaceField[]): Flag {
  if (!n.field) return { kind: "not_placed", why: NOT_PLACED_WHY };
  if (n.confirmed_by) return { kind: "confirmed" };
  const f = fieldIndex(fields).get(n.field.node_uuid);
  if (f) {
    const policy = f.template === POLICIES;
    const t = matchWords(n);
    const best = ranked(n, fields, policy, 1)[0];
    const here = score(t, f, policy);
    if (f.catchAll && best && best.s >= 0.5)
      return {
        kind: "check",
        better: best.f,
        why: `This sits in the catch-all field, but mTool has a field named ${best.f.short}.`,
      };
    if (!f.catchAll && best && best.s >= 0.5 && best.s >= here + 0.25)
      return {
        kind: "check",
        better: best.f,
        why: `The title reads closer to ${best.f.short} than to ${f.short}.`,
      };
    // Issued capital and related-party field names describe what the template holds ("Classes of share capital"),
    // not a note's title, so a title sharing no words with them says nothing.
    const named =
      f.template !== "ISSUED_CAPITAL" && f.template !== "RELATED_PARTY";
    if (
      n.certainty !== "unsure" &&
      !f.catchAll &&
      named &&
      t.length > 0 &&
      here === 0
    )
      return {
        kind: "check",
        why: "The note's title and the field's name share no words.",
      };
  }
  if (n.certainty === "unsure")
    return { kind: "check", why: n.certainty_reason || UNSURE_WHY };
  return { kind: "placed" };
}

/** Every note's flag, worked out once per notes list. */
export const flagsOf = (notes: NoteSummary[], fields: PlaceField[]) =>
  new Map(notes.map((n) => [n.id, flagOf(n, fields)]));

export const needsLook = (f: Flag | undefined) =>
  f?.kind === "not_placed" || f?.kind === "check";

/** Mandatory fields no note fills and no person has left empty. */
export function emptyMandatory(
  fields: PlaceField[],
  notes: NoteSummary[],
  leftEmpty: Set<string>,
): PlaceField[] {
  const used = new Set(notes.map((n) => n.field?.node_uuid));
  return fields.filter(
    (f) => f.mandatory && !f.heading && !used.has(f.id) && !leftEmpty.has(f.id),
  );
}

/** Fields whose name, everyday words or template match what a person typed. */
export function searchFields(
  q: string,
  fields: PlaceField[],
  k = 8,
): PlaceField[] {
  const t = words(q);
  if (!t.length) return [];
  return fields
    .filter((f) => !f.heading)
    .map((f) => {
      const all = [...f.words, ...f.alsoWords, ...words(f.templateName)];
      const hits = t.filter((w) => all.some((a) => a.startsWith(w))).length;
      return {
        f,
        s:
          hits / t.length + (f.words.some((a) => a.startsWith(t[0])) ? 0.1 : 0),
      };
    })
    .filter((x) => x.s >= 1)
    .sort((a, b) => b.s - a.s)
    .slice(0, k)
    .map((x) => x.f);
}

/** Notes in the order the report prints them: by first page, then number, then part. */
const firstPage = (n: NoteSummary) =>
  n.pages.length ? Math.min(...n.pages) : Number.MAX_SAFE_INTEGER;
const byReport = (a: NoteSummary, b: NoteSummary) =>
  firstPage(a) - firstPage(b) ||
  a.number.localeCompare(b.number, undefined, { numeric: true }) ||
  a.part - b.part ||
  a.id - b.id;

export type ReportRow =
  | { kind: "note"; note: NoteSummary }
  | {
      kind: "split";
      key: string;
      number: string;
      title: string;
      parts: NoteSummary[];
    };

/** The report-order list: each whole note, and each split note as one row holding its parts. */
export function reportRows(notes: NoteSummary[]): ReportRow[] {
  const out: ReportRow[] = [];
  const splits = new Map<string, Extract<ReportRow, { kind: "split" }>>();
  for (const n of [...notes].sort(byReport)) {
    if (n.parts < 2) {
      out.push({ kind: "note", note: n });
      continue;
    }
    const key = n.number
      ? `#${n.number.replace(/[^0-9a-z]/gi, "").toLowerCase()}`
      : `|${n.title.toLowerCase()}`;
    let row = splits.get(key);
    if (!row) {
      row = { kind: "split", key, number: n.number, title: n.title, parts: [] };
      splits.set(key, row);
      out.push(row);
    }
    row.parts.push(n);
  }
  return out;
}

export interface TemplateSection {
  templateId: string;
  name: string;
  used: number;
  total: number;
  /** Each field shown, with the notes in it in their order. */
  rows: { field: PlaceField; notes: NoteSummary[] }[];
}

/** mTool order: each template's fields in mTool's order. Empty fields show only when asked, or when mTool needs them. */
export function templateSections(
  fields: PlaceField[],
  notes: NoteSummary[],
  showEmpty: boolean,
): TemplateSection[] {
  const inField = new Map<string, NoteSummary[]>();
  for (const n of notes)
    if (n.field)
      inField.set(n.field.node_uuid, [
        ...(inField.get(n.field.node_uuid) ?? []),
        n,
      ]);
  const out: TemplateSection[] = [];
  for (const f of fields) {
    let section = out[out.length - 1];
    if (!section || section.templateId !== f.templateId) {
      section = {
        templateId: f.templateId,
        name: f.templateName,
        used: 0,
        total: 0,
        rows: [],
      };
      out.push(section);
    }
    if (f.heading) continue;
    const here = (inField.get(f.id) ?? []).sort(
      (a, b) => a.position - b.position || a.id - b.id,
    );
    section.total += 1;
    if (here.length) section.used += 1;
    if (here.length || f.mandatory || showEmpty)
      section.rows.push({ field: f, notes: here });
  }
  return out;
}
