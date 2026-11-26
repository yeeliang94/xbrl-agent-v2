import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { Comparison, FilledWorkbook, NoteDifference, NotesComparison, Score } from "../../api";
import { mockFetch } from "../../test-utils";
import { CompareNoteSide } from "./CompareNoteSide";
import { CompareView, percent } from "./CompareView";

afterEach(() => vi.unstubAllGlobals());

const workbook: FilledWorkbook = { filename: "Seri Maju 2025 mTool.xlsx", sha256: "x", layout: "mtool", uploaded_by: "aina@firm.my", uploaded_at: "2026-11-22T09:00:00Z", cells_read: 214, not_assessed: 1 };
const counts = { agree: 110, extra: 1, sign_only: 1, scale: 0, different: 2, missing: 6, zero_left_blank: 0, not_assessed: 1 };
const score: Score = { person_filled: 120, both_filled: 114, agree: 110, completeness: 0.95, accuracy: 0.9649, complete_and_accurate: 0.9167, counts };
const moved: NoteDifference = {
  kind: "different_field", number: "24", title: "Related party disclosures", note_id: 12, pages: [31, 32],
  run_fields: [{ field_id: "f-other", label: "Disclosure of other related party transactions" }],
  workbook_fields: [{ field_id: "f-rp", label: "Disclosure of related party" }],
};
const left: NoteDifference = {
  kind: "missing", number: "27", title: "Capital commitments", note_id: null, pages: [],
  run_fields: [], workbook_fields: [{ field_id: "f-commit", label: "Disclosure of commitments" }],
};
const notes: NotesComparison = { score: 0.9474, in_workbook: 38, same_field: 36, different_field: 1, missing: 1, differences: [moved, left], only_in_run: [] };
const comparison: Comparison = {
  workbook, tolerance: 1, overall: score, notes,
  statements: [{ statement: "SOFP", score: { ...score, accuracy: null } }],
  differences: [{
    kind: "sign_only", statement: "SOFP", concept_uuid: "tpay", field_label: "Trade payables", sheet: "SOFP-Sub-CuNonCu", row: 404, period: "CY",
    entity_scope: "Company", dimension_key: "", matrix_col: null, run_value: -1628400, person_value: 1628400, figure_id: 31, workbook_cell: "SOFP-Sub-CuNonCu!B404",
  }],
  totals: { counts, differences: [] },
  not_assessed: [{ statement: "SOFP", reason: "not_a_number", sentence: "SOFP-Sub-CuNonCu!B139 holds text, not a number.", workbook_cell: "SOFP-Sub-CuNonCu!B139", concept_uuid: null, period: "CY", entity_scope: "Company", dimension_key: "", figure_id: null }],
};

describe("Compare", () => {
  it("offers to attach a workbook when there is none, and scores the run once attached", async () => {
    let attached: FilledWorkbook | null = null;
    const fetch = mockFetch({
      "GET /api/runs/1/filled-workbook": () => ({ body: { workbook: attached } }),
      "POST /api/runs/1/filled-workbook": () => {
        attached = workbook;
        return { body: { workbook } };
      },
      "GET /api/runs/1/comparison": { body: { comparison } },
    });
    render(<CompareView runId={1} onOpen={vi.fn()} />);
    expect(await screen.findByText(/No filled workbook/)).toBeInTheDocument();
    const file = new File(["x"], "Seri Maju 2025 mTool.xlsx");
    fireEvent.change(screen.getByLabelText("Filled workbook"), { target: { files: [file] } });
    expect(await screen.findByText("Differences")).toBeInTheDocument();
    const upload = fetch.mock.calls.find(([url, init]) => String(url) === "/api/runs/1/filled-workbook" && init?.method === "POST");
    expect((upload?.[1]?.body as FormData).get("file")).toBe(file);
  });

  it("shows the scores, the differences and what was not assessed; a difference opens its figure", async () => {
    mockFetch({ "GET /api/runs/1/filled-workbook": { body: { workbook } }, "GET /api/runs/1/comparison": { body: { comparison } } });
    const onOpen = vi.fn();
    render(<CompareView runId={1} onOpen={onOpen} />);
    await screen.findByText("Differences");
    const stats = document.querySelector(".stats") as HTMLElement;
    expect(within(stats).getByText("91.7%").nextSibling).toHaveTextContent("Complete and accurate");
    expect(within(stats).getByText("95%").nextSibling).toHaveTextContent("Completeness");
    expect(screen.getByText("Seri Maju 2025 mTool.xlsx")).toBeInTheDocument();
    // A score with nothing to divide by is a dash, never 0.
    const sofp = screen.getAllByText("Financial position")[0].closest("tr")!;
    expect(within(sofp).getByText("–")).toBeInTheDocument();
    const row = screen.getByText("Trade payables, this year").closest("tr")!;
    expect(row).toHaveTextContent("(1,628,400)");
    expect(row).toHaveTextContent("Sign only");
    fireEvent.click(row);
    expect(onOpen).toHaveBeenCalledWith({ statement: "SOFP", concept_uuid: "tpay", period: "CY", entity_scope: "Company", figure_id: 31 });
    expect(screen.getByText("SOFP-Sub-CuNonCu!B139 holds text, not a number.")).toBeInTheDocument();
  });

  it("removes the workbook after asking", async () => {
    let attached: FilledWorkbook | null = workbook;
    const fetch = mockFetch({
      "GET /api/runs/1/filled-workbook": () => ({ body: { workbook: attached } }),
      "GET /api/runs/1/comparison": { body: { comparison } },
      "DELETE /api/runs/1/filled-workbook": () => {
        attached = null;
        return { status: 204 };
      },
    });
    render(<CompareView runId={1} onOpen={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Remove the filled workbook?" })).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText(/No filled workbook/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  });

  it("shows a refused upload's sentence", async () => {
    mockFetch({
      "GET /api/runs/1/filled-workbook": { body: { workbook: null } },
      "POST /api/runs/1/filled-workbook": { status: 422, body: { detail: "Choose an .xlsx or .xlsm workbook." } },
    });
    render(<CompareView runId={1} onOpen={vi.fn()} />);
    await screen.findByText(/No filled workbook/);
    fireEvent.change(screen.getByLabelText("Filled workbook"), { target: { files: [new File(["x"], "a.csv")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose an .xlsx or .xlsm workbook.");
  });

  function Screen({ onOpenNote = vi.fn() }: { onOpenNote?: (id: number) => void }) {
    const [note, setNote] = useState<NoteDifference | null>(null);
    return (
      <>
        <CompareView runId={1} onOpen={vi.fn()} note={note} onNote={setNote} />
        {note && <CompareNoteSide runId={1} note={note} onClose={() => setNote(null)} onOpenNote={onOpenNote} />}
      </>
    );
  }

  const serve = (answer: Comparison) => mockFetch({ "GET /api/runs/1/filled-workbook": { body: { workbook } }, "GET /api/runs/1/comparison": { body: { comparison: answer } } });

  it("shows the notes score beside the figures, and the notes placed elsewhere or missing on their own tab", async () => {
    serve(comparison);
    render(<Screen />);
    await screen.findByText("Differences");
    const stats = document.querySelector(".stats") as HTMLElement;
    expect(within(stats).getByText("94.7%").nextSibling).toHaveTextContent("Notes in the same field");
    expect(screen.getByRole("radio", { name: /Figures/ })).toHaveTextContent("Figures1");
    const tab = screen.getByRole("radio", { name: /Notes/ });
    expect(tab).toHaveTextContent("Notes2");
    expect(screen.queryByText("Different field or missing")).not.toBeInTheDocument();

    fireEvent.click(tab);

    expect(screen.queryByText("Differences")).not.toBeInTheDocument();
    const counts = screen.getByText("Notes in workbook").closest("table")!;
    expect([...counts.querySelectorAll("td")].map((td) => td.textContent)).toEqual(["38", "36", "1", "1"]);
    const row = screen.getByText("Related party disclosures").closest("tr")!;
    expect([...row.querySelectorAll("td")].map((td) => td.textContent)).toEqual([
      "Related party disclosures", "Disclosure of other related party transactions", "Disclosure of related party", "Different field",
    ]);
    const missing = screen.getByText("Capital commitments").closest("tr")!;
    expect([...missing.querySelectorAll("td")].map((td) => td.textContent)).toEqual(["Capital commitments", "–", "Disclosure of commitments", "Missing"]);
  });

  it("opens a note's detail beside the list, and the note itself from there", async () => {
    serve(comparison);
    const onOpenNote = vi.fn();
    render(<Screen onOpenNote={onOpenNote} />);
    fireEvent.click(await screen.findByRole("radio", { name: /Notes/ }));
    const row = screen.getByText("Related party disclosures").closest("tr")!;
    fireEvent.click(row);

    expect(row).toHaveClass("sel");
    const side = screen.getByRole("heading", { name: "Related party disclosures" }).closest(".det") as HTMLElement;
    expect(within(side).getByText("Run").nextSibling).toHaveTextContent("Disclosure of other related party transactions");
    expect(within(side).getByText("Workbook").nextSibling).toHaveTextContent("Disclosure of related party");
    expect(within(side).getByText("Source").nextSibling).toHaveTextContent("Pages 31 to 32");
    expect(within(side).getByAltText("Page 31")).toBeInTheDocument();
    fireEvent.click(within(side).getByRole("button", { name: "Open note" }));
    expect(onOpenNote).toHaveBeenCalledWith(12);

    // A note the run never stored has nothing to open and no page.
    fireEvent.click(screen.getByText("Capital commitments").closest("tr")!);
    const other = screen.getByRole("heading", { name: "Capital commitments" }).closest(".det") as HTMLElement;
    expect(within(other).getByText("Run").nextSibling).toHaveTextContent("Not placed");
    expect(within(other).queryByRole("button", { name: "Open note" })).not.toBeInTheDocument();
    expect(within(other).queryByText("Source")).not.toBeInTheDocument();
    fireEvent.click(within(other).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "Capital commitments" })).not.toBeInTheDocument();
  });

  it("says so when every note is in the same field, and when the workbook has no notes", async () => {
    serve({ ...comparison, notes: { ...notes, score: 1, same_field: 38, different_field: 0, missing: 0, differences: [] } });
    const first = render(<Screen />);
    fireEvent.click(await screen.findByRole("radio", { name: /Notes/ }));
    expect(screen.getByText("Every note is in the same field")).toBeInTheDocument();
    expect(within(document.querySelector(".stats") as HTMLElement).getByText("100%").nextSibling).toHaveTextContent("Notes in the same field");
    first.unmount();

    serve({ ...comparison, notes: null });
    render(<Screen />);
    fireEvent.click(await screen.findByRole("radio", { name: /Notes/ }));
    expect(screen.getByText("The workbook has no notes")).toBeInTheDocument();
    expect(within(document.querySelector(".stats") as HTMLElement).queryByText("Notes in the same field")).toBeNull();
  });

  it("writes scores as percentages", () => {
    expect(percent(0.9649)).toBe("96.5%");
    expect(percent(1)).toBe("100%");
    expect(percent(null)).toBe("–");
  });
});
