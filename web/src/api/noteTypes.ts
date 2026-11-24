// Step 6: a run's notes, in the shapes of docs/api-contract.md "Step 6b"
// and "Step 6e".
import type { StatementColumn, StatementRow } from "./types";

export type Align = "left" | "center" | "right" | "justify";
export type VAlign = "top" | "middle" | "bottom";

export interface TextLook {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  align: Align | null;
  /** Steps of 2em, 0 to 4. */
  indent: number;
  /** Look keys the agent could not tell from the page. */
  unsure: string[];
}

export interface CellLook {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  align: Align | null;
  valign: VAlign | null;
  unsure: string[];
}

export interface BlockSource {
  page: number;
  block: number;
}

export interface HeadingBlock {
  kind: "heading";
  id: string;
  source: BlockSource;
  level: number;
  text: string;
  look: TextLook;
}

export interface ParagraphBlock {
  kind: "paragraph";
  id: string;
  source: BlockSource;
  text: string;
  look: TextLook;
}

export interface ListBlock {
  kind: "list";
  id: string;
  source: BlockSource;
  items: { text: string; level: number }[];
  look: TextLook;
}

export interface Line {
  style: "single" | "double";
  /** 0-based columns; empty means every column. */
  columns: number[];
}

export interface TableCell {
  text: string;
  look: CellLook;
}

export interface TableRow {
  role: "heading" | "item" | "subtotal" | "total";
  cells: TableCell[];
  indent: number;
  bold: boolean;
  shaded: boolean;
  line_below: Line | null;
  unsure: string[];
}

export interface TableColumn {
  role: "label" | "amount" | "text" | "date";
  width: number | null;
  align: Align | null;
  unsure: string[];
}

export interface TableBlock {
  kind: "table";
  id: string;
  source: BlockSource;
  columns: TableColumn[];
  rows: TableRow[];
  frame: "none" | "grid";
  font_pt: number | null;
  unsure: string[];
}

export type NoteBlock = HeadingBlock | ParagraphBlock | ListBlock | TableBlock;

export type FormatState = "fine" | "check_formatting" | "not_sure";
export type SizeTier = "full" | "compact" | "lite" | "flat" | "too_long";

/** The field's prepared text measured against mTool's limit (the renderer's `Prepared`). */
export interface NoteFit {
  tier: SizeTier;
  chars: number;
  limit: number;
}

/** The figures of a numeric note (issued capital, related parties), from the figure store. */
export interface NoteFigures {
  columns: StatementColumn[];
  rows: StatementRow[];
  /** How many of them are marked Unsure. */
  unsure: number;
}

export interface NoteSummary {
  id: number;
  number: string;
  title: string;
  pages: number[];
  template_id: string | null;
  field: { node_uuid: string; label: string } | null;
  part: number;
  parts: number;
  /** A split part's own first heading, without its numbering; empty for a whole note. */
  part_title?: string;
  position: number;
  format_state: FormatState;
  format_reason: string;
  has_unsure: boolean;
  certainty: "sure" | "unsure";
  certainty_reason: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  revision: number;
  updated_by: string | null;
  updated_at: string;
  /** Null when the note is not placed. */
  fit?: NoteFit | null;
}

export interface Note extends NoteSummary {
  blocks: NoteBlock[];
  /** Present only on a numeric note. */
  figures?: NoteFigures | null;
}

export interface NoteHistoryEntry {
  id: number;
  action: "place" | "look" | "move" | "clear" | "confirm" | "redo" | "restore";
  actor_kind: "agent" | "person";
  actor_name: string;
  changed_at: string;
  round_id: number | null;
  comment_ids: number[];
  reason: string;
  before: unknown;
  after: unknown;
}

/** One template field a note can go in (app/catalog/note_fields.py, as JSON). */
export interface NoteField {
  field_id: string;
  template: string;
  template_name: string;
  template_id: string;
  label: string;
  path: string[];
  heading: boolean;
  mandatory: boolean;
  catch_all: boolean;
}

/** What the notes agent reported (the `note_reports` table). */
export interface NoteReport {
  id: number;
  kind: "source_gap" | "missing_mandatory_field" | "routed_elsewhere";
  note_id: number | null;
  /** The field, for a missing mandatory field. */
  node_uuid: string | null;
  field_label: string | null;
  template_id: string | null;
  pages: number[];
  reason: string;
  /** A source gap falls after this block of its note. */
  after_block: string | null;
  /** Open, or settled by a person (Confirm on a gap, Leave empty on a missing field). */
  status: "open" | "settled";
  settled_by: string | null;
  note_number?: string;
  settled_at?: string | null;
  created_at?: string;
}

/** The field's prepared text for Copy, the same text mTool gets. */
export interface PreparedNote {
  node_uuid: string;
  revision: string;
  html: string;
  tier: SizeTier;
  chars: number;
  limit: number;
}

/**
 * The text the review page draws: the field's prepared text, the same as Copy and mTool get, with
 * `data-note` and `data-block` on each block and `data-row` and `data-col` on each table cell. A note
 * not placed is drawn alone through the same renderer.
 */
export interface NoteReview {
  note_id: number;
  node_uuid: string | null;
  /** The revision of the prepared text, the same as `PreparedNote.revision`. */
  revision: string;
  tier: SizeTier;
  html: string;
  /** How the Settings house style draws a double underline. */
  double_underline: "thick_bottom_border" | "single_bottom_border";
}

export type NotePartScope = "block" | "cell" | "row" | "column" | "table";

/** A comment on part of a note (`comments.note_part`). Rows and columns are 0-based. */
export interface NotePart {
  block: string;
  scope: NotePartScope;
  row: number | null;
  column: number | null;
}
