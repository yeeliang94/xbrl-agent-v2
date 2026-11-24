// Step 10: reports and the starting workbook (docs/api-contract.md, Step 10a-c and Step 10d).

export type ReportCode = "DIRECTORS_REPORT" | "STATEMENT_BY_DIRECTORS" | "AUDITORS_REPORT";
export type ReportFieldKind = "html" | "date" | "choice" | "text";
export type ReportFieldStatus = "not_assessed" | "filled" | "not_shown" | "unsure" | "cleared";

export interface ReportField {
  report: ReportCode;
  field_id: string;
  element_id: string;
  label: string;
  kind: ReportFieldKind;
  choices: string[];
  row: number;
  status: ReportFieldStatus;
  value: string | null;
  reason: string;
  pages: number[];
  revision: number;
  updated_by: string | null;
  actor_kind: "agent" | "person" | null;
  updated_at: string | null;
  /** The narrative only: its text as mTool gets it, and whether it fits. Null until it is filled. */
  html?: string | null;
  fit?: { tier: string; chars: number; limit: number } | null;
}

export interface Report {
  report: ReportCode;
  name: string;
  sheet: string;
  fields: ReportField[];
  assessed: number;
  total: number;
}

export interface Reports {
  stage: { status: string; error: string | null } | null;
  reports: Report[];
}

/** A person's change to a short field. The narrative is only cleared from the screen. */
export interface ReportFieldEdit {
  revision: number;
  status?: "filled" | "not_shown" | "unsure";
  value?: string;
  pages?: number[];
  reason?: string;
}

export interface WorkbookSays {
  standard: string | null;
  level: string | null;
  unit: string | null;
  year_end: string | null;
}

export interface StartingWorkbook {
  filename: string;
  sha256: string;
  uploaded_by: string;
  uploaded_at: string;
  workbook: WorkbookSays;
  imported_at: string | null;
  imported: { prior_year: number; typed_this_year: number; typed_totals: number } | null;
}
