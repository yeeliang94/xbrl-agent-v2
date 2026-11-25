import type { Report, ReportCode, ReportField } from "../../api";
import type { StatusKind } from "../../components/Status";

export const REPORT_CODES: ReportCode[] = ["DIRECTORS_REPORT", "STATEMENT_BY_DIRECTORS", "AUDITORS_REPORT"];

export const isReport = (section: string | null): section is ReportCode => REPORT_CODES.includes(section as ReportCode);

/** A field left empty or not read yet shows why as a dot and a word; a filled field shows nothing. */
export function fieldStatus(field: ReportField): { kind: StatusKind; word: string } | null {
  switch (field.status) {
    case "filled":
      return null;
    case "unsure":
      return { kind: "attention", word: "Unsure" };
    case "not_shown":
      return { kind: "neutral", word: "Not shown" };
    case "cleared":
      return { kind: "neutral", word: "Cleared" };
    default:
      return null;
  }
}

/** "2025-03-28" reads "28 March 2025"; anything else is shown as saved. */
export function shownValue(field: ReportField): string {
  const value = field.value ?? "";
  if (field.kind !== "date" || !/^\d{4}-\d\d-\d\d$/.test(value)) return value;
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

/** [2, 3, 4, 7] reads "p2–4, 7". */
export function pageRange(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(j > i ? `${sorted[i]}–${sorted[j]}` : `${sorted[i]}`);
    i = j + 1;
  }
  return parts.length ? `p${parts.join(", ")}` : "";
}

/** What waits for a person in a report: its unsure fields. */
export const reportCount = (report: Report) => report.fields.filter((f) => f.status === "unsure").length;

/** The start of a report's wording, for its row in the fields list. */
export function textPreview(field: ReportField, length = 60): string {
  const text = field.value ?? (field.html ? new DOMParser().parseFromString(field.html.replace(/</g, " <"), "text/html").body.textContent ?? "" : "");
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > length ? `${flat.slice(0, length).trimEnd()}…` : flat;
}
