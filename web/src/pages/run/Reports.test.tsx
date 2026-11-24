import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Report, ReportField } from "../../api";
import { mockFetch } from "../../test-utils";
import { pageRange, shownValue, textPreview } from "./reportModel";
import { ReportSide } from "./ReportSide";
import { ReportWork } from "./ReportView";

afterEach(() => vi.unstubAllGlobals());

const field = (over: Partial<ReportField> = {}): ReportField => ({
  report: "AUDITORS_REPORT", field_id: "AUD-15", element_id: "ssmt_NameOfAuditFirm", label: "Name of audit firm", kind: "text",
  choices: [], row: 15, status: "filled", value: "Ernst & Young PLT", reason: "", pages: [34], revision: 2,
  updated_by: "reports", actor_kind: "agent", updated_at: "2026-11-24T08:00:00Z", ...over,
});
const OPINION = field({ field_id: "AUD-5", label: "Type of auditor's opinion", kind: "choice", choices: ["Unmodified opinion", "Modified opinion - Adverse"], value: "Unmodified opinion" });
const TEXT = field({ field_id: "AUD-1", label: "Auditors' report text", kind: "html", value: "We have audited the financial statements", html: "<p>We have audited the financial statements of Seri Maju.</p>", pages: [34, 35, 36] });
const STATE = field({ field_id: "AUD-21", label: "State", status: "not_assessed", value: null, pages: [], revision: 0 });
const LINE3 = field({ field_id: "AUD-19", label: "Address line 3", status: "not_shown", value: null, reason: "The address has two street lines." });
const report: Report = { report: "AUDITORS_REPORT", name: "Auditors' report", sheet: "AuditReport", fields: [TEXT, OPINION, field(), LINE3, STATE], assessed: 4, total: 13 };

describe("Reports", () => {
  it("lists every field with its value, why an empty one is empty, and its page", () => {
    const onSelect = vi.fn();
    render(<ReportWork report={report} field={null} text={false} error="" stage={{ status: "done", error: null }} onSelect={onSelect} onBack={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Auditors' report" })).toBeInTheDocument();
    expect(screen.getByText("13 fields")).toBeInTheDocument();
    const row = (name: string) => screen.getByRole("button", { name }).closest("tr") as HTMLElement;
    expect(within(row("Name of audit firm")).getByText("Ernst & Young PLT")).toBeInTheDocument();
    expect(within(row("Address line 3")).getByText("Not shown").closest("[data-kind]")).toHaveAttribute("data-kind", "neutral");
    expect(within(row("State")).getByText("Not read yet")).toBeInTheDocument();
    expect(within(row("Auditors' report text")).getByText("p34–36")).toBeInTheDocument();
    expect(within(row("Auditors' report text")).getByText("We have audited the financial statements")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Name of audit firm" }));
    expect(onSelect).toHaveBeenCalledWith("AUD-15");
  });

  it("opens a report's wording on the page as mTool gets it", () => {
    const onBack = vi.fn();
    render(<ReportWork report={report} field={TEXT} text error="" stage={{ status: "done", error: null }} onSelect={vi.fn()} onBack={onBack} />);
    expect(screen.getByText("We have audited the financial statements of Seri Maju.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to fields" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("saves a person's change with the revision they saw, and clears a field", async () => {
    const onChanged = vi.fn(async () => {});
    const fetch = mockFetch({
      "PATCH /api/runs/1/reports/AUDITORS_REPORT/AUD-15": { body: { field: field({ value: "Ernst & Young PLT (AF 0039)", revision: 3 }) } },
      "POST /api/runs/1/reports/AUDITORS_REPORT/AUD-15/clear": { body: { field: field({ status: "cleared", value: null, revision: 3 }) } },
    });
    render(<ReportSide runId={1} field={field()} busy={false} onOpenText={vi.fn()} onChanged={onChanged} />);
    const input = screen.getByRole("textbox", { name: "Name of audit firm" });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "Ernst & Young PLT (AF 0039)" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const patch = fetch.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ revision: 2, status: "filled", value: "Ernst & Young PLT (AF 0039)", pages: [34] });
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
    const clear = fetch.mock.calls.find(([url]) => String(url).endsWith("/clear"));
    expect(JSON.parse(String(clear?.[1]?.body))).toEqual({ revision: 2 });
  });

  it("shows a stale edit's sentence and keeps what the person typed", async () => {
    mockFetch({ "PATCH /api/runs/1/reports/AUDITORS_REPORT/AUD-5": { status: 409, body: { detail: "Type of auditor's opinion changed since you opened it, so reload it before saving." } } });
    render(<ReportSide runId={1} field={OPINION} busy={false} onOpenText={vi.fn()} onChanged={vi.fn(async () => {})} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Type of auditor's opinion" }), { target: { value: "Modified opinion - Adverse" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed since you opened it");
    expect(screen.getByRole("combobox", { name: "Type of auditor's opinion" })).toHaveValue("Modified opinion - Adverse");
  });

  it("does not save on Enter when nothing changed", () => {
    const fetch = mockFetch({});
    render(<ReportSide runId={1} field={field()} busy={false} onOpenText={vi.fn()} onChanged={vi.fn(async () => {})} />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name of audit firm" }), { key: "Enter" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("says why the fields are empty when the reports agent failed or never ran", () => {
    const { rerender } = render(<ReportWork report={report} field={null} text={false} error="" stage={{ status: "failed", error: "No report field was saved." }} onSelect={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No report field was saved.");
    expect(screen.getByText("Reports agent failed").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    rerender(<ReportWork report={report} field={null} text={false} error="" stage={null} onSelect={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText(/so the reports agent did not run/)).toBeInTheDocument();
  });

  it("gives the reason a field is empty, and the narrative opens instead of being typed", () => {
    const { rerender } = render(<ReportSide runId={1} field={LINE3} busy={false} onOpenText={vi.fn()} onChanged={vi.fn(async () => {})} />);
    expect(screen.getByText("The address has two street lines.")).toBeInTheDocument();
    const onOpenText = vi.fn();
    rerender(<ReportSide runId={1} field={TEXT} busy={false} onOpenText={onOpenText} onChanged={vi.fn(async () => {})} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open text" }));
    expect(onOpenText).toHaveBeenCalled();
  });

  it("previews a narrative kept as page blocks from its prepared text", () => {
    expect(textPreview(field({ kind: "html", value: null, html: "<p>The directors   present</p><p>their report.</p>" }))).toBe("The directors present their report.");
  });

  it("writes dates and page ranges as a person reads them", () => {
    expect(shownValue(field({ kind: "date", value: "2025-03-28" }))).toBe("28 March 2025");
    expect(pageRange([7, 2, 3, 4])).toBe("p2–4, 7");
    expect(pageRange([])).toBe("");
  });
});
