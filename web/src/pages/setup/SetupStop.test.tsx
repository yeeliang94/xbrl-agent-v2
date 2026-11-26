import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadProgress, RunDocument } from "../../api";
import { mockFetch, type Reply } from "../../test-utils";
import { SetupPage } from "./SetupPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const document: RunDocument = {
  filename: "annual-report-2025.pdf", sha256: "x", size_bytes: 10, page_count: 62, scanned_pages: 0,
  uploaded_by: "aina@firm.my", uploaded_at: "2026-11-25T09:00:00Z", pages: [],
};

const progress = (over: Partial<ReadProgress> = {}): ReadProgress => ({
  status: "working", started_at: "2026-11-25T09:00:00Z", finished_at: null, error: null,
  pages: { total: 62, read: 13, blank: 0, failed: 0, waiting: 49 }, map_saved: false, stop_requested: false, ...over,
});

function routes(read: ReadProgress, extra: Record<string, Reply | (() => Reply)> = {}) {
  return {
    "GET /api/runs/5/document": { body: { document } },
    "GET /api/runs/5/read": { body: { read } },
    "GET /api/runs/5/events": {
      body: { events: [{ id: 1, job_id: 1, source: "reading", kind: "page", message: "Read page 13 of 62.", created_at: "2026-11-25T09:00:52Z", has_data: true }], last_id: 1, has_more: false },
    },
    ...extra,
  };
}

const posts = (fetch: ReturnType<typeof mockFetch>, path: string) => fetch.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url) === path).length;

describe("Stopping the reading", () => {
  it("offers Stop while the document is read, then says it is stopping after the page under way", async () => {
    const fetch = mockFetch(routes(progress(), { "POST /api/runs/5/read/stop": { status: 202, body: { read: progress({ stop_requested: true }) } } }));
    render(<SetupPage runId={5} />);
    expect(await screen.findByText("Reading page 14 of 62")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Replace" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByText("Stopping after page 14")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stopping" })).toBeDisabled();
    expect(posts(fetch, "/api/runs/5/read/stop")).toBe(1);
  });

  it("shows a stopped reading with the pages kept, and reads on when the person tries again", async () => {
    const stopped = progress({ status: "stopped", stop_requested: true, error: "Stopped on request; the pages read so far are kept." });
    let retried = false;
    const fetch = mockFetch(routes(stopped, {
      "GET /api/runs/5/read": () => ({ body: { read: retried ? progress() : stopped } }),
      "POST /api/runs/5/read/retry": () => {
        retried = true;
        return { status: 202, body: { read: progress({ status: "waiting" }) } };
      },
    }));
    render(<SetupPage runId={5} />);
    expect((await screen.findByText("Reading stopped")).closest("[data-kind]")).toHaveAttribute("data-kind", "neutral");
    expect(screen.getByText("13 of 62 pages read")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Pages read" })).toHaveAttribute("aria-valuenow", "13");
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/5/read/retry")).toBe(1));
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("says why when the stop is refused", async () => {
    mockFetch(routes(progress(), { "POST /api/runs/5/read/stop": { status: 409, body: { detail: "Reading is not running, so there is nothing to stop." } } }));
    render(<SetupPage runId={5} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByText("Reading is not running, so there is nothing to stop.")).toBeInTheDocument();
  });
});
