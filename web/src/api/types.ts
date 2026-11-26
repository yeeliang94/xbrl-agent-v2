// Shapes from docs/api-contract.md.
import type { NotePart } from "./noteTypes";

export interface User {
  email: string;
  name: string;
  is_admin: boolean;
  must_change_password: boolean;
}

export type Standard = "MFRS" | "MPERS";
export type Level = "Company" | "Group";
export type RunStatus =
  | "reading"
  | "setup"
  | "ready"
  | "extracting"
  | "needs_answer"
  | "in_review"
  | "correcting"
  | "filed"
  | "failed"
  | "stopped";

export interface Run {
  id: number;
  /** Null until setup is confirmed; the list then shows the file name. */
  company: string | null;
  year: number | null;
  standard: Standard | null;
  level: Level | null;
  status: RunStatus;
  updated_at: string;
  owner_name: string;
  owner_email: string;
  filename: string | null;
  /** Which stage failed, when the status is "failed"; "read" when the status is "stopped" because reading was stopped. */
  failed_stage?: "read" | "extract" | null;
}

/** The run list's search, filters and page (docs/api-contract.md, "Run list: search, filters, paging and delete"). */
export interface RunQuery {
  q?: string;
  /** One status, or "working" for reading, extracting and correcting. */
  status?: RunStatus | "working" | "";
  standard?: Standard | "";
  /** An ISO time: runs updated at or after it. */
  updated_since?: string;
  mine?: boolean;
  page?: number;
}

export interface RunList {
  runs: Run[];
  total: number;
  page: number;
  per_page: number;
}

/** What deleting a run would remove, and whether this person may delete it now. */
export interface RunDeletion {
  allowed: boolean;
  refused: { code: "owner" | "working"; detail: string } | null;
  figures: number;
  notes: number;
  filled_workbook: boolean;
}

export type ModelRole = "reading" | "extraction" | "review";

export interface HouseStyle {
  body_text: "justified" | "left";
  table_font_pt: 9 | 10 | 11;
  smallest_table_font_pt: 8 | 9;
  double_underline: "thick_bottom_border" | "single_bottom_border";
  bold_totals: boolean;
}

export interface LoginLimits {
  idle_timeout_minutes: number;
  max_attempts: number;
  lockout_minutes: number;
}

export interface Settings {
  route: "direct" | "gateway";
  models: Record<ModelRole, string>;
  code_workbench: boolean;
  claude_sandbox_real_documents: boolean;
  house_style: HouseStyle;
  login: LoginLimits;
}

/** Any subset of the fields an admin can change. */
export type SettingsChange = Partial<Omit<Settings, "route" | "models" | "house_style" | "login">> & {
  models?: Partial<Settings["models"]>;
  house_style?: Partial<HouseStyle>;
  login?: Partial<LoginLimits>;
};

export interface Model {
  id: string;
  provider: "openai" | "anthropic";
  family: "luna" | "terra" | "claude" | "other";
  label: string;
  available: boolean;
}

// Step 3: the document, reading and setup.

export interface DocumentPage {
  page: number;
  width: number;
  height: number;
  rotation: number;
  has_text_layer: boolean;
}

/** What a run started from. A Word or Excel run's pages are a reading copy the server laid out. */
export type SourceKind = "pdf" | "word" | "excel";

/** One sheet of an Excel run's workbook. `used`: laid out in the reading copy, on these pages. */
export interface WorkbookSheet {
  name: string;
  hidden: boolean;
  used: boolean;
  first_page: number | null;
  last_page: number | null;
  rows: number;
  empty_formulas: number;
  /** What to tell the person when formulas were saved without a result, or null. */
  notice: string | null;
}

/** A sheet's filled cells, as the review and setup screens draw them. */
export interface SheetGrid {
  name: string;
  position: number;
  count: number;
  columns: string[];
  first_page: number;
  last_page: number;
  /** Pictures placed on the sheet: drawn only on its reading-copy pages, not among its cells. */
  pictures: number;
  rows: { row: number; cells: Record<string, string> }[];
}

export interface RunDocument {
  filename: string;
  /** Absent on a document made before runs could start from Word or Excel: a PDF. */
  kind?: SourceKind;
  /** Excel runs only. */
  sheets?: WorkbookSheet[];
  sha256: string;
  size_bytes: number;
  page_count: number;
  scanned_pages: number;
  uploaded_by: string;
  uploaded_at: string;
  pages: DocumentPage[];
}

export type StageStatus = "waiting" | "working" | "done" | "failed" | "stopped";

export interface ReadProgress {
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  pages: { total: number; read: number; blank: number; failed: number; waiting: number };
  map_saved: boolean;
  /** A person asked the reading to stop; it stops once the calls under way finish. */
  stop_requested?: boolean;
}

export interface RunEvent {
  id: number;
  job_id: number | null;
  source: string;
  kind: string;
  message: string;
  created_at: string;
  has_data: boolean;
  /** The PDF pages the step concerns, in order, or empty. */
  pages?: number[];
  /** The scope question an asked, answered or setup_changed event is about. */
  question_id?: number | null;
  /** The agent that wrote the row when several run side by side, such as "Placing the notes", else null. */
  agent?: string | null;
}

export interface EventPage {
  events: RunEvent[];
  last_id: number;
  has_more: boolean;
}

export interface Finding {
  value: string | null;
  pages: number[];
  reason: string;
  unsure: boolean;
}

export type StatementCode = "SOFP" | "SOPL" | "SOCI" | "SOCF" | "SOCIE";

/** Where a comment or a Needs you item is filed: a statement, or "NOTES" for the notes as a whole. */
export type PlaceStatement = StatementCode | "NOTES";

export interface MapNote {
  number: string;
  title: string;
  first_page: number;
  last_page: number;
}

export interface DocumentMap {
  saved_at: string;
  notes: MapNote[];
  note_gaps: { note: string; reason: string }[];
  open_points: string[];
}

/** One layout a person may choose, with its label, as the server names it. */
export interface LayoutChoice {
  value: string;
  label: string;
}

export interface SuggestedStatement {
  statement: StatementCode;
  found: boolean;
  pages: number[];
  layout: string | null;
  /** The choices under each standard. */
  layouts: Record<Standard, LayoutChoice[]>;
  reason: string;
  unsure: boolean;
}

export interface SuggestedSetup {
  company: Finding;
  year_end: Finding;
  year: number | null;
  standard: Finding;
  level: Finding;
  unit: Finding;
  statements: SuggestedStatement[];
  /** One card for each unsure suggestion of the standard, the level, the unit or a layout. */
  questions?: SetupQuestion[];
  /** Value "yes" when the Reader found no figures for last year; null for a map read before it looked. */
  first_statements?: Finding | null;
}

/** As printed: RM, RM thousands or RM millions. Figures are never rescaled. */
export type Unit = "RM" | "RM'000" | "RM'000,000";

export interface ConfirmedSetup {
  company: string;
  year_end: string;
  standard: Standard;
  level: Level;
  unit: Unit;
  statements: { statement: StatementCode; layout: string; included: boolean; pages: number[] }[];
  notes_included: boolean;
  notes: MapNote[];
  /** True for "This year only": the company's first financial statements, with no prior year. */
  first_statements: boolean;
}

// Step 1 and step 5a: statements, figures, checks, comments, rounds, Needs you.

export type Period = "CY" | "PY";
export type EntityScope = "Company" | "Group";

export interface StatementColumn {
  key: string;
  label: string;
  entity_scope: EntityScope | null;
  period: Period | null;
  matrix_col: string | null;
}

export interface Cell {
  figure_id: number | null;
  concept_uuid: string;
  value: number | null;
  printed: number | null;
  stated: number | null;
  certainty: "sure" | "unsure";
  reason: string;
  edited: boolean;
  origin: string | null;
  writable: boolean;
  agent_writable: boolean;
  lines_sum: number | null;
  /** A last-year figure kept from the starting workbook whose report comparative differs only in sign. */
  sign_question?: boolean;
  /** The report's comparative for a kept last-year figure, as the agent read it (step 10e). */
  comparison?: { report_value: number; page: number | null; open: boolean } | null;
  /** Excel runs: the cell this figure comes from on the row's sheet, e.g. "B12". */
  source_cell?: string;
}

export type RowStatus = "does_not_tally" | "differs_from_report" | "unsure" | "edited";

export interface StatementRow {
  kind: "heading" | "line" | "total";
  label: string;
  field_label: string;
  printed_label: string | null;
  concept_uuid: string;
  sheet: string;
  row: number;
  page: number | null;
  print_order: number | null;
  cells: Record<string, Cell>;
  status: RowStatus | null;
  certainty: "sure" | "unsure";
  reason: string;
  edited: boolean;
  entity_scope?: EntityScope | null;
  period?: Period | null;
  /** Excel runs: the sheet the line is on, and its row when it could be told. */
  source?: { sheet: string; row: number | null };
}

export interface Statement {
  run_id: number;
  statement: StatementCode;
  variant: string;
  template_id: string;
  order: "report" | "template";
  columns: StatementColumn[];
  rows: StatementRow[];
  /** What the run started from. Absent on an older server: a PDF. */
  source_kind?: SourceKind;
}

export interface Figure {
  id: number;
  concept_uuid: string;
  period: Period;
  entity_scope: EntityScope;
  dimension_key: string;
  value: number | null;
  certainty: "sure" | "unsure";
  reason: string;
  person_edited: boolean;
}

export interface FigureEdit {
  concept_uuid: string;
  period: Period;
  entity_scope: EntityScope;
  value: number | null;
  page?: number;
  printed_label?: string;
}

export type CheckStatus = "passed" | "failed" | "warning" | "not_applicable" | "not_assessed";

export interface Check {
  name: string;
  title: string;
  entity_scope: EntityScope;
  status: CheckStatus;
  period: Period | null;
  message: string;
  comparands: { label: string; statement: string; period: Period | null }[];
  target_concept_uuid: string | null;
}

export type CommentScope = "figure" | "run" | "company";

export type CommentTarget =
  | { kind: "figure"; figure_id: number }
  | { kind: "figure"; statement: StatementCode; concept_uuid: string; period: Period; entity_scope: EntityScope; dimension_key?: string }
  | { kind: "line"; statement: StatementCode; concept_uuid: string; entity_scope: EntityScope }
  | { kind: "statement"; statement: StatementCode }
  /** The notes as a whole, or one of the notes agent's reports (a missing field) by `report_id`. */
  | { kind: "statement"; statement: "NOTES"; report_id?: number }
  /** A whole note when `note_part` is null, or one block, cell, row, column or table of it (step 6e). */
  | { kind: "note"; note_id: number; note_part: NotePart | null };

export interface NewComment {
  target: CommentTarget;
  text: string;
  scope?: CommentScope;
}

export type CommentStatus = "open" | "sent" | "answered" | "accepted" | "undone" | "done";
export type Outcome = "changed" | "not_changed" | "question";

export interface Comment {
  id: number;
  run_id: number;
  author_kind: "person" | "agent";
  author_name: string;
  target: {
    kind: "figure" | "line" | "statement" | "note";
    statement: PlaceStatement | null;
    concept_uuid: string | null;
    period: Period | null;
    entity_scope: EntityScope | null;
    dimension_key: string | null;
    field_label: string | null;
    figure_id: number | null;
    /** On a note comment (step 6e). */
    note_id?: number | null;
    note_part?: NotePart | null;
    /** On a comment on one of the notes agent's reports, such as a missing field. */
    report_id?: number | null;
  };
  text: string;
  scope: CommentScope;
  status: CommentStatus;
  outcome: Outcome | null;
  answer: string | null;
  proposed_guidance: string | null;
  round_id: number | null;
  guidance_status?: "added" | "dismissed" | null;
  guidance_version?: number | null;
  created_at: string;
  updated_at: string;
}

export type RoundStatus = "sent" | "working" | "done" | "failed" | "stopped";

export interface Round {
  id: number;
  run_id: number;
  number: number;
  status: RoundStatus;
  sent_by: string;
  sent_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: string | null;
  error: string | null;
  stop_requested: boolean;
  comment_ids: number[];
}

export interface Change {
  figure_id: number | null;
  statement: StatementCode;
  concept_uuid: string;
  field_label: string;
  period: Period;
  entity_scope: EntityScope;
  dimension_key: string;
  was: number | null;
  is_now: number | null;
  changed: boolean;
  served: number[];
  /** What moved, in plain words, e.g. "certainty sure → unsure". */
  differences?: string[];
}

/** What Accept all would accept now: the latest round's answered comments. */
export interface AcceptAll {
  round_id: number | null;
  comment_ids: number[];
}

/** A note the round changed, from note history (step 6e). */
export interface NoteChange {
  note_id: number;
  number: string;
  title: string;
  field_was: { node_uuid: string; label: string } | null;
  field_now: { node_uuid: string; label: string } | null;
  changed: boolean;
  /** What moved, in plain words, e.g. "look changed". */
  differences: string[];
  served: number[];
}

export interface RoundReport {
  round_id: number;
  comments: { comment_id: number; outcome: Outcome | null; answer: string | null; changed: boolean; verified: boolean; figures: Change[]; notes?: NoteChange[] }[];
  other: Change[];
  totals_recalculated: Change[];
  /** Notes the round changed that no comment points at. */
  notes_other?: NoteChange[];
  counts: { comments: number; changed: number; other: number; totals_recalculated: number; notes?: number };
}

/** Where a Needs you item, a change or a check points. */
export interface FigurePlace {
  statement?: PlaceStatement | null;
  concept_uuid?: string | null;
  period?: Period | null;
  entity_scope?: EntityScope | null;
  figure_id?: number | null;
  /** A note, for a note's Needs you item or comment (step 6e). */
  note_id?: number | null;
  /** A notes report, for a source gap or a missing mandatory field (step 6e). */
  report_id?: number | null;
}

export interface AlikeLine extends FigurePlace {
  figure_id: number;
  printed_label: string;
  field_label: string;
}

export type NeedsYouItem = FigurePlace & {
  kind: "failed_check" | "unsure" | "agent_comment" | "alike" | "note_to_check" | "unplaced_note" | "note_gap" | "missing_field" | "note_too_long";
  title: string;
  message: string;
  check?: string;
  comment_id?: number;
  count?: number;
  lines?: AlikeLine[];
};

export interface NeedsYou {
  items: NeedsYouItem[];
  passed: number;
}

// Step 5b: scope questions and guidance.

export type ScopeField = "standard" | "level" | "year_end" | "unit" | "layout";

export interface ScopeChoice {
  label: string;
  /** Null for "Not printed" on a statement whose layouts have no such value. */
  value: string | null;
  effect: string;
  suggested: boolean;
  /** On a setup layout card: what the choice sets. */
  layout?: string;
  included?: boolean;
}

export interface ScopeQuestion {
  id: number;
  run_id: number;
  stage: string;
  asked_by: string;
  field: ScopeField;
  statement: StatementCode | null;
  question: string;
  evidence: { text: string; page: number }[];
  choices: ScopeChoice[];
  setup_value: string | null;
  status: "open" | "answered";
  asked_at: string;
  answer: { choice: number | null; text: string | null; value: string | null; setup_changed: boolean; cleared: number; by: string; at: string } | null;
}

/** A question card on the setup screen, for an unsure suggestion. */
export interface SetupQuestion {
  /** "period": the Reader found no figures for last year and asks whether these are first statements. */
  field: "standard" | "level" | "unit" | "layout" | "period";
  statement: StatementCode | null;
  question: string;
  reason: string | null;
  pages: number[];
  choices: ScopeChoice[];
}

export interface Guidance {
  company_id: number | null;
  version: number;
  lines: string[];
  saved_by: string | null;
  saved_at: string | null;
  source: "typed" | "proposed" | "restored" | null;
  comment_id: number | null;
  restored_from: number | null;
}

export interface GuidanceVersion {
  version: number;
  saved_by: string;
  saved_at: string;
  source: "typed" | "proposed" | "restored";
  comment_id: number | null;
  restored_from: number | null;
  line_count: number;
}

export interface GuidancePage {
  company?: { id: number; name: string };
  guidance: Guidance;
  versions: GuidanceVersion[];
}

export interface RunGuidance {
  firm: Guidance;
  company: Guidance | null;
  company_id: number | null;
  /** Before setup is confirmed: the suggested company name matched an existing company. */
  company_from_suggestion?: boolean;
}

export interface RunStage {
  name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

/** One run, with what the run screen needs (GET /api/runs/{id}). */
export interface RunDetail extends Run {
  statements: { statement: StatementCode; name: string; layout: string; layout_label: string; pages: number[] }[];
  failure: { stage: "read" | "extract"; sentence: string } | null;
  working_on: StatementCode | null;
  open_question_id: number | null;
  stages: RunStage[];
  /** The statement being redone, with the ids of the figures kept through it, until it is finished again. */
  redo?: { statement: StatementCode; kept: number[] } | null;
}

/** A line of a statement a person edited or confirmed: a redo keeps it unless the person says otherwise. */
export interface KeptLine {
  concept_uuid: string;
  entity_scope: EntityScope;
  label: string;
  how: "edited" | "confirmed";
}

export interface RedoPreview {
  statement: StatementCode;
  name: string;
  /** Why the statement cannot be redone now, or null. */
  refusal: string | null;
  kept: KeptLine[];
}

export interface AgentCost {
  agent: string;
  seconds: number;
  calls: number;
  /** Null when none of the agent's calls has a known price. */
  cost_usd: number | null;
  unpriced: number;
}

export interface RunCost {
  agents: AgentCost[];
  total: Omit<AgentCost, "agent">;
}

// Step 2: a person's filled workbook and the comparison with the run.

export interface FilledWorkbook {
  filename: string;
  sha256: string;
  layout: "mtool" | "template";
  uploaded_by: string;
  uploaded_at: string;
  cells_read: number;
  not_assessed: number;
}

export type DifferenceKind = "extra" | "sign_only" | "scale" | "different" | "missing" | "zero_left_blank";

export interface ScoreCounts {
  agree: number;
  extra: number;
  sign_only: number;
  scale: number;
  different: number;
  missing: number;
  zero_left_blank: number;
  not_assessed: number;
}

export interface Score {
  person_filled: number;
  both_filled: number;
  agree: number;
  completeness: number | null;
  accuracy: number | null;
  complete_and_accurate: number | null;
  counts: ScoreCounts;
}

export interface Difference {
  kind: DifferenceKind;
  statement: StatementCode;
  concept_uuid: string;
  field_label: string;
  sheet: string;
  row: number;
  period: Period;
  entity_scope: EntityScope;
  dimension_key: string;
  matrix_col: string | null;
  run_value: number | null;
  person_value: number | null;
  figure_id: number | null;
  workbook_cell: string | null;
}

export interface NotAssessed {
  statement: StatementCode | null;
  reason: string;
  sentence: string;
  workbook_cell: string | null;
  concept_uuid: string | null;
  period: Period | null;
  entity_scope: EntityScope | null;
  dimension_key: string | null;
  figure_id: number | null;
}

export interface NoteFieldName {
  field_id: string;
  label: string;
}

/** A note of the workbook the run placed in a different field, or left out. */
export interface NoteDifference {
  kind: "different_field" | "missing";
  /** The note's printed number, or "" when the run has no note to name it by. */
  number: string;
  /** The note's printed title, or the workbook field's label when the run has no note to name it by. */
  title: string;
  run_fields: NoteFieldName[];
  workbook_fields: NoteFieldName[];
  /** The run's note, when it stored one. */
  note_id: number | null;
  pages: number[];
}

/** "Same field" only: the words are not compared. */
export interface NotesComparison {
  /** same_field / in_workbook. */
  score: number | null;
  in_workbook: number;
  same_field: number;
  different_field: number;
  missing: number;
  differences: NoteDifference[];
  only_in_run: { number: string; title: string; run_fields: NoteFieldName[] }[];
}

export interface Comparison {
  workbook: FilledWorkbook;
  /** Null when the workbook holds no notes. */
  notes: NotesComparison | null;
  tolerance: number;
  overall: Score;
  statements: { statement: StatementCode; score: Score }[];
  differences: Difference[];
  totals: { counts: ScoreCounts; differences: Difference[] };
  not_assessed: NotAssessed[];
}

/** An undone comment whose proposed line stays in the company's guidance. */
export interface GuidanceLineKept {
  comment_id: number;
  company_id: number;
  version: number;
}

/** One mTool fill: queued, filling, then ready with its receipt, or failed with one sentence. */
export type FillJobStatus = "queued" | "filling" | "ready" | "failed";

/** A figure or note the fill did not write, named in words, with its reason. Never a cell address. */
export interface ReceiptLine {
  /** Stable and unique within the receipt. */
  id: string;
  name: string;
  reason: string;
  code: string | null;
  kind: string;
}

export interface FillReceipt {
  counts: {
    written: number;
    not_written: number;
    notes: number;
    notes_not_written: number;
    reports?: number;
    reports_not_written?: number;
    /** Figures imported from the starting workbook, kept as they are (step 10g). */
    kept_in_workbook?: number;
    workbook_kept?: number;
  };
  lines: ReceiptLine[];
  template: { name: string | null; compatibility: string | null; reasons: string[] };
}

export interface Fill {
  id: number;
  run_id: number;
  job_status: FillJobStatus;
  error: string | null;
  template_filename: string;
  template_sha256: string;
  compatibility: string | null;
  status: "ok" | "needs review" | null;
  output_sha256: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  downloaded_at: string | null;
  /** Step 12: the search for places for the figures the fill could not place; null when none was needed. */
  investigation?: "queued" | "working" | "done" | "failed" | null;
  investigation_error?: string | null;
  /** How many proposed places wait for a person's Use or Skip. Present when the fill is read on its own. */
  placements_open?: number;
  receipt?: FillReceipt | null;
}

/** A cell the investigating agent proposed for a figure, in words, with its evidence (step 12). */
export interface Placement {
  id: number;
  figure: string;
  place: string;
  evidence: string;
  status: "open" | "used" | "skipped";
}
