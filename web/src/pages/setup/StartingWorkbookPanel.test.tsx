import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StartingWorkbook } from "../../api";
import { mockFetch } from "../../test-utils";
import { StartingWorkbookPanel } from "./StartingWorkbookPanel";

afterEach(() => vi.unstubAllGlobals());

const book: StartingWorkbook = {
  filename: "SeriMaju_FY2024_mTool.xlsx", sha256: "x", uploaded_by: "aina@firm.my", uploaded_at: "2026-11-24T08:00:00Z",
  workbook: { standard: "MFRS", level: "Company", unit: "RM'000", year_end: "2025-12-31" }, imported_at: null, imported: null,
};
const pick = (name = book.filename) => fireEvent.change(screen.getByLabelText("Starting workbook"), { target: { files: [new File(["x"], name)] } });

describe("Starting workbook at setup", () => {
  it("attaches a workbook and shows what it says of itself, then removes it", async () => {
    const fetch = mockFetch({
      "GET /api/runs/1/starting-workbook": { body: { starting_workbook: null } },
      "POST /api/runs/1/starting-workbook": { body: { starting_workbook: book } },
      "DELETE /api/runs/1/starting-workbook": { status: 204 },
    });
    const onBusy = vi.fn();
    render(<StartingWorkbookPanel runId={1} onBusy={onBusy} />);
    fireEvent.click(await screen.findByRole("button", { name: "Attach workbook" }));
    pick();
    expect(onBusy).toHaveBeenLastCalledWith(true);
    expect(await screen.findByText(book.filename)).toBeInTheDocument();
    expect(screen.getByText("MFRS, Company, RM thousands")).toBeInTheDocument();
    expect(onBusy).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Attach workbook" })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  });

  it("shows a refused workbook's sentence and offers another", async () => {
    const sentence = "This is not an mTool workbook, so attach last year's mTool file rolled forward to this year.";
    mockFetch({
      "GET /api/runs/1/starting-workbook": { body: { starting_workbook: null } },
      "POST /api/runs/1/starting-workbook": { status: 422, body: { detail: sentence } },
    });
    render(<StartingWorkbookPanel runId={1} onBusy={vi.fn()} />);
    await screen.findByRole("button", { name: "Attach workbook" });
    pick("notes.xlsx");
    expect(await screen.findByRole("alert")).toHaveTextContent(sentence);
    expect(screen.getByText("Not attached").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByRole("button", { name: "Attach another" })).toBeInTheDocument();
  });

  it("shows a workbook attached earlier", async () => {
    mockFetch({ "GET /api/runs/1/starting-workbook": { body: { starting_workbook: book } } });
    render(<StartingWorkbookPanel runId={1} onBusy={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(book.filename)).toBeInTheDocument());
  });
});
