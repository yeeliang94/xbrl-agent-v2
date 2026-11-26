import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SheetGrid, Statement } from "../../api";
import { mockFetch } from "../../test-utils";
import { sofp } from "./fixtures";
import { cellPlace, type Selection } from "./runModel";
import { SourceTab } from "./SourceTab";
import { sourcePlace } from "./SourceView";

afterEach(() => vi.unstubAllGlobals());

const cash = sofp.rows.find((r) => r.concept_uuid === "cash")!;
const thisYear = sofp.columns[0];

/** The statement as the server sends it for an Excel run: each row's sheet and row, each figure's cell. */
const fromWorkbook: Statement = {
  ...sofp,
  source_kind: "excel",
  rows: sofp.rows.map((r) =>
    r.concept_uuid === "cash"
      ? { ...r, source: { sheet: "SOFP", row: 9 }, cells: { ...r.cells, "Company:CY": { ...r.cells["Company:CY"], source_cell: "B9" } } }
      : r.page !== null && r.kind !== "heading"
        ? { ...r, source: { sheet: "SOFP", row: null } }
        : r,
  ),
};

const grid: SheetGrid = {
  name: "SOFP", position: 2, count: 3, columns: ["A", "B", "C"], first_page: 7, last_page: 7,
  rows: [{ row: 9, cells: { A: "Cash and bank balances", B: "1,264,900", C: "986,750" } }],
};

function show(statement: Statement, selection: Selection) {
  render(
    <SourceTab runId={1} statement={statement} selection={selection} comments={[]} busy={false} changed={new Set()} onSelect={() => {}} onChanged={async () => {}} />,
  );
}

describe("Where a figure comes from", () => {
  it("is said as a page, a reading-copy page, or a sheet, row and cell", () => {
    expect(sourcePlace(undefined, cash, 7)).toBe("Page 7");
    expect(sourcePlace("word", cash, 7)).toBe("Reading copy, page 7");
    expect(sourcePlace("excel", { ...cash, source: { sheet: "SOFP", row: 9 } }, 7, "B9")).toBe("SOFP, cell B9");
    expect(sourcePlace("excel", { ...cash, source: { sheet: "SOFP", row: 9 } }, 7)).toBe("SOFP, row 9");
    expect(sourcePlace("excel", { ...cash, source: { sheet: "SOFP", row: null } }, 7)).toBe("SOFP");
    expect(sourcePlace("excel", cash, 7)).toBe("Reading copy, page 7");
  });

  it("opens an Excel run's figure on its sheet with the cell marked", async () => {
    mockFetch({ "GET /api/runs/1/sheets/SOFP": { body: { sheet: grid } } });
    show(fromWorkbook, { kind: "cell", ...cellPlace(fromWorkbook, cash, thisYear) });

    expect(screen.getByText("Source").nextSibling).toHaveTextContent("SOFP, cell B9");
    const marked = await screen.findByText("1,264,900", { selector: "td" });
    expect(marked).toHaveClass("mk");
    expect(screen.getByText("Sheet 2 of 3")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("opens an Excel run's figure on its page picture when its line is not among the sheet's cells", () => {
    const fetched = mockFetch({});
    const other = fromWorkbook.rows.find((r) => r.source?.row === null && Object.keys(r.cells).length > 0)!;
    show(fromWorkbook, { kind: "cell", ...cellPlace(fromWorkbook, other, thisYear) });

    expect(screen.getByText("Source").nextSibling).toHaveTextContent("SOFP");
    expect(screen.getByAltText(`Page ${other.page}`)).toBeInTheDocument();
    expect(fetched.mock.calls.some(([url]) => String(url).includes("/sheets/"))).toBe(false);
  });

  it("opens a Word run's figure on its reading-copy page and says the numbers are its own", () => {
    mockFetch({});
    show({ ...sofp, source_kind: "word" }, { kind: "cell", ...cellPlace(sofp, cash, thisYear) });

    expect(screen.getByText("Source").nextSibling).toHaveTextContent("Reading copy, page 7");
    expect(screen.getByText("Reading copy made from the Word file. Page numbers differ from the printed report.")).toBeInTheDocument();
  });

  it("leaves a PDF run's figure as it was: no source line, no reading-copy line", () => {
    mockFetch({});
    show(sofp, { kind: "cell", ...cellPlace(sofp, cash, thisYear) });

    expect(screen.queryByText("Source")).not.toBeInTheDocument();
    expect(screen.queryByText(/Reading copy/)).not.toBeInTheDocument();
  });
});
