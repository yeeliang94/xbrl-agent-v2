import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Comparison, FilledWorkbook, Score } from "../../api";
import { mockFetch } from "../../test-utils";
import { CompareView, percent } from "./CompareView";

afterEach(() => vi.unstubAllGlobals());

const workbook: FilledWorkbook = { filename: "Seri Maju 2025 mTool.xlsx", sha256: "x", layout: "mtool", uploaded_by: "aina@firm.my", uploaded_at: "2026-11-22T09:00:00Z", cells_read: 214, not_assessed: 1 };
const counts = { agree: 110, extra: 1, sign_only: 1, scale: 0, different: 2, missing: 6, zero_left_blank: 0, not_assessed: 1 };
const score: Score = { person_filled: 120, both_filled: 114, agree: 110, completeness: 0.95, accuracy: 0.9649, complete_and_accurate: 0.9167, counts };
const comparison: Comparison = {
  workbook, tolerance: 1, overall: score,
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

  it("writes scores as percentages", () => {
    expect(percent(0.9649)).toBe("96.5%");
    expect(percent(1)).toBe("100%");
    expect(percent(null)).toBe("–");
  });
});
