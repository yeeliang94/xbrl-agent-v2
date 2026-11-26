import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentMap, ReadProgress, RunDocument, SheetGrid, SuggestedSetup, WorkbookSheet } from "../../api";
import { mockFetch, run, type Reply } from "../../test-utils";
import { SetupPage } from "./SetupPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const sheet = (name: string, first: number | null, over: Partial<WorkbookSheet> = {}): WorkbookSheet => ({
  name, hidden: false, used: first !== null, first_page: first, last_page: first, rows: 4, empty_formulas: 0, notice: null, ...over,
});

const workbook: RunDocument = {
  filename: "Accounts 2025.xlsx", kind: "excel", sha256: "x", size_bytes: 10, page_count: 4, scanned_pages: 0,
  uploaded_by: "aina@firm.my", uploaded_at: "2026-11-26T09:00:00Z", pages: [],
  sheets: [sheet("Cover", 1), sheet("SOFP", 2), sheet("SOPL", 3), sheet("Notes", 4), sheet("Old SOFP", null, { hidden: true })],
};

const grid = (name: string, position: number): SheetGrid => ({
  name, position, count: 4, columns: ["A", "B", "C"], first_page: position, last_page: position,
  rows: [{ row: 5, cells: { A: "Property, plant and equipment", B: "1,284,300", C: "1,196,450" } }],
});

const finding = (value: string | null) => ({ value, pages: [1], reason: "On the cover.", unsure: false });
const choices = (values: string[]) => ({ MFRS: values.map((value) => ({ value, label: value })), MPERS: values.map((value) => ({ value, label: value })) });

const setup: SuggestedSetup = {
  company: finding("Contoh Maju Sdn. Bhd."), year_end: finding("2025-12-31"), year: 2025,
  standard: finding("MFRS"), level: finding("Company"), unit: finding("RM"),
  statements: [
    { statement: "SOFP", found: true, pages: [2], layout: "CuNonCu", layouts: choices(["CuNonCu"]), reason: "The sheet SOFP shows current and non-current assets.", unsure: false },
    { statement: "SOPL", found: true, pages: [3], layout: "Function", layouts: choices(["Function"]), reason: "The sheet SOPL groups costs by role.", unsure: false },
  ],
};

const map: DocumentMap = {
  saved_at: "2026-11-26T09:02:00Z",
  notes: [{ number: "1", title: "Corporate information", first_page: 4, last_page: 4 }],
  note_gaps: [],
  open_points: [],
};

const done: ReadProgress = {
  status: "done", started_at: "2026-11-26T09:00:00Z", finished_at: "2026-11-26T09:01:00Z", error: null,
  pages: { total: 4, read: 4, blank: 0, failed: 0, waiting: 0 }, map_saved: true,
};

function routes(extra: Record<string, Reply | ((init: RequestInit | undefined) => Reply)> = {}) {
  return {
    "GET /api/runs/5/document": { body: { document: workbook } },
    "GET /api/runs/5/read": { body: { read: done } },
    "GET /api/runs/5/events": { body: { events: [], last_id: 0, has_more: false } },
    "GET /api/runs/5/setup": { body: { setup } },
    "GET /api/runs/5/map": { body: { map } },
    "GET /api/runs/5/sheets/SOFP": { body: { sheet: grid("SOFP", 2) } },
    "GET /api/runs/5/sheets/Cover": { body: { sheet: { ...grid("Cover", 1), rows: [{ row: 1, cells: { A: "Contoh Maju Sdn. Bhd." } }] } } },
    ...extra,
  };
}

const statementLine = (name: string) => screen.getByRole("button", { name }).closest(".line") as HTMLElement;

describe("Setup of a run from an Excel workbook", () => {
  it("names each statement's sheet and the notes' sheet, and counts the workbook's sheets", async () => {
    mockFetch(routes());
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    expect(screen.getByText("5 sheets")).toBeInTheDocument();
    expect(within(statementLine("Financial position")).getByText("SOFP")).toBeInTheDocument();
    expect(within(statementLine("Profit or loss")).getByText("SOPL")).toBeInTheDocument();
    expect(within(statementLine("Notes")).getByText("Notes", { selector: ".pg" })).toBeInTheDocument();
  });

  it("gives a spare sheet to the notes and lets the person stop using a notes sheet", async () => {
    let sent: { notes: { number: string; title: string; first_page: number }[] } | null = null;
    mockFetch(routes({
      "POST /api/runs/5/setup": (init) => {
        sent = JSON.parse(String(init?.body));
        return { body: { run: run({ id: 5, status: "ready" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    const panel = (await screen.findByRole("heading", { name: "Sheets not used" })).closest("section") as HTMLElement;
    fireEvent.change(within(panel).getByLabelText("Use Cover for"), { target: { value: "notes" } });
    expect(within(statementLine("Notes")).getByText("Cover, Notes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Do not use Notes" }));
    expect(within(statementLine("Notes")).getByText("Cover", { selector: ".pg" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.notes).toEqual([{ number: "", title: "Cover", first_page: 1, last_page: 1 }]);
  });

  it("tells the person about formulas saved without a result", async () => {
    const notice = "The sheet SOFP has 1 formula saved without a result, so it reads as empty. Open the workbook in Excel, save it and upload it again.";
    mockFetch({
      ...routes(),
      "GET /api/runs/5/document": { body: { document: { ...workbook, sheets: workbook.sheets!.map((s) => (s.name === "SOFP" ? { ...s, empty_formulas: 1, notice } : s)) } } },
    });
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    expect(screen.getByText(notice)).toBeInTheDocument();
  });

  it("shows a statement's sheet as cells and lets the person choose another sheet", async () => {
    let sent: { statements: { statement: string; pages: number[] }[] } | null = null;
    mockFetch(routes({
      "POST /api/runs/5/setup": (init) => {
        sent = JSON.parse(String(init?.body));
        return { body: { run: run({ id: 5, status: "ready" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.click(screen.getByRole("button", { name: "Financial position" }));
    expect(await screen.findByText("1,284,300")).toBeInTheDocument();
    expect(screen.getByText("Sheet 2 of 4")).toBeInTheDocument();
    expect(screen.getByText("The sheet SOFP shows current and non-current assets.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Financial position sheet"), { target: { value: "Cover" } });
    expect(await screen.findByText("Contoh Maju Sdn. Bhd.", { selector: "td" })).toBeInTheDocument();
    expect(within(statementLine("Financial position")).getByText("Cover")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.statements.find((s) => s.statement === "SOFP")!.pages).toEqual([1]);
  });

  it("lists the sheets not used, gives one to a statement and brings a hidden one in", async () => {
    const brought: string[] = [];
    mockFetch(routes({
      "POST /api/runs/5/sheets/bring-in": (init) => {
        brought.push(JSON.parse(String(init?.body)).sheet);
        return { body: { run: run({ id: 5, status: "reading" }), document: { ...workbook, page_count: 5 } } };
      },
    }));
    render(<SetupPage runId={5} />);
    const panel = (await screen.findByRole("heading", { name: "Sheets not used" })).closest("section") as HTMLElement;
    expect(within(panel).getByText("Cover")).toBeInTheDocument();
    expect(within(panel).getByText("Hidden sheet")).toBeInTheDocument();
    expect(within(panel).queryByText("SOFP")).not.toBeInTheDocument();

    fireEvent.change(within(panel).getByLabelText("Use Cover for"), { target: { value: "1" } });
    expect(within(statementLine("Profit or loss")).getByText("Cover, SOPL")).toBeInTheDocument();
    expect(within(panel).queryByText("Cover")).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Bring in" }));
    await waitFor(() => expect(brought).toEqual(["Old SOFP"]));
  });

  it("says the sheet of each note", async () => {
    mockFetch(routes());
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.click(screen.getByRole("button", { name: "Notes" }));
    const notes = screen.getAllByRole("heading", { name: "Notes" }).slice(-1)[0].closest("section") as HTMLElement;
    expect(within(notes).getByText("Corporate information")).toBeInTheDocument();
    expect(within(notes).getByText("Notes", { selector: "span.mono" })).toBeInTheDocument();
  });
});
