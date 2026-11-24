import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Comment, Round, RunDetail, RunEvent } from "../../api";
import { admin, mockFetch, run, type Reply } from "../../test-utils";
import { checks, comment, event, guidance, needs, report, round, runDetail, scopeQuestion, sofp } from "./fixtures";
import { NavSlot } from "../../components/AppShell";
import { RunPage } from "./RunPage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

type Handler = Reply | ((init: RequestInit | undefined) => Reply);

type Over = { accept_all?: { round_id: number | null; comment_ids: number[] }; status?: string; comments?: Comment[]; rounds?: Round[]; events?: RunEvent[]; failed_stage?: "read" | "extract" | null; detail?: Partial<RunDetail> };

function routes({ accept_all, status = "in_review", comments = [], rounds = [], events = [], failed_stage = null, detail = {} }: Over = {}, extra: Record<string, Handler> = {}) {
  return {
    "GET /api/runs/1": { body: { run: runDetail({ status: status as never, failed_stage, ...detail }) } },
    "GET /api/runs/1/statements/SOFP": { body: sofp },
    "GET /api/runs/1/checks": { body: { checks } },
    "GET /api/runs/1/needs-you": { body: needs },
    "GET /api/runs/1/comments": { body: { comments } },
    "GET /api/runs/1/rounds": { body: { rounds, accept_all: accept_all ?? { round_id: rounds.length ? rounds[rounds.length - 1].id : null, comment_ids: [] } } },
    "GET /api/runs/1/rounds/2": { body: { round: rounds[0] ?? round(), report } },
    "GET /api/runs/1/events": { body: { events, last_id: events.length ? events[events.length - 1].id : 0, has_more: false } },
    "GET /api/runs/1/question": { body: { question: null } },
    "GET /api/runs/1/questions": { body: { questions: [] } },
    "GET /api/runs/1/notes": { body: { notes: [] } },
    "GET /api/runs/1/notes/fields": { body: { fields: [] } },
    "GET /api/runs/1/notes/reports": { body: { reports: [] } },
    ...extra,
  };
}

const posts = (fetch: ReturnType<typeof mockFetch>, path: string) =>
  fetch.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url) === path).map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : null));

const tab = (name: string) => screen.getByRole("tab", { name: new RegExp(`^${name}`) });

async function openCell(name: string) {
  fireEvent.click(await screen.findByRole("button", { name }));
  expect(tab("Source")).toHaveAttribute("aria-selected", "true");
}

describe("Run screen", () => {
  it("shows the company in the header and the statement as a grid", async () => {
    mockFetch(routes());
    render(<RunPage runId={1} user={admin} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Seri Maju Trading Sdn. Bhd." })).toBeInTheDocument();
    expect(await screen.findByText("Filed as Cash and cash equivalents")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Other payables and accruals, Last year" })).toHaveTextContent("389,200");
    expect(screen.getByText("Does not tally").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByRole("button", { name: "Download traces" })).toBeInTheDocument();
  });

  it("lists what needs a person, ends with the passed count, and opens an item's figure", async () => {
    mockFetch(routes());
    render(<RunPage runId={1} user={admin} />);
    expect(await screen.findByText("214 other figures passed their checks")).toBeInTheDocument();
    expect(tab("Needs you")).toHaveTextContent("3");
    expect(screen.getByText("Check failed")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Other receivables, this year"));
    expect(tab("Source")).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: "Other receivables, deposits and prepayments, This year" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Note 11 includes 42,000 due from a director.")).toBeInTheDocument();
  });

  it("shows each alike line and accepts them all at once", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/needs-you/alike/accept": { body: { items: needs.items.slice(0, 2), passed: 215 } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Show each" }));
    expect(within(document.querySelector(".alike") as HTMLElement).getByRole("button", { name: /Cash and bank balances/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept all" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/needs-you/alike/accept")).toHaveLength(1));
  });

  it("says nothing needs you while the agent extracts", async () => {
    mockFetch(routes({ status: "extracting", events: [event(1, "Extraction is queued: the balance sheet.")] }));
    render(<RunPage runId={1} user={admin} />);
    expect(await screen.findByText("Extraction is queued: the balance sheet.")).toBeInTheDocument();
    fireEvent.click(tab("Needs you"));
    expect(screen.getByText("Shown when the agent finishes")).toBeInTheDocument();
  });

  it("confirms a figure when the person says it is right", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/figures/31/confirm": { body: { figure: {} } } }));
    render(<RunPage runId={1} user={admin} />);
    await openCell("Other payables and accruals, Last year");
    fireEvent.click(screen.getByRole("radio", { name: "Right" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/figures/31/confirm")).toHaveLength(1));
  });

  it("sends a Wrong comment with the scope the person chose", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/comments": { status: 201, body: { comment: comment() } } }));
    render(<RunPage runId={1} user={admin} />);
    await openCell("Other payables and accruals, Last year");
    expect(screen.queryByLabelText("Comment for the agent")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Wrong" }));
    expect(screen.getByLabelText("Comment for the agent")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Recheck" }));
    fireEvent.click(screen.getByRole("radio", { name: "Company" }));
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments")).toEqual([{ target: { kind: "figure", figure_id: 31 }, text: "Recheck", scope: "company" }]));
  });

  it("comments on the statement as a whole, with no scope", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/comments": { status: 201, body: { comment: comment() } } }));
    render(<RunPage runId={1} user={admin} />);
    await screen.findByText("214 other figures passed their checks");
    fireEvent.click(tab("Source"));
    expect(screen.queryByRole("radiogroup", { name: "Apply to" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Comment for the agent"), { target: { value: "Recheck the whole page." } });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments")).toEqual([{ target: { kind: "statement", statement: "SOFP" }, text: "Recheck the whole page." }]));
  });

  it("shows a refused comment's sentence beside the comment box", async () => {
    mockFetch(routes({}, { "POST /api/runs/1/comments": { status: 422, body: { detail: "Comments on Group figures arrive with the Group columns, in a later step." } } }));
    render(<RunPage runId={1} user={admin} />);
    await openCell("Other payables and accruals, Last year");
    fireEvent.click(screen.getByRole("radio", { name: "Wrong" }));
    fireEvent.change(screen.getByLabelText("Comment for the agent"), { target: { value: "Recheck" } });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Comments on Group figures arrive with the Group columns, in a later step.");
    expect(alert.closest(".bar")).toContainElement(screen.getByRole("button", { name: "Add comment" }));
    expect(screen.getByLabelText("Comment for the agent")).toHaveValue("Recheck");
  });

  it("comments on a whole line with a scope", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/comments": { status: 201, body: { comment: comment() } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Cash and bank balances\s*Filed as/ }));
    fireEvent.change(screen.getByLabelText("Comment for the agent"), { target: { value: "Split this line." } });
    fireEvent.click(screen.getByRole("radio", { name: "Run" }));
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments")).toHaveLength(1));
    expect(posts(fetch, "/api/runs/1/comments")[0]).toEqual({ target: { kind: "line", statement: "SOFP", concept_uuid: "cash", entity_scope: "Company" }, text: "Split this line.", scope: "run" });
  });

  it("sends the open comments as one round", async () => {
    const fetch = mockFetch(routes({ comments: [comment(), comment({ id: 5, text: "Recheck" })] }, { "POST /api/runs/1/rounds": { status: 202, body: { round: round({ status: "sent" }) } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Send 2 comments" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/rounds")).toHaveLength(1));
    expect(typeof posts(fetch, "/api/runs/1/rounds")[0].client_id).toBe("string");
  });

  it("offers Stop while a round works", async () => {
    const fetch = mockFetch(routes({ status: "correcting", rounds: [round({ status: "working" })], comments: [comment({ status: "sent" })] }, { "POST /api/runs/1/rounds/2/stop": { body: { round: round({ status: "stopped" }) } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/rounds/2/stop")).toHaveLength(1));
  });

  it("shows a round's outcomes and calls Undo and Accept", async () => {
    const answered = [
      comment({ status: "answered", outcome: "changed", answer: "Used 398,200 as page 7 prints.", round_id: 2 }),
      comment({ id: 6, status: "answered", outcome: "not_changed", answer: "Page 7 prints this figure as shown.", round_id: 2, text: "Recheck cash" }),
    ];
    const fetch = mockFetch(
      routes({ comments: answered, rounds: [round()], accept_all: { round_id: 2, comment_ids: [4, 6] } }, {
        "POST /api/runs/1/comments/4/undo": { body: { comments: [], figures: [] } },
        "POST /api/runs/1/comments/6/accept": { body: { comment: answered[1] } },
        "POST /api/runs/1/comments/accept-all": { body: { comments: answered } },
      }),
    );
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
    expect(await screen.findByText("Used page 7's payables.")).toBeInTheDocument();
    expect(screen.getByText(/Changed 1 of 2 commented items\. 1 other figure changed:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Total current liabilities, last year" })).toBeInTheDocument();
    expect(screen.getByText("Not changed")).toBeInTheDocument();
    expect(screen.getByText("389,200", { selector: "s" }).closest("p")).toHaveTextContent("389,200 to 398,200");
    expect(screen.getByText("certainty sure → unsure, reason changed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/4/undo")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/6/accept")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Accept all" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/accept-all")).toHaveLength(1));
  });

  it("replies to the agent's question", async () => {
    const asked = comment({ id: 5, status: "answered", outcome: "question", answer: "Which lines should change?", round_id: 2, target: { ...comment().target, kind: "statement", concept_uuid: null, period: null, field_label: null, figure_id: null } });
    const fetch = mockFetch(routes({ comments: [asked], rounds: [round()] }, { "POST /api/runs/1/comments/5/reply": { body: { comment: { ...asked, status: "open" } } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
    expect(await screen.findByText("Question")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept all" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "The payables lines." } });
    fireEvent.click(screen.getByRole("button", { name: "Reply" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/5/reply")).toEqual([{ text: "The payables lines." }]));
  });

  it("folds a finished run's activity into one line and unfolds it", async () => {
    const events = [event(1, "Mapped 48 pages."), event(2, "Step 1 of at most 40.", { kind: "step" }), event(3, "Read page 7.", { pages: [7] }), event(4, "Saved 12 figure(s)."), event(10, "Extraction is finished.")];
    mockFetch(routes({ events }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    const fold = await screen.findByRole("button", { name: /Worked through 4 steps/ });
    expect(fold).toHaveTextContent("00:09");
    expect(screen.queryByText("Read page 7.")).toBeNull();
    fireEvent.click(fold);
    expect(screen.getByText("Read page 7.")).toBeInTheDocument();
    expect(screen.queryByText("Step 1 of at most 40.")).toBeNull();
    // Chips come from the event's pages, not from its wording.
    expect(screen.getAllByRole("button", { name: /^Page / })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Page 7" }));
    expect(screen.getByRole("dialog", { name: "Page 7" })).toBeInTheDocument();
  });

  it("does not fold three lines or fewer", async () => {
    mockFetch(routes({ events: [event(1, "Mapped 48 pages."), event(2, "Read page 7.")] }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    expect(await screen.findByText("Read page 7.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Worked through/ })).toBeNull();
  });

  it("shows a failed extraction and tries again", async () => {
    const fetch = mockFetch(
      routes({ status: "failed", failed_stage: "extract", detail: { failure: { stage: "extract", sentence: "No figure was saved. The model did not answer." } } }, {
        "POST /api/runs/1/extract/retry": { status: 202, body: { run: run({ id: 1, status: "ready" }) } },
      }),
    );
    render(<RunPage runId={1} user={admin} />);
    expect((await screen.findByText("Extraction failed")).closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByText("No figure was saved. The model did not answer.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/extract/retry")).toHaveLength(1));
  });

  it("stops extraction from the header and tries again once it has stopped", async () => {
    const fetch = mockFetch(routes({ status: "extracting" }, { "POST /api/runs/1/extract/stop": { status: 202, body: { run: run({ id: 1, status: "extracting" }) } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/extract/stop")).toHaveLength(1));
  });

  it("shows a stopped extraction in review and tries again from it", async () => {
    const stage = { name: "extract", status: "stopped", started_at: null, finished_at: null, error: "Stopped on request; the figures saved so far are kept." };
    const fetch = mockFetch(routes({ detail: { stages: [stage] } }, { "POST /api/runs/1/extract/retry": { status: 202, body: { run: run({ id: 1, status: "ready" }) } } }));
    render(<RunPage runId={1} user={admin} />);
    expect(await screen.findByText("Extraction stopped")).toBeInTheDocument();
    expect(screen.getByText("Stopped on request; the figures saved so far are kept.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/extract/retry")).toHaveLength(1));
  });

  it("offers Try again beside the main action when the notes or reports agent failed after the figures finished", async () => {
    const done = { name: "extract", status: "done", started_at: null, finished_at: null, error: null };
    const notes = { name: "notes", status: "failed", started_at: null, finished_at: null, error: "The model gateway did not answer." };
    const fetch = mockFetch(routes({ detail: { stages: [done, notes] } }, { "POST /api/runs/1/extract/retry": { status: 202, body: { run: run({ id: 1, status: "ready" }) } } }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(screen.getByRole("button", { name: "Prepare mTool file" })).toBeInTheDocument();
    await waitFor(() => expect(posts(fetch, "/api/runs/1/extract/retry")).toHaveLength(1));
  });

  it("puts the spinner on the statement the agent is working on", async () => {
    mockFetch(routes({ status: "extracting", detail: { working_on: "SOFP" } }));
    const slot = document.createElement("div");
    document.body.appendChild(slot);
    render(
      <NavSlot.Provider value={slot}>
        <RunPage runId={1} user={admin} />
      </NavSlot.Provider>,
    );
    const link = await within(slot).findByRole("button", { name: /Financial position/ });
    expect(link.querySelector(".spin")).not.toBeNull();
    expect(within(slot).getByRole("button", { name: /Checks/ }).querySelector(".spin")).toBeNull();
    slot.remove();
  });

  it("offers Accept all only for what the server says it would accept", async () => {
    const answered = comment({ id: 4, status: "answered", outcome: "changed", answer: "Used 398,200.", round_id: 1 });
    const header = () => within(document.querySelector(".page-header") as HTMLElement);
    mockFetch(routes({ comments: [answered], rounds: [round()], accept_all: { round_id: 2, comment_ids: [] } }));
    const { unmount } = render(<RunPage runId={1} user={admin} />);
    await screen.findByText("214 other figures passed their checks");
    expect(header().queryByRole("button", { name: "Accept all" })).toBeNull();
    unmount();
    const fetch = mockFetch(routes({ comments: [answered], rounds: [round()], accept_all: { round_id: 2, comment_ids: [4] } }, { "POST /api/runs/1/comments/accept-all": { body: { comments: [answered] } } }));
    render(<RunPage runId={1} user={admin} />);
    await waitFor(() => expect(header().getByRole("button", { name: "Accept all" })).toBeInTheDocument());
    fireEvent.click(header().getByRole("button", { name: "Accept all" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/accept-all")).toHaveLength(1));
  });

  it("asks for events without the loop's own rows, and shows a look at the pages in the agent's words", async () => {
    const fetch = mockFetch(routes({ events: [event(1, "Checking the payables against note 14.", { kind: "looked", source: "reviewer", pages: [7, 21] })] }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    const line = (await screen.findByText("Checking the payables against note 14.")).closest(".fl") as HTMLElement;
    expect(within(line).getByRole("button", { name: "Page 7" })).toBeInTheDocument();
    expect(within(line).getByRole("button", { name: "Page 21" })).toBeInTheDocument();
    const reads = fetch.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/events"));
    expect(reads.every((u) => u.includes("hide_internal=true"))).toBe(true);
  });

  it("shows a stopped round with a plain dot, not the failure label", async () => {
    mockFetch(routes({ comments: [comment({ status: "open" })], rounds: [round({ status: "stopped", summary: null, error: "Stopped on request." })] }));
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
    expect((await screen.findByText("Stopped")).closest("[data-kind]")).toHaveAttribute("data-kind", "neutral");
    expect(screen.queryByText("Round failed")).toBeNull();
  });

  it("says it is loading the run, then what needs you", async () => {
    let answer: (value: Response) => void = () => {};
    const fetch = mockFetch(routes());
    const real = fetch.getMockImplementation()!;
    const needsYou = new Promise<Response>((resolve) => (answer = resolve));
    fetch.mockImplementation((input, init) => (String(input) === "/api/runs/1/needs-you" ? needsYou : real(input, init)));
    render(<RunPage runId={1} user={admin} />);
    expect(screen.getByRole("heading", { name: "Loading run" })).toBeInTheDocument();
    expect(await screen.findByText("Loading what needs you")).toBeInTheDocument();
    answer(new Response(JSON.stringify(needs), { status: 200, headers: { "Content-Type": "application/json" } }));
    expect(await screen.findByText("214 other figures passed their checks")).toBeInTheDocument();
  });

  it("reads every page of events, 500 at a time, with no cap", async () => {
    const afters: string[] = [];
    mockFetch(
      routes({}, {
        "GET /api/runs/1/events": () => {
          afters.push("x");
          const n = afters.length;
          return { body: { events: n <= 25 ? [event(n, `Step ${n}.`)] : [], last_id: Math.min(n, 25), has_more: n < 25 } };
        },
      }),
    );
    const fetch = vi.mocked(globalThis.fetch);
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    await screen.findByRole("button", { name: /Worked through 25 steps/ });
    const urls = fetch.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/events"));
    expect(urls[0]).toContain("limit=500");
    expect(urls[1]).toContain("after_id=1");
  });

  it("loads the closing lines when the run stops being busy", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let done = false;
    mockFetch(
      routes({ status: "extracting" }, {
        "GET /api/runs/1": () => ({ body: { run: runDetail({ status: done ? "in_review" : "extracting" }) } }),
        "GET /api/runs/1/events": () => ({ body: done ? { events: [event(9, "Extraction is finished. The run is ready for review.", { kind: "notice" })], last_id: 9, has_more: false } : { events: [], last_id: 0, has_more: false } }),
      }),
    );
    render(<RunPage runId={1} user={admin} />);
    await screen.findByRole("heading", { level: 1, name: "Seri Maju Trading Sdn. Bhd." });
    done = true;
    // The poll's own read finds nothing new; the run read after it says the stage ended.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    fireEvent.click(screen.getByRole("tab", { name: "Activity" }));
    expect(await screen.findByText("Extraction is finished. The run is ready for review.")).toBeInTheDocument();
  });

  it("asks rarely while extraction waits for an answer, and not at all while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetch = mockFetch(routes({ status: "needs_answer" }));
    render(<RunPage runId={1} user={admin} />);
    await screen.findByRole("heading", { level: 1, name: "Seri Maju Trading Sdn. Bhd." });
    const reads = () => fetch.mock.calls.filter(([u]) => String(u).includes("/events")).length;
    const before = reads();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(reads()).toBe(before);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(reads()).toBe(before);
    hidden.mockReturnValue(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(reads()).toBeGreaterThan(before);
    hidden.mockRestore();
  });

  describe("adding a figure the agent missed", () => {
    const blankCell = { figure_id: null, concept_uuid: "ip", value: null, printed: null, stated: null, certainty: "sure" as const, reason: "", edited: false, origin: null, writable: true, agent_writable: true, lines_sum: null };
    const template = {
      ...sofp,
      order: "template" as const,
      rows: [
        ...sofp.rows,
        { ...sofp.rows[2], label: "Investment property", field_label: "Investment property", printed_label: null, concept_uuid: "ip", page: null, print_order: null, status: null, certainty: "sure" as const, reason: "", cells: { "Company:CY": blankCell, "Company:PY": blankCell } },
      ],
    };

    it("asks for the page and sends it with the amount", async () => {
      const fetch = mockFetch(routes({}, { "GET /api/runs/1/statements/SOFP": { body: template }, "POST /api/runs/1/figures": { body: { figure: {} } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("button", { name: "Investment property, This year" }));
      const amount = screen.getByRole("textbox", { name: "Investment property, This year" });
      fireEvent.change(amount, { target: { value: "1,250,000" } });
      // Leaving the amount does not save it: it waits for its page.
      fireEvent.blur(amount);
      expect(posts(fetch, "/api/runs/1/figures")).toHaveLength(0);
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(screen.queryByRole("button", { name: "Save" })).toBeDisabled();
      fireEvent.change(screen.getByLabelText("Page"), { target: { value: "7" } });
      fireEvent.change(screen.getByLabelText("Printed as"), { target: { value: "Investment properties" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(posts(fetch, "/api/runs/1/figures")).toEqual([
          { concept_uuid: "ip", period: "CY", entity_scope: "Company", value: 1250000, page: 7, printed_label: "Investment properties" },
        ]),
      );
    });

    it("shows the store's refusal beside the amount", async () => {
      mockFetch(routes({}, { "GET /api/runs/1/statements/SOFP": { body: template }, "POST /api/runs/1/figures": { status: 422, body: { detail: "Give the page and the line as printed for this figure, because every figure needs its source." } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("button", { name: "Investment property, This year" }));
      fireEvent.change(screen.getByRole("textbox", { name: "Investment property, This year" }), { target: { value: "5" } });
      fireEvent.change(screen.getByLabelText("Page"), { target: { value: "7" } });
      fireEvent.keyDown(screen.getByLabelText("Page"), { key: "Enter" });
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("every figure needs its source");
      expect(alert.closest(".det")).toContainElement(screen.getByRole("textbox", { name: "Investment property, This year" }));
    });
  });

  it("offers the mTool file once review has nothing waiting, and not while the agent works", async () => {
    mockFetch(routes({}, { "GET /api/runs/1/fills": { body: { fills: [] } } }));
    const { unmount } = render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Prepare mTool file" }));
    expect(screen.getByRole("dialog", { name: "Prepare mTool file" })).toBeInTheDocument();
    unmount();
    mockFetch(routes({ status: "extracting" }));
    render(<RunPage runId={1} user={admin} />);
    await screen.findByRole("button", { name: "Stop" });
    expect(screen.queryByRole("button", { name: "Prepare mTool file" })).toBeNull();
  });

  it("downloads the traces with the PDF when the switch is on", async () => {
    const fetch = mockFetch(routes({}, { "GET /api/runs/1/traces": { body: {} } }));
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Download traces" }));
    const dialog = screen.getByRole("dialog", { name: "Download traces" });
    fireEvent.click(within(dialog).getByRole("switch", { name: "Include the uploaded PDF" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Download" }));
    await waitFor(() => expect(fetch.mock.calls.map(([u]) => String(u))).toContain("/api/runs/1/traces?include_pdf=1"));
    click.mockRestore();
  });

  it("asks for news while the agent works and fills in new figures", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let page = 0;
    const fetch = mockFetch(
      routes({ status: "extracting" }, {
        "GET /api/runs/1/events": () => {
          page += 1;
          return { body: page < 2 ? { events: [], last_id: 0, has_more: false } : { events: [event(5, "Saved 1 figure(s).", { kind: "saved" })], last_id: 5, has_more: false } };
        },
      }),
    );
    render(<RunPage runId={1} user={admin} />);
    await screen.findByRole("heading", { level: 1 });
    const reads = () => fetch.mock.calls.filter(([u]) => String(u).startsWith("/api/runs/1/statements/SOFP?order=report")).length;
    const before = reads();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    await waitFor(() => expect(screen.getByText("Saved 1 figure(s).")).toBeInTheDocument());
    expect(reads()).toBeGreaterThan(before);
  });

  describe("a scope question", () => {
    const asking = (extra: Record<string, Handler> = {}) =>
      routes({ status: "needs_answer", events: [event(1, "Stopped to ask about the standard.", { kind: "asked", source: "figures" })] }, {
        "GET /api/runs/1/question": { body: { question: scopeQuestion() } },
        "GET /api/runs/1/questions": { body: { questions: [scopeQuestion()] } },
        ...extra,
      });

    it("shows the card above the grid, with no Send, and opens an evidence page", async () => {
      mockFetch(asking());
      render(<RunPage runId={1} user={admin} />);
      expect(await screen.findByRole("heading", { name: "This looks like an MPERS filing. Which standard applies?" })).toBeInTheDocument();
      expect(screen.getByText("Suggested").closest("button")).toHaveTextContent("MPERS");
      expect(screen.queryByRole("button", { name: /^Send \d/ })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Page 3" }));
      expect(screen.getByRole("dialog", { name: "Page 3" })).toBeInTheDocument();
    });

    it("answers with a choice, by click or by its number key", async () => {
      const fetch = mockFetch(asking({ "POST /api/runs/1/question/answer": { body: { question: scopeQuestion({ status: "answered" }), run: run({ id: 1, status: "ready" }) } } }));
      render(<RunPage runId={1} user={admin} />);
      await screen.findByRole("heading", { name: /Which standard applies/ });
      fireEvent.keyDown(document.body, { key: "2" });
      await waitFor(() => expect(posts(fetch, "/api/runs/1/question/answer")).toEqual([{ choice: 1, question_id: 3 }]));
    });

    it("answers in the person's own words", async () => {
      const fetch = mockFetch(asking({ "POST /api/runs/1/question/answer": { body: { question: scopeQuestion({ status: "answered" }), run: run({ id: 1, status: "ready" }) } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.change(await screen.findByLabelText("Something else"), { target: { value: "MFRS, the auditors' report is wrong." } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => expect(posts(fetch, "/api/runs/1/question/answer")).toEqual([{ text: "MFRS, the auditors' report is wrong.", question_id: 3 }]));
    });

    it("shows a refused answer's sentence under the card", async () => {
      mockFetch(asking({ "POST /api/runs/1/question/answer": { status: 409, body: { detail: "This question is already answered." } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("button", { name: /MFRS, as set up/ }));
      expect(await screen.findByText("This question is already answered.")).toBeInTheDocument();
    });

    it("shows an answered question in Activity as the question and the answer", async () => {
      const done = scopeQuestion({ status: "answered", answer: { choice: 0, text: null, value: "MPERS", setup_changed: true, cleared: 12, by: "aina@firm.my", at: "2026-11-22T09:01:00Z" } });
      mockFetch(
        routes({ events: [event(1, "Stopped to ask about the standard.", { kind: "asked", question_id: 3 }), event(2, "aina@firm.my answered the question about the standard with MPERS.", { kind: "answered", question_id: 3 })] }, {
          "GET /api/runs/1/questions": { body: { questions: [done] } },
        }),
      );
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
      const qa = (await screen.findByText(done.question)).closest(".qa")!;
      expect(qa).toHaveTextContent("MPERS");
      expect(screen.queryByText(/answered the question about the standard/)).toBeNull();
    });
  });

  describe("a proposed guidance line", () => {
    it("still shows the card, with the sentence, when the company guidance cannot be read", async () => {
      const line = comment({ status: "answered", outcome: "changed", scope: "company", round_id: 2, proposed_guidance: "A line." });
      mockFetch(routes({ comments: [line], rounds: [round()] }, { "GET /api/runs/1/guidance": { status: 500, body: { detail: "The guidance could not be read." } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
      expect(await screen.findByRole("heading", { name: "Add to guidance for this company?" })).toBeInTheDocument();
      expect(screen.getByText("The guidance could not be read.")).toBeInTheDocument();
    });

    const proposed = comment({ status: "answered", outcome: "changed", answer: "Moved it.", scope: "company", round_id: 2, proposed_guidance: "Amounts due from a director go under related parties." });
    const company = (lines: string[], version: number) => ({ "GET /api/runs/1/guidance": { body: { firm: guidance([], 0, null), company: guidance(lines, version), company_id: 4 } } });

    it("adds the line to the company's guidance", async () => {
      const fetch = mockFetch(routes({ comments: [proposed], rounds: [round()] }, { ...company([], 2), "POST /api/runs/1/comments/4/guidance": { body: { guidance: guidance([proposed.proposed_guidance!], 3), versions: [], comment: proposed } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
      expect(await screen.findByRole("heading", { name: "Add to guidance for this company?" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Add to guidance" }));
      await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/4/guidance")).toEqual([{ based_on: 2 }]));
    });

    it("keeps the correction to this run only", async () => {
      const fetch = mockFetch(routes({ comments: [proposed], rounds: [round()] }, { ...company([], 2), "POST /api/runs/1/comments/4/guidance/dismiss": { body: { comment: { ...proposed, guidance_status: "dismissed" } } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
      fireEvent.click(await screen.findByRole("button", { name: "This run only" }));
      await waitFor(() => expect(posts(fetch, "/api/runs/1/comments/4/guidance/dismiss")).toHaveLength(1));
    });

    it("after undoing a change whose line was added, says the line stays and offers to take it out", async () => {
      const added = { ...proposed, guidance_status: "added" as const, guidance_version: 3 };
      let undone = false;
      const fetch = mockFetch(
        routes({ rounds: [round()] }, {
          ...company([proposed.proposed_guidance!], 3),
          "GET /api/runs/1/comments": () => ({ body: { comments: [undone ? { ...added, status: "undone" } : added] } }),
          "POST /api/runs/1/comments/4/undo": () => {
            undone = true;
            return { body: { comments: [{ ...added, status: "undone" }], figures: [], guidance_line_kept: [{ comment_id: 4, company_id: 4, version: 3 }] } };
          },
          "POST /api/companies/4/guidance/restore": { body: { guidance: guidance([], 4), versions: [] } },
        }),
      );
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
      const card = (await screen.findByText("Page 7 prints 398,200 for last year.")).closest(".cm") as HTMLElement;
      fireEvent.click(within(card).getByRole("button", { name: "Undo" }));
      expect(await screen.findByText("This change was undone, but its line is still in the company's guidance")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Undo guidance line" }));
      await waitFor(() => expect(posts(fetch, "/api/companies/4/guidance/restore")).toEqual([{ version: 2, based_on: 3 }]));
    });

    it("says the line was added, and Undo restores the version before it", async () => {
      const added = { ...proposed, guidance_status: "added" as const, guidance_version: 3 };
      const fetch = mockFetch(routes({ comments: [added], rounds: [round()] }, { ...company([proposed.proposed_guidance!], 3), "POST /api/companies/4/guidance/restore": { body: { guidance: guidance([], 4), versions: [] } } }));
      render(<RunPage runId={1} user={admin} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^Comments/ }));
      expect(await screen.findByText("Added to guidance for this company")).toBeInTheDocument();
      fireEvent.click(screen.getAllByRole("button", { name: "Undo" })[0]);
      await waitFor(() => expect(posts(fetch, "/api/companies/4/guidance/restore")).toEqual([{ version: 2, based_on: 3 }]));
    });
  });

  it("shows where an imported figure came from and keeps the workbook's sign when a person says so", async () => {
    const rows = sofp.rows.map((r) =>
      r.concept_uuid === "opay"
        ? { ...r, cells: { ...r.cells, "Company:PY": { ...r.cells["Company:PY"], origin: "prior_workbook", writable: false, certainty: "unsure" as const, reason: "The report prints 389,200 and the workbook holds -389,200: only the sign differs.", sign_question: true, comparison: { report_value: 389200, page: 13, open: true }, value: -389200 } } }
        : r,
    );
    const fetch = mockFetch(routes({}, { "GET /api/runs/1/statements/SOFP": { body: { ...sofp, rows } }, "POST /api/runs/1/figures/31/confirm": { body: { figure: {} } } }));
    render(<RunPage runId={1} user={admin} />);
    await openCell("Other payables and accruals, Last year");
    expect(screen.getByText("Needs a person").closest("[data-kind]")).toHaveAttribute("data-kind", "attention");
    expect(screen.getByText("Kept as filed in last year's workbook.")).toBeInTheDocument();
    expect(screen.getByText("Report, page 13").nextSibling).toHaveTextContent("389,200");
    fireEvent.click(screen.getByRole("button", { name: "Keep the workbook's" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/figures/31/confirm")).toHaveLength(1));
  });

  it("lists the three reports in the sidebar and opens a report's fields", async () => {
    const field = { report: "DIRECTORS_REPORT", field_id: "DIR-3", element_id: "x", label: "Name of first director who signed", kind: "text", choices: [], row: 3, status: "unsure", value: "Lim Wei Ming", reason: "The signature is faint.", pages: [7], revision: 1, updated_by: "reports", actor_kind: "agent", updated_at: null };
    const reports = ["DIRECTORS_REPORT", "STATEMENT_BY_DIRECTORS", "AUDITORS_REPORT"].map((code, i) => ({
      report: code, name: ["Directors' report", "Statement by directors", "Auditors' report"][i], sheet: "S", fields: i === 0 ? [field] : [], assessed: 1, total: 22,
    }));
    mockFetch(routes({}, { "GET /api/runs/1/reports": { body: { stage: { status: "done", error: null }, reports } } }));
    const slot = document.createElement("nav");
    document.body.appendChild(slot);
    render(
      <NavSlot.Provider value={slot}>
        <RunPage runId={1} user={admin} />
      </NavSlot.Provider>,
    );
    const link = await within(slot).findByRole("button", { name: /^Directors' report/ });
    expect(link).toHaveTextContent("1");
    expect(within(slot).getByRole("button", { name: /^Auditors' report/ })).toBeInTheDocument();
    fireEvent.click(link);
    fireEvent.click(await screen.findByRole("button", { name: "Name of first director who signed" }));
    expect(tab("Source")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("The signature is faint.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name of first director who signed" })).toHaveValue("Lim Wei Ming");
    slot.remove();
  });
});
