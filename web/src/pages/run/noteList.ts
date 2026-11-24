// The notes in the left list: grouped by template, with what each still
// needs from a person. No React here.
import type { Comment, NoteField, NoteReport, NoteSummary, SizeTier } from "../../api";
import type { SelectOption } from "../../components/Select";
import { isLive } from "./runModel";

export const NOT_PLACED = "";

/** "Related parties, part 1" for a note split across fields. */
export const noteName = (n: NoteSummary) => (n.parts > 1 ? `${n.title}, part ${n.part}` : n.title);

export const REDUCED_TIER: Partial<Record<SizeTier, string>> = { compact: "Compact styling", lite: "Lite styling", flat: "No styling" };
export const TIER_WHY: Partial<Record<SizeTier, string>> = {
  compact: "Kept the look with slimmer styling so the field fits mTool.",
  lite: "Dropped alignment and wrapping hints so the field fits mTool.",
  flat: "Dropped all styling so the field fits mTool.",
};

export interface NoteFlags {
  tooLong: boolean;
  /** A smaller styling tier, so the field fits mTool. */
  tier: string | null;
  check: boolean;
  /** The notes agent was not sure the note belongs in its field. Confirm makes the placement sure. */
  placement: boolean;
  gaps: NoteReport[];
  notPlaced: boolean;
}

export function noteFlags(n: NoteSummary, reports: NoteReport[]): NoteFlags {
  const tier = n.fit?.tier ?? "full";
  return {
    tooLong: tier === "too_long",
    tier: REDUCED_TIER[tier] ?? null,
    check: n.format_state !== "fine",
    placement: !!n.field && n.certainty === "unsure",
    gaps: reports.filter((r) => r.kind === "source_gap" && r.note_id === n.id && r.status === "open"),
    notPlaced: !n.field,
  };
}

const noteComments = (comments: Comment[], id: number) => comments.filter((c) => isLive(c) && c.author_kind === "person" && c.target.kind === "note" && c.target.note_id === id);

/** What waits for a person on a note: its labels and its open comments. */
export function noteCount(n: NoteSummary, reports: NoteReport[], comments: Comment[]): number {
  const f = noteFlags(n, reports);
  return Number(f.tooLong) + Number(f.check) + Number(f.placement) + f.gaps.length + Number(f.notPlaced) + noteComments(comments, n.id).length;
}

/** A list entry. A part of a split note carries its title and part apart, so a narrow list still tells the parts apart. */
export type NoteItem = { kind: "note"; id: number; name: string; count: number; split?: { title: string; part: number } } | { kind: "missing"; id: number; name: string; count: number };

const noteItem = (n: NoteSummary, reports: NoteReport[], comments: Comment[]): NoteItem => ({
  kind: "note",
  id: n.id,
  name: noteName(n),
  count: noteCount(n, reports, comments),
  ...(n.parts > 1 ? { split: { title: n.title, part: n.part } } : {}),
});

export interface NoteGroup {
  templateId: string;
  name: string;
  items: NoteItem[];
  count: number;
}

/** A missing mandatory field counts until a note fills it or a person leaves it empty. */
export const fieldFilled = (notes: NoteSummary[], nodeUuid: string | null) => notes.some((n) => n.field?.node_uuid === nodeUuid);

/** The notes list: each template of the run in order, its notes and missing fields; not placed notes last. */
export function noteGroups(fields: NoteField[], notes: NoteSummary[], reports: NoteReport[], comments: Comment[]): NoteGroup[] {
  const templates = new Map<string, string>();
  for (const f of fields) if (!templates.has(f.template_id)) templates.set(f.template_id, f.template_name);
  for (const n of notes) if (n.template_id && !templates.has(n.template_id)) templates.set(n.template_id, n.template_id);
  const groups: NoteGroup[] = [];
  const add = (templateId: string, name: string, items: NoteItem[]) => groups.push({ templateId, name, items, count: items.reduce((a, i) => a + i.count, 0) });
  for (const [templateId, name] of templates) {
    const items: NoteItem[] = notes
      .filter((n) => n.template_id === templateId && n.field)
      .map((n) => noteItem(n, reports, comments));
    for (const r of reports) {
      if (r.kind !== "missing_mandatory_field" || r.template_id !== templateId || fieldFilled(notes, r.node_uuid)) continue;
      items.push({ kind: "missing", id: r.id, name: r.field_label ?? "Missing field", count: r.status === "open" ? 1 : 0 });
    }
    add(templateId, name, items);
  }
  const loose = notes.filter((n) => !n.field);
  if (loose.length) add(NOT_PLACED, "Not placed", loose.map((n) => noteItem(n, reports, comments)));
  return groups;
}

/** The other parts of a note split across fields, in part order, itself included. */
export function noteParts(notes: NoteSummary[], n: NoteSummary): NoteSummary[] {
  if (n.parts < 2) return [];
  return notes.filter((x) => x.number === n.number && x.title === n.title && x.parts === n.parts).sort((a, b) => a.part - b.part);
}

/**
 * The field dropdown: "Not placed", then each template's fields under its
 * name. Headings are shown, greyed, so each field reads under its headings.
 */
export function fieldOptions(fields: NoteField[], current: { node_uuid: string; label: string } | null): SelectOption[] {
  const out: SelectOption[] = [{ value: NOT_PLACED, label: "Not placed" }];
  let template = "";
  for (const f of fields) {
    if (f.template_id !== template) {
      template = f.template_id;
      out.push({ value: `template:${f.template_id}`, label: f.template_name, disabled: true });
    }
    const pad = "  ".repeat(f.path.length + 1);
    out.push({ value: f.heading ? `heading:${f.field_id}` : f.field_id, label: `${pad}${f.label}`, disabled: f.heading });
  }
  if (current && !fields.some((f) => f.field_id === current.node_uuid)) out.splice(1, 0, { value: current.node_uuid, label: current.label });
  return out;
}
