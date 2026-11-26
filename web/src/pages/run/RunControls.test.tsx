import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RedoPreview, RunCost, RunDetail } from "../../api";
import { admin, mockFetch, type Reply } from "../../test-utils";
import { CostFold } from "./CostFold";
import { checks, event, needs, runDetail, sofp } from "./fixtures";
import { RedoDialog } from "./RedoDialog";
import { RunPage } from "./RunPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

type Handler = Reply | ((init: RequestInit | undefined) => Reply);

const preview = (over: Partial<RedoPreview> = {}): RedoPreview => ({
  statement: "SOFP", name: "statement of financial position", refusal: null,
  kept: [
    { concept_uuid: "cash", entity_scope: "Company", label: "Cash and bank balances", how: "confirmed" },
    { concept_uuid: "opay", entity_scope: "Company", label: "Other payables and accruals", how: "edited" },
  ],
  ...over,
});

const cost: RunCost = {
  agents: [
    { agent: "Reading the document", seconds: 130, calls: 40, cost_usd: 0.18, unpriced: 0 },
    { agent: "Figures", seconds: 1327, calls: 61, cost_usd: 3.184, unpriced: 0 },
    { agent: "Notes", seconds: 65, calls: 2, cost_usd: null, unpriced: 2 },
  ],
  total: { seconds: 1522, calls: 103, cost_usd: 3.364, unpriced: 2 },
};

function routes(detail: Partial<RunDetail> = {}, extra: Record<string, Handler> = {}) {
  const events = [event(1, "Started the figures."), event(2, "Extraction is finished. The run is ready for review.", { kind: "done" })];
  return {
    "GET /api/runs/1": { body: { run: runDetail(detail) } },
    "GET /api/runs/1/statements/SOFP": { body: sofp },
    "GET /api/runs/1/checks": { body: { checks } },
    "GET /api/runs/1/needs-you": { body: needs },
    "GET /api/runs/1/comments": { body: { comments: [] } },
    "GET /api/runs/1/rounds": { body: { rounds: [], accept_all: { round_id: null, comment_ids: [] } } },
    "GET /api/runs/1/events": { body: { events, last_id: 2, has_more: false } },
    "GET /api/runs/1/question": { body: { question: null } },
    "GET /api/runs/1/questions": { body: { questions: [] } },
    "GET /api/runs/1/notes": { body: { notes: [] } },
    "GET /api/runs/1/notes/fields": { body: { fields: [] } },
    "GET /api/runs/1/notes/reports": { body: { reports: [] } },
    "GET /api/runs/1/statements/SOFP/redo": { body: { redo: preview() } },
    "GET /api/runs/1/cost": { body: { cost } },
    ...extra,
  };
}

const posted = (fetch: ReturnType<typeof mockFetch>, path: string) =>
  fetch.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url) === path).map(([, init]) => JSON.parse(String(init?.body)));

describe("Redo a statement", () => {
  it("lists the lines a person edited or confirmed and keeps them by default", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/statements/SOFP/redo": { status: 202, body: { run: runDetail({ status: "ready" }), cleared: 3, kept: 2 } } }));
    const onStarted = vi.fn();
    const onClose = vi.fn();
    render(<RedoDialog runId={1} statement="SOFP" name="Financial position" open onClose={onClose} onStarted={onStarted} />);
    const dialog = screen.getByRole("dialog", { name: "Redo financial position" });
    expect(await within(dialog).findByText("Keep the 2 lines you edited or confirmed")).toBeInTheDocument();
    expect(within(dialog).getByText("Cash and bank balances").closest("tr")).toHaveTextContent("Confirmed");
    expect(within(dialog).getByText("Other payables and accruals").closest("tr")).toHaveTextContent("Edited");
    expect(within(dialog).getByRole("switch", { name: "Keep the lines you edited or confirmed" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posted(fetch, "/api/runs/1/statements/SOFP/redo")).toEqual([{ keep_mine: true }]);
    expect(onStarted).toHaveBeenCalled();
  });

  it("replaces everything only when the person switches keeping off, and says so on the button", async () => {
    const fetch = mockFetch(routes({}, { "POST /api/runs/1/statements/SOFP/redo": { status: 202, body: { run: runDetail({ status: "ready" }), cleared: 5, kept: 0 } } }));
    render(<RedoDialog runId={1} statement="SOFP" name="Financial position" open onClose={() => {}} onStarted={() => {}} />);
    fireEvent.click(await screen.findByRole("switch", { name: "Keep the lines you edited or confirmed" }));
    expect(screen.queryByText("Cash and bank balances")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Redo and replace all" }));
    await waitFor(() => expect(posted(fetch, "/api/runs/1/statements/SOFP/redo")).toEqual([{ keep_mine: false }]));
  });

  it("has no switch when no line was edited or confirmed, and says why a redo is refused", async () => {
    mockFetch(routes({}, { "GET /api/runs/1/statements/SOFP/redo": { body: { redo: preview({ kept: [], refusal: "This run still has work in progress, so wait for it to finish before redoing a statement." }) } } }));
    render(<RedoDialog runId={1} statement="SOFP" name="Financial position" open onClose={() => {}} onStarted={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This run still has work in progress");
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  it("is offered on a statement of a run in review and opens the question", async () => {
    mockFetch(routes());
    render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Redo statement" }));
    expect(await screen.findByRole("dialog", { name: "Redo financial position" })).toBeInTheDocument();
    expect(await screen.findByText("Keep the 2 lines you edited or confirmed")).toBeInTheDocument();
  });

  it("marks the statement as being redone and the kept lines as kept while the agent works", async () => {
    mockFetch(routes({ status: "extracting", working_on: "SOFP", redo: { statement: "SOFP", kept: [7] }, stages: [{ name: "extract", status: "working", started_at: "2026-11-22T09:00:00Z", finished_at: null, error: null }] }));
    render(<RunPage runId={1} user={admin} />);
    // Only the line whose figure the person chose to keep says so.
    expect((await screen.findByText("Kept")).closest("tr")).toHaveTextContent("Cash and bank balances");
    expect(screen.getByText("Redoing").closest("[data-kind]")).toHaveAttribute("data-kind", "working");
    expect(screen.queryByRole("button", { name: "Redo statement" })).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
  });

  it("says a stopped redo was stopped and offers to try again", async () => {
    mockFetch(routes({ redo: { statement: "SOFP", kept: [] }, stages: [{ name: "extract", status: "stopped", started_at: null, finished_at: null, error: "Stopped on request; the figures saved so far are kept." }] }));
    render(<RunPage runId={1} user={admin} />);
    expect(await screen.findByText("Redo stopped")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Try again" }).length).toBeGreaterThan(0);
  });

  it("sends a run whose reading was stopped back to its setup page", async () => {
    mockFetch(routes({ status: "stopped", statements: [], stages: [{ name: "read", status: "stopped", started_at: null, finished_at: null, error: null }] }));
    render(<RunPage runId={1} user={admin} />);
    await waitFor(() => expect(window.location.hash).toBe("#/runs/1/setup"));
  });
});

describe("Cost and time", () => {
  it("stays one quiet line until opened, then shows each agent and the whole run", async () => {
    const fetch = mockFetch(routes());
    render(<CostFold runId={1} />);
    const fold = screen.getByRole("button", { name: "Cost and time" });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(fold);
    const figures = (await screen.findByText("Figures")).closest("tr")!;
    expect(figures).toHaveTextContent("22:07");
    expect(figures).toHaveTextContent("$3.18");
    // A cost nobody could price is left blank, never shown as zero.
    expect(screen.getByText("Notes").closest("tr")).toHaveTextContent(/^Notes1:05$/);
    const whole = screen.getByText("Whole run").closest("tr")!;
    expect(whole).toHaveTextContent("25:22");
    // Two calls had no known price, so the whole run's cost is marked as at least this much.
    expect(whole).toHaveTextContent(/\$3\.36\+$/);
    expect(figures).not.toHaveTextContent("+");
    fireEvent.click(fold);
    expect(screen.queryByText("Whole run")).toBeNull();
  });

  it("opens from the Activity tab of a run in review, and is absent while an agent works", async () => {
    mockFetch(routes());
    const { unmount } = render(<RunPage runId={1} user={admin} />);
    fireEvent.click(await screen.findByRole("tab", { name: /^Activity/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Cost and time" }));
    expect(await screen.findByText("Reading the document")).toBeInTheDocument();
    unmount();
    mockFetch(routes({ status: "extracting", stages: [{ name: "extract", status: "working", started_at: "2026-11-22T09:00:00Z", finished_at: null, error: null }] }));
    render(<RunPage runId={1} user={admin} />);
    await screen.findByText("Started the figures.");
    expect(screen.queryByRole("button", { name: "Cost and time" })).toBeNull();
  });
});
