import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Fill, FillReceipt } from "../../api";
import { mockFetch } from "../../test-utils";
import { FillDialog } from "./FillDialog";

afterEach(() => vi.unstubAllGlobals());

const NAME = "SeriMaju_MFRS_Company_2025.xlsx";
const fill = (over: Partial<Fill> = {}): Fill => ({
  id: 4, run_id: 1, job_status: "queued", error: null, template_filename: NAME, template_sha256: "x", compatibility: null,
  status: null, output_sha256: null, created_by: "aina@firm.my", created_at: "2026-11-23T09:00:00Z", started_at: null,
  finished_at: null, downloaded_at: null, ...over,
});
const receipt = (over: Partial<FillReceipt> = {}): FillReceipt => ({
  counts: { written: 214, not_written: 2, notes: 11, notes_not_written: 1 },
  lines: [
    { id: "skipped|oci|CY|Company|", name: "Other comprehensive income, Company, 2025", reason: "No value in the source, so the cell is left empty.", code: "no_value", kind: "skipped" },
    { id: "note_unresolved|12", name: "Contingent liabilities", reason: "The template has no text block for this field.", code: "no_note_cell", kind: "note_unresolved" },
  ],
  template: { name: "MFRS Company", compatibility: "known", reasons: [] },
  ...over,
});
const SLOW = { timeout: 3000 };
const NO_BOOK = { "GET /api/runs/1/starting-workbook": { body: { starting_workbook: null } } };

async function choose() {
  fireEvent.change(await screen.findByLabelText("mTool template"), { target: { files: [new File(["x"], NAME)] } });
}

describe("Prepare mTool file", () => {
  it("waits for a template before it can fill", async () => {
    mockFetch({ ...NO_BOOK, "GET /api/runs/1/fills": { body: { fills: [] } } });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Prepare mTool file" });
    expect(await within(dialog).findByText("No template chosen")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Choose template" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Fill template" })).toBeDisabled();
  });

  it("shows the chosen template with Replace, then fills, waits and shows the receipt", async () => {
    let polls = 0;
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill() } },
      "GET /api/runs/1/fills/4": () => (++polls < 2 ? { body: { fill: fill({ job_status: "filling" }) } } : { body: { fill: fill({ job_status: "ready", status: "ok", receipt: receipt() }) } }),
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    expect(screen.getByText(NAME)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    expect(await screen.findByText("Filling")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fill template" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Replace" })).toBeNull();

    const ready = await screen.findByRole("dialog", { name: "mTool file ready" }, SLOW);
    const stats = ready.querySelector(".stats") as HTMLElement;
    expect(within(stats).getByText("214").nextSibling).toHaveTextContent("Written");
    expect(within(stats).getByText("2").nextSibling).toHaveTextContent("Skipped");
    expect(within(stats).getByText("11").nextSibling).toHaveTextContent("Notes");
    expect(within(ready).getByText("Other comprehensive income, Company, 2025")).toBeInTheDocument();
    expect(within(ready).getByText("The template has no text block for this field.")).toBeInTheDocument();
    expect(ready.textContent).not.toMatch(/![A-Z]+\d+/);
    const upload = fetch.mock.calls.find(([url, init]) => String(url) === "/api/runs/1/fills" && init?.method === "POST");
    expect((upload?.[1]?.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("shows only the counts when the receipt lists nothing, and downloads the file", async () => {
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill({ job_status: "ready", receipt: receipt({ lines: [], counts: { written: 9, not_written: 0, notes: 0, notes_not_written: 0 } }) }) } },
      "GET /api/runs/1/fills/4/file": { body: {} },
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    const ready = await screen.findByRole("dialog", { name: "mTool file ready" });
    expect(ready.querySelector(".stats")).not.toBeNull();
    expect(within(ready).queryByRole("table")).toBeNull();
    fireEvent.click(within(ready).getByRole("button", { name: "Download" }));
    await vi.waitFor(() => expect(fetch.mock.calls.map(([u]) => String(u))).toContain("/api/runs/1/fills/4/file"));
    await vi.waitFor(() => expect(click).toHaveBeenCalled());
    click.mockRestore();
  });

  it("shows a failed fill with its sentence and lets the person fill again", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill({ job_status: "filling" }) } },
      "GET /api/runs/1/fills/4": { body: { fill: fill({ job_status: "failed", error: "This file could not be read as an Excel workbook." }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    const alert = await screen.findByRole("alert", {}, SLOW);
    expect(within(alert).getByText("Fill failed")).toHaveAttribute("data-kind", "failure");
    expect(within(alert).getByText("This file could not be read as an Excel workbook.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fill template" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
  });

  it("shows the server's sentence when the fill is refused", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 409, body: { detail: "The run is still working, so prepare the mTool file when it finishes." } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The run is still working, so prepare the mTool file when it finishes.");
  });

  it("picks up a fill still running when it opens", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [fill({ job_status: "filling" })] } },
      "GET /api/runs/1/fills/4": { body: { fill: fill({ job_status: "filling" }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    expect(await screen.findByText("Filling")).toBeInTheDocument();
    expect(screen.getByText(NAME)).toBeInTheDocument();
  });

  it("keeps asking after a failed ask, shows the failure meanwhile, and stops once ready", async () => {
    let polls = 0;
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [fill({ job_status: "filling" })] } },
      "GET /api/runs/1/fills/4": () => (++polls === 1 ? { status: 503, body: { detail: "The server is busy." } } : { body: { fill: fill({ job_status: "ready", status: "ok", receipt: receipt() }) } }),
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    expect(await screen.findByRole("alert", {}, SLOW)).toHaveTextContent("The server is busy.");
    expect(screen.getByText("Filling")).toBeInTheDocument();
    expect(await screen.findByRole("dialog", { name: "mTool file ready" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    const asks = () => fetch.mock.calls.filter(([url]) => String(url) === "/api/runs/1/fills/4").length;
    const after = asks();
    await new Promise((done) => setTimeout(done, 1500));
    expect(asks()).toBe(after);
  }, 10000);

  it("stops asking when the dialog closes", async () => {
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [fill({ job_status: "filling" })] } },
      "GET /api/runs/1/fills/4": { status: 503, body: { detail: "The server is busy." } },
    });
    const { rerender } = render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await screen.findByRole("alert", {}, SLOW);
    rerender(<FillDialog runId={1} open={false} onClose={vi.fn()} />);
    const asks = () => fetch.mock.calls.filter(([url]) => String(url) === "/api/runs/1/fills/4").length;
    const after = asks();
    await new Promise((done) => setTimeout(done, 2500));
    expect(asks()).toBe(after);
  }, 10000);

  it("says the file needs a check, with the template's reasons as lines, when the template is not recognised", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill({ job_status: "ready", status: "needs review", compatibility: "unknown", receipt: receipt({ template: { name: null, compatibility: "unknown", reasons: ["SOFP-CuNonCu marks a label column but carries no SSM names."] } }) }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    const check = await screen.findByRole("dialog", { name: "mTool file needs a check" });
    const rows = within(check).getAllByRole("row").map((row) => row.textContent);
    expect(rows[0]).toBe("SOFP-CuNonCu marks a label column but carries no SSM names.Template not recognised");
    expect(rows[1]).toContain("Other comprehensive income, Company, 2025");
    expect(within(check).getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("says the file needs a check when lines were not resolved on a known template", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill({ job_status: "ready", status: "needs review", compatibility: "known", receipt: receipt() }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Fill template" }));
    const check = await screen.findByRole("dialog", { name: "mTool file needs a check" });
    expect(within(check).getAllByRole("row")).toHaveLength(2);
    expect(within(check).getByRole("button", { name: "Download" })).toBeInTheDocument();
  });

  it("shows the latest ready fill again when it reopens, and can prepare another", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [fill({ id: 3, job_status: "failed" }), fill({ job_status: "ready", status: "ok" })] } },
      "GET /api/runs/1/fills/4": { body: { fill: fill({ job_status: "ready", status: "ok", receipt: receipt() }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    const ready = await screen.findByRole("dialog", { name: "mTool file ready" });
    expect(within(ready).getByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(within(ready).getByText(NAME)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("mTool template"), { target: { files: [new File(["y"], "Another.xlsx")] } });
    const prepare = screen.getByRole("dialog", { name: "Prepare mTool file" });
    expect(within(prepare).getByText("Another.xlsx")).toBeInTheDocument();
    expect(within(prepare).getByRole("button", { name: "Fill template" })).toBeEnabled();
  });

  it("fills the workbook attached at setup without asking for a template, and counts what it kept", async () => {
    const BOOK = "SeriMaju_FY2024_mTool.xlsx";
    const starting = {
      filename: BOOK, sha256: "x", uploaded_by: "aina@firm.my", uploaded_at: "2026-11-24T08:00:00Z",
      workbook: { standard: "MFRS", level: "Company", unit: "RM", year_end: "2025-12-31" }, imported_at: "2026-11-24T08:01:00Z",
      imported: { prior_year: 412, typed_this_year: 18, typed_totals: 6 },
    };
    const ready = fill({ template_filename: BOOK, job_status: "ready", status: "needs review", receipt: receipt({ counts: { written: 1604, not_written: 3, notes: 11, notes_not_written: 0, kept_in_workbook: 436 } }) });
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/starting-workbook": { body: { starting_workbook: starting } },
      "GET /api/runs/1/fills": { body: { fills: [] } },
      "POST /api/runs/1/fills": { status: 202, body: { fill: fill({ template_filename: BOOK }) } },
      "GET /api/runs/1/fills/4": { body: { fill: ready } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    expect(await screen.findByText(BOOK)).toBeInTheDocument();
    expect(screen.getByText(/The figures that came from it stay exactly as they are/)).toBeInTheDocument();
    expect(screen.queryByLabelText("mTool template")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fill workbook" }));
    const done = await screen.findByRole("dialog", { name: "mTool file needs a check" }, SLOW);
    const stats = done.querySelector(".stats") as HTMLElement;
    expect(within(stats).getByText("436").nextSibling).toHaveTextContent("Kept from the workbook");
    expect(within(stats).getByText("3").nextSibling).toHaveTextContent("Not written");
    expect(within(done).queryByRole("button", { name: "Replace" })).toBeNull();
    fireEvent.click(within(done).getByRole("button", { name: "Fill again" }));
    await waitFor(() => expect(fetch.mock.calls.filter(([url, init]) => String(url) === "/api/runs/1/fills" && init?.method === "POST")).toHaveLength(2));
    const start = fetch.mock.calls.find(([url, init]) => String(url) === "/api/runs/1/fills" && init?.method === "POST");
    expect(start?.[1]?.body).toBeUndefined();
  });

  it("offers nothing to fill until it knows whether the run has a starting workbook, and says when it cannot tell", async () => {
    mockFetch({ "GET /api/runs/1/fills": { body: { fills: [] } }, "GET /api/runs/1/starting-workbook": { status: 500, body: { detail: "The server could not read the run." } } });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The server could not read the run.");
    expect(screen.queryByLabelText("mTool template")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Fill/ })).toBeNull();
  });
});

describe("Check placements", () => {
  const unknown = receipt({
    counts: { written: 150, not_written: 2, notes: 11, notes_not_written: 0 },
    lines: [
      { id: "unresolved|land|CY|Company|", name: "Freehold land, 2025", reason: "The template has no cell for this field.", code: "no_cell", kind: "unresolved" },
      { id: "unresolved|land|PY|Company|", name: "Freehold land, 2024", reason: "No place found in this template.", code: "no_cell", kind: "unresolved" },
    ],
    template: { name: null, compatibility: "unknown", reasons: ["SOFP-Sub-CuNonCu marks a label column but carries no SSM names."] },
  });
  const ready = (over: Partial<Fill> = {}) => fill({ job_status: "ready", status: "needs review", receipt: unknown, ...over });
  const places = [
    { id: 7, figure: "Freehold land, 2025", place: 'SOFP-Sub-CuNonCu, row 30 "Freehold land", column E (31/12/2025)', evidence: "The row's label matches; column E is this year.", status: "open" },
    { id: 8, figure: "Leasehold land, 2025", place: 'SOFP-Sub-CuNonCu, row 31 "Leasehold land", column E (31/12/2025)', evidence: "The label matches.", status: "open" },
  ];

  it("says it is looking for places while the template is investigated", async () => {
    let polls = 0;
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [ready({ investigation: "working" })] } },
      "GET /api/runs/1/fills/4": () => ({ body: { fill: ++polls < 2 ? ready({ investigation: "working" }) : ready({ investigation: "done", placements_open: 2 }) } }),
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog", { name: "mTool file needs a check" });
    expect(within(dialog).getByText("Looking for places in the template")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Check placements" })).toBeNull();
    expect(await within(dialog).findByRole("button", { name: "Check placements" }, SLOW)).toBeInTheDocument();
    expect(within(dialog).getByText("No place found in this template.")).toBeInTheDocument();
  });

  it("shows a failed search for places with the failure label", async () => {
    mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [ready({ investigation: "failed" })] } },
      "GET /api/runs/1/fills/4": { body: { fill: ready({ investigation: "failed", investigation_error: "The model did not answer; the receipt stands as it is." }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    const failure = await screen.findByText("Search for places failed");
    expect(failure.closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByText("The model did not answer; the receipt stands as it is.")).toBeInTheDocument();
  });

  it("lists each proposed place with its evidence, and saves the used ones and fills again", async () => {
    const fetch = mockFetch({
      ...NO_BOOK,
      "GET /api/runs/1/fills": { body: { fills: [ready({ investigation: "done" })] } },
      "GET /api/runs/1/fills/4": { body: { fill: ready({ investigation: "done", placements_open: 2 }) } },
      "GET /api/runs/1/fills/4/placements": { body: { placements: places } },
      "POST /api/runs/1/fills/4/placements": { status: 202, body: { fill: fill({ id: 5, job_status: "queued" }) } },
      "GET /api/runs/1/fills/5": { body: { fill: fill({ id: 5, job_status: "filling" }) } },
    });
    render(<FillDialog runId={1} open onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Check placements" }));
    const check = await screen.findByRole("dialog", { name: "Check placements" });
    expect(await within(check).findByText("The row's label matches; column E is this year.")).toBeInTheDocument();
    fireEvent.click(within(check).getByRole("radiogroup", { name: "Use or skip Leasehold land, 2025" }).querySelector("button:last-child")!);
    fireEvent.click(within(check).getByRole("button", { name: "Save and fill again" }));
    await waitFor(() => {
      const sent = fetch.mock.calls.find(([url, init]) => String(url) === "/api/runs/1/fills/4/placements" && init?.method === "POST");
      expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ use: [7] });
    });
    expect(await screen.findByText("Filling")).toBeInTheDocument();
  });
});
