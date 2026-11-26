import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentMap, ReadProgress, RunDocument, SuggestedSetup } from "../../api";
import { mockFetch, run, type Reply } from "../../test-utils";
import { SetupPage } from "./SetupPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const document: RunDocument = {
  filename: "Doc 4.pdf", sha256: "x", size_bytes: 10, page_count: 37, scanned_pages: 37,
  uploaded_by: "aina@firm.my", uploaded_at: "2026-11-18T09:00:00Z", pages: [],
};

const progress = (over: Partial<ReadProgress> = {}): ReadProgress => ({
  status: "working", started_at: "2026-11-18T09:00:00Z", finished_at: null, error: null,
  pages: { total: 37, read: 20, blank: 1, failed: 0, waiting: 16 }, map_saved: false, ...over,
});

const finding = (value: string | null, unsure = false) => ({ value, pages: [3], reason: "Shown on page 3.", unsure });

// The choices as the server sends them: values with labels, per standard.
const LABELS: Record<string, string> = {
  CuNonCu: "Current and non-current", OrderOfLiquidity: "Order of liquidity", Function: "By function", Nature: "By nature",
  BeforeTax: "Before tax", NetOfTax: "Net of tax", NotPrepared: "Not printed", Indirect: "Indirect", Direct: "Direct",
  Default: "Changes in equity", SoRE: "Retained earnings",
};
const choices = (mfrs: string[], mpers: string[] = mfrs) => ({
  MFRS: mfrs.map((value) => ({ value, label: LABELS[value] })),
  MPERS: mpers.map((value) => ({ value, label: LABELS[value] })),
});

const setup: SuggestedSetup = {
  company: finding("Bukit Indah Services Berhad"), year_end: finding("2021-12-31"), year: 2021,
  standard: finding("MFRS"), level: finding("Company"), unit: finding("RM"),
  statements: [
    { statement: "SOFP", found: true, pages: [14], layout: "CuNonCu", layouts: choices(["CuNonCu", "OrderOfLiquidity"]), reason: "Page 14 shows current and non-current sections.", unsure: false },
    { statement: "SOPL", found: true, pages: [15], layout: "Nature", layouts: choices(["Function", "Nature"]), reason: "Only income and expenditure are shown.", unsure: true },
    { statement: "SOCI", found: false, pages: [], layout: "NotPrepared", layouts: choices(["BeforeTax", "NetOfTax", "NotPrepared"]), reason: "No statement of comprehensive income is printed.", unsure: false },
    { statement: "SOCF", found: true, pages: [17], layout: "Direct", layouts: choices(["Indirect", "Direct"]), reason: "Cash received from members.", unsure: false },
    { statement: "SOCIE", found: true, pages: [16], layout: "Default", layouts: choices(["Default"], ["Default", "SoRE"]), reason: "Page 16.", unsure: false },
  ],
};

const map: DocumentMap = {
  saved_at: "2026-11-18T09:02:00Z",
  notes: [
    { number: "1", title: "General information", first_page: 18, last_page: 18 },
    { number: "3", title: "Significant accounting policies", first_page: 19, last_page: 23 },
  ],
  note_gaps: [],
  open_points: ["Note 2 is not in the list; find it or say why it is absent.", "The unit rests on fewer than two pages; check."],
};

function routes(read: ReadProgress, extra: Record<string, Reply | ((init: RequestInit | undefined) => Reply)> = {}) {
  return {
    "GET /api/runs/5/document": { body: { document } },
    "GET /api/runs/5/read": { body: { read } },
    "GET /api/runs/5/events": {
      body: {
        events: [
          { id: 1, job_id: 1, source: "reading", kind: "transcribing", message: "Reading 37 pages.", created_at: "2026-11-18T09:00:01Z", has_data: false },
          { id: 2, job_id: 1, source: "reading", kind: "page", message: "Read page 1 of 37.", created_at: "2026-11-18T09:00:08Z", has_data: true },
        ],
        last_id: 2,
        has_more: false,
      },
    },
    "GET /api/runs/5/setup": { body: { setup } },
    "GET /api/runs/5/map": { body: { map } },
    ...extra,
  };
}

const ready = async () => {
  mockFetch(routes(progress({ status: "done", map_saved: true })));
  render(<SetupPage runId={5} />);
  await screen.findByRole("heading", { name: "Statements" });
};

describe("Setup page", () => {
  it("shows reading progress and the activity while reading, with Start run off", async () => {
    mockFetch(routes(progress()));
    render(<SetupPage runId={5} />);
    expect(await screen.findByText("Reading page 22 of 37")).toBeInTheDocument();
    expect(screen.getByText("Doc 4.pdf")).toBeInTheDocument();
    expect(screen.getByText("37 pages")).toBeInTheDocument();
    expect(screen.getByText("Reading 37 pages.")).toBeInTheDocument();
    expect(screen.getByText("Read page 1 of 37.")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "21");
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("shows a failed reading with its reason and tries again", async () => {
    const retried: string[] = [];
    mockFetch(routes(progress({ status: "failed", error: "The model service did not answer for pages 20 to 24." }), {
      "POST /api/runs/5/read/retry": () => {
        retried.push("yes");
        return { status: 202, body: { read: progress({ status: "waiting" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    expect((await screen.findByText("Reading failed")).closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByText("The model service did not answer for pages 20 to 24.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(retried).toEqual(["yes"]));
  });

  it("fills the filing from the suggestion when reading is done", async () => {
    await ready();
    expect(screen.getByLabelText("Company")).toHaveValue("Bukit Indah Services Berhad");
    expect(screen.getByLabelText("Year end")).toHaveValue("2021-12-31");
    expect(screen.getByRole("radio", { name: "MFRS" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Company" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Amounts in")).toHaveValue("RM");
    expect(screen.getByRole("button", { name: "Start run" })).toBeEnabled();
    expect(screen.queryByText("Prior year")).not.toBeInTheDocument();
    expect(screen.queryByText("Reports")).not.toBeInTheDocument();
  });

  it("marks an unsure statement and the notes with the orange dot", async () => {
    await ready();
    const line = (name: string) => screen.getByRole("button", { name }).closest(".line")!;
    expect(within(line("Profit or loss") as HTMLElement).getByRole("img", { name: "Check this" })).toBeInTheDocument();
    expect(within(line("Financial position") as HTMLElement).queryByRole("img", { name: "Check this" })).not.toBeInTheDocument();
    expect(within(line("Notes") as HTMLElement).getByRole("img", { name: "Check this" })).toBeInTheDocument();
    expect(within(line("Notes") as HTMLElement).getByText("2 notes")).toBeInTheDocument();
  });

  it("offers Not printed for comprehensive income and starts it switched off", async () => {
    await ready();
    const layout = screen.getByLabelText("Comprehensive income layout") as HTMLSelectElement;
    expect(layout.value).toBe("NotPrepared");
    expect(Array.from(layout.options).map((o) => o.textContent)).toEqual(["Before tax", "Net of tax", "Not printed"]);
    expect(screen.getByRole("switch", { name: "Comprehensive income" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Financial position" })).toHaveAttribute("aria-checked", "true");
    fireEvent.change(layout, { target: { value: "NetOfTax" } });
    expect(screen.getByRole("switch", { name: "Comprehensive income" })).toHaveAttribute("aria-checked", "true");
  });

  it("offers Retained earnings for changes in equity only under MPERS", async () => {
    await ready();
    const options = () => Array.from((screen.getByLabelText("Changes in equity layout") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options()).toEqual(["Changes in equity"]);
    fireEvent.click(screen.getByRole("radio", { name: "MPERS" }));
    expect(options()).toEqual(["Changes in equity", "Retained earnings"]);
    fireEvent.change(screen.getByLabelText("Changes in equity layout"), { target: { value: "SoRE" } });
    // The statement is then named as printed: a statement of retained earnings.
    expect(screen.getByRole("button", { name: "Retained earnings" })).toBeInTheDocument();
    expect(screen.getByLabelText("Retained earnings layout")).toHaveValue("SoRE");
    fireEvent.click(screen.getByRole("radio", { name: "MFRS" }));
    expect(screen.getByLabelText("Changes in equity layout")).toHaveValue("Default");
  });

  it("shows a statement's page picture, its page number and the Reader's reason", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Profit or loss" }));
    expect(screen.getByText("Page 15 of 37")).toBeInTheDocument();
    expect(screen.getByText("Only income and expenditure are shown.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Profit or loss, page 15" })).toHaveAttribute("src", "/api/runs/5/pages/15/image");
  });

  it("edits the notes list: open points first, then remove, add and replace", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Notes" }));
    expect(screen.getByText("Note 2 is not in the list; find it or say why it is absent.")).toBeInTheDocument();
    expect(screen.queryByText(/The unit rests/)).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();   // the list has no header row
    const titles = () => screen.getAllByRole("row").map((row) => row.children[1].textContent);
    expect(titles()).toEqual(["General information", "Significant accounting policies"]);

    fireEvent.click(screen.getByRole("button", { name: "Remove note 1" }));
    expect(titles()).toEqual(["Significant accounting policies"]);

    const add = screen.getByRole("button", { name: "Add" });
    fireEvent.change(screen.getByLabelText("Note number"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Note title"), { target: { value: "Basis of preparation" } });
    expect(add).toBeDisabled();   // no page yet
    fireEvent.change(screen.getByLabelText("Note pages"), { target: { value: "18" } });
    fireEvent.click(add);
    expect(titles()).toEqual(["Basis of preparation", "Significant accounting policies"]);

    fireEvent.change(screen.getByLabelText("Note number"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Note title"), { target: { value: "Accounting policies" } });
    fireEvent.change(screen.getByLabelText("Note pages"), { target: { value: "19-24" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(titles()).toEqual(["Basis of preparation", "Accounting policies"]);
    expect(screen.getByText("p19–24")).toBeInTheDocument();
  });

  it("sends the confirmed setup and returns to the runs", async () => {
    let sent: unknown = null;
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "POST /api/runs/5/setup": (init) => {
        sent = JSON.parse(String(init?.body));
        return { body: { run: run({ id: 5, status: "ready" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "Bukit Indah" } });
    fireEvent.click(screen.getByRole("radio", { name: "Group" }));
    fireEvent.change(screen.getByLabelText("Amounts in"), { target: { value: "RM'000" } });
    fireEvent.click(screen.getByRole("switch", { name: "Cash flows" }));
    fireEvent.change(screen.getByLabelText("Profit or loss layout"), { target: { value: "Function" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(window.location.hash).toBe("#/runs/5"));
    expect(sent).toEqual({
      company: "Bukit Indah",
      year_end: "2021-12-31",
      standard: "MFRS",
      level: "Group",
      unit: "RM'000",
      statements: [
        { statement: "SOFP", layout: "CuNonCu", included: true, pages: [14] },
        { statement: "SOPL", layout: "Function", included: true, pages: [15] },
        { statement: "SOCI", layout: "NotPrepared", included: false, pages: [] },
        { statement: "SOCIE", layout: "Default", included: true, pages: [16] },
        { statement: "SOCF", layout: "Direct", included: false, pages: [17] },
      ],
      notes_included: true,
      notes: map.notes,
    });
  });

  it("shows the server's refusal when the setup is refused", async () => {
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "POST /api/runs/5/setup": { status: 422, body: { detail: "Switch on at least one statement." } },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Switch on at least one statement.");
    expect(screen.getByText("Not started").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
  });

  it("keeps asking for news after a failed ask and shows the failure until it answers", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let asks = 0;
      mockFetch(routes(progress(), {
        "GET /api/runs/5/read": () => {
          asks += 1;
          return asks === 1 ? { status: 503, body: { detail: "The server is busy." } } : { body: { read: progress() } };
        },
      }));
      render(<SetupPage runId={5} />);
      expect(await screen.findByText("The server is busy.")).toBeInTheDocument();
      expect(screen.getByText("Not updated").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
      await vi.advanceTimersByTimeAsync(3500);
      expect(await screen.findByText("Reading page 22 of 37")).toBeInTheDocument();
      expect(screen.queryByText("The server is busy.")).not.toBeInTheDocument();
      expect(asks).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers Replace when ready or failed, never while reading", async () => {
    mockFetch(routes(progress()));
    const { unmount } = render(<SetupPage runId={5} />);
    await screen.findByText("Reading page 22 of 37");
    expect(screen.queryByRole("button", { name: "Replace" })).not.toBeInTheDocument();
    unmount();
    mockFetch(routes(progress({ status: "failed", error: "Stopped." })));
    render(<SetupPage runId={5} />);
    expect(await screen.findByRole("button", { name: "Replace" })).toBeInTheDocument();
  });

  it("replaces the document: uploads a new run, deletes this one and opens the new setup", async () => {
    const calls: string[] = [];
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "POST /api/runs": () => {
        calls.push("upload");
        return { body: { run: run({ id: 9, status: "reading" }), document } };
      },
      "DELETE /api/runs/5": () => {
        calls.push("delete");
        return { status: 204 };
      },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    const file = new File(["%PDF-1.7"], "Other.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Replacement PDF"), { target: { files: [file] } });
    await waitFor(() => expect(window.location.hash).toBe("#/runs/9/setup"));
    expect(calls).toEqual(["upload", "delete"]);
  });

  it("shows a refused replacement and keeps this run", async () => {
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "POST /api/runs": { status: 422, body: { detail: "This file is not a PDF, so choose the PDF of the financial statements." } },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.change(screen.getByLabelText("Replacement PDF"), { target: { files: [new File(["x"], "x.pdf")] } });
    expect(await screen.findByText("This file is not a PDF, so choose the PDF of the financial statements.")).toBeInTheDocument();
    expect(screen.getByText("Not replaced").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
  });

  it("sets a statement's pages with Other page, checked against the page count", async () => {
    let sent: { statements: { statement: string; pages: number[] }[] } | null = null;
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "POST /api/runs/5/setup": (init) => {
        sent = JSON.parse(String(init?.body));
        return { body: { run: run({ id: 5, status: "ready" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.click(screen.getByRole("button", { name: "Financial position" }));
    fireEvent.click(screen.getByRole("button", { name: "Other page" }));
    const input = screen.getByLabelText("Financial position pages");
    fireEvent.change(input, { target: { value: "38" } });               // the document has 37 pages
    expect(screen.getByRole("button", { name: "Set" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "20-21" } });
    fireEvent.click(screen.getByRole("button", { name: "Set" }));
    expect(screen.getByText("Page 20 of 37")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Financial position, page 20" })).toHaveAttribute("src", "/api/runs/5/pages/20/image");
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.statements.find((s) => s.statement === "SOFP")?.pages).toEqual([20, 21]);
  });

  it("shows a note whose title was not found as Not found with the orange dot", async () => {
    mockFetch(routes(progress({ status: "done", map_saved: true }), {
      "GET /api/runs/5/map": { body: { map: { ...map, notes: [{ number: "7", title: "", first_page: 25, last_page: 25 }] } } },
    }));
    render(<SetupPage runId={5} />);
    await screen.findByRole("heading", { name: "Statements" });
    fireEvent.click(screen.getByRole("button", { name: "Notes" }));
    const row = screen.getByText("Not found").closest("tr")!;
    expect(within(row).getByRole("img", { name: "Check this" })).toBeInTheDocument();
    expect(within(row).getByText("p25").closest("td")).toHaveClass("nw");
  });

  describe("question cards", () => {
    const cards: SuggestedSetup["questions"] = [
      {
        field: "unit", statement: null, question: "Are the amounts in RM or RM thousands?", reason: "No unit is printed above the statements.", pages: [7],
        choices: [
          { value: "RM", label: "RM", effect: "Figures are filed as printed, in RM", suggested: true },
          { value: "RM'000", label: "RM thousands", effect: "Figures are filed as printed, in RM thousands", suggested: false },
        ],
      },
      {
        field: "layout", statement: "SOPL", question: "Which layout does the statement of profit or loss use?", reason: "Only income and expenditure are shown.", pages: [15],
        choices: [
          { value: "Function", label: "By function", layout: "Function", included: true, effect: "", suggested: false },
          { value: "Nature", label: "By nature", layout: "Nature", included: true, effect: "", suggested: true },
          { value: null, label: "Not printed", layout: "Nature", included: false, effect: "", suggested: false },
        ],
      },
    ];
    const asked = async () => {
      mockFetch(routes(progress({ status: "done", map_saved: true }), { "GET /api/runs/5/setup": { body: { setup: { ...setup, questions: cards } } } }));
      render(<SetupPage runId={5} />);
      await screen.findByRole("heading", { name: "Statements" });
    };

    it("asks each card in turn, locking its field and Start run until answered", async () => {
      await asked();
      expect(screen.getByRole("heading", { name: "Are the amounts in RM or RM thousands?" })).toBeInTheDocument();
      expect(screen.getByLabelText("Amounts in")).toBeDisabled();
      expect(screen.getByLabelText("Profit or loss layout")).toBeDisabled();
      expect(screen.getByLabelText("Financial position layout")).toBeEnabled();
      expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();

      fireEvent.click(screen.getByRole("button", { name: /RM thousands/ }));
      expect(screen.getByLabelText("Amounts in")).toHaveValue("RM'000");
      expect(screen.getByLabelText("Amounts in")).toBeEnabled();
      expect(screen.getByRole("heading", { name: "Which layout does the statement of profit or loss use?" })).toBeInTheDocument();

      fireEvent.keyDown(window.document.body, { key: "3" });
      expect(screen.getByLabelText("Profit or loss layout")).toHaveValue("Nature");
      expect(screen.getByRole("switch", { name: "Profit or loss" })).toHaveAttribute("aria-checked", "false");
      expect(screen.queryByRole("heading", { name: /Which layout/ })).toBeNull();
      expect(screen.getByRole("button", { name: "Start run" })).toBeEnabled();
    });

    it("opens the page a card's reason points to", async () => {
      await asked();
      fireEvent.click(screen.getByRole("button", { name: "Page 7" }));
      expect(screen.getByRole("dialog", { name: "Page 7" })).toBeInTheDocument();
    });

    it("leaves the field to the person when they answer in their own words", async () => {
      await asked();
      fireEvent.change(screen.getByLabelText("Something else"), { target: { value: "Check with the partner" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      expect(screen.getByLabelText("Amounts in")).toBeEnabled();
      expect(screen.getByLabelText("Amounts in")).toHaveValue("RM");
    });
  });

  describe("guidance for the suggested company", () => {
    const g = (lines: string[]) => ({ company_id: 4, version: 1, lines, saved_by: "a", saved_at: "2026-11-22T09:00:00Z", source: "typed", comment_id: null, restored_from: null });

    it("shows the company's guidance when the suggested name is a company already known", async () => {
      mockFetch(routes(progress({ status: "done", map_saved: true }), {
        "GET /api/runs/5/guidance": { body: { firm: g([]), company: g(["Goods in transit are part of inventories."]), company_id: 4, company_from_suggestion: true } },
        "GET /api/companies/4/guidance": { body: { company: { id: 4, name: "Bukit Indah" }, guidance: g(["Goods in transit are part of inventories."]), versions: [] } },
      }));
      render(<SetupPage runId={5} />);
      expect(await screen.findByRole("heading", { name: "Guidance for this company" })).toBeInTheDocument();
      expect(await screen.findByText("Goods in transit are part of inventories.")).toBeInTheDocument();
    });

    it("shows no guidance panel for a company not seen before", async () => {
      mockFetch(routes(progress({ status: "done", map_saved: true }), {
        "GET /api/runs/5/guidance": { body: { firm: g([]), company: null, company_id: null, company_from_suggestion: false } },
      }));
      render(<SetupPage runId={5} />);
      await screen.findByRole("heading", { name: "Statements" });
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(screen.queryByRole("heading", { name: "Guidance for this company" })).toBeNull();
    });
  });
});
