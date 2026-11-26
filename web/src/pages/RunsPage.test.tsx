import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Run } from "../api";
import { admin, member, mockFetch, run } from "../test-utils";
import { REFRESH_MS, RunsPage, updatedSince } from "./RunsPage";
import { formatUpdated } from "./runStatus";
import type { RunStatus } from "../api/types";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

/** One page of the run list, as the server sends it. */
const listOf = (runs: Run[], over: { total?: number; page?: number } = {}) => ({
  body: { runs, total: over.total ?? runs.length, page: over.page ?? 0, per_page: 25 },
});
const deletion = (over: object = {}) => ({ body: { allowed: true, refused: null, figures: 412, notes: 18, filled_workbook: false, ...over } });
/** The addresses asked for, newest last, without the host. */
const asked = (spy: ReturnType<typeof mockFetch>, method = "GET") =>
  spy.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method).map(([input]) => decodeURIComponent(String(input)));

const latest = (spy: ReturnType<typeof mockFetch>) => asked(spy).slice(-1)[0];

describe("Runs page", () => {
  it("refreshes itself, so a run's status moves without a reload", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let status: RunStatus = "extracting";
      mockFetch({ "GET /api/runs": () => listOf([run({ status })]) });
      render(<RunsPage user={admin} />);
      const row = (await screen.findByText("Extracting")).closest("tr")!;
      status = "in_review";
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
      await waitFor(() => expect(within(row).getByText("In review")).toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });

  it("says so when there are no runs", async () => {
    mockFetch({ "GET /api/runs": listOf([]) });
    render(<RunsPage user={admin} />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  });

  it("opens the New run page from its button", async () => {
    mockFetch({ "GET /api/runs": listOf([]) });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    expect(window.location.hash).toBe("#/runs/new");
  });

  it("shows a reading run by its file name and opens its setup", async () => {
    mockFetch({
      "GET /api/runs": listOf([run({ id: 9, company: null, year: null, standard: null, level: null, status: "reading", filename: "Doc 3.pdf" })]),
    });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Doc 3.pdf")).closest("tr")!;
    const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(0, 5)).toEqual(["", "Doc 3.pdf", "", "", "Reading"]);
    expect(row.textContent).not.toContain("null");
    expect(within(row).getByText("Reading").closest("[data-kind]")).toHaveAttribute("data-kind", "working");
    fireEvent.click(row);
    expect(window.location.hash).toBe("#/runs/9/setup");
  });

  it("makes only a run that opens something look clickable", async () => {
    window.location.hash = "#/runs";
    mockFetch({
      "GET /api/runs": listOf([run({ id: 9, company: null, status: "setup", filename: "Doc 3.pdf" }), run({ id: 4, company: "Demo", status: "setup", filename: null })]),
    });
    render(<RunsPage user={admin} />);
    const opens = (await screen.findByText("Doc 3.pdf")).closest("tr")!;
    const stays = screen.getByText("Demo").closest("tr")!;
    expect(opens).toHaveClass("click");
    expect(stays).not.toHaveClass("click");
    fireEvent.click(stays);
    expect(window.location.hash).toBe("#/runs");
  });

  it.each([
    ["extracting", null, "#/runs/4"],
    ["ready", null, "#/runs/4"],
    ["in_review", null, "#/runs/4"],
    ["correcting", null, "#/runs/4"],
    ["failed", "extract", "#/runs/4"],
    ["failed", "read", "#/runs/4/setup"],
    ["stopped", "read", "#/runs/4/setup"],
    ["stopped", null, "#/runs/4"],
    ["setup", null, "#/runs/4/setup"],
    ["needs_answer", null, "#/runs/4"],
  ] as const)("opens a %s run (failed stage %s) at %s", async (status, failed_stage, hash) => {
    mockFetch({ "GET /api/runs": listOf([run({ id: 4, status, failed_stage })]) });
    render(<RunsPage user={admin} />);
    fireEvent.click((await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!);
    expect(window.location.hash).toBe(hash);
  });

  it("shows a run from the contract shape, with its file beside its company", async () => {
    mockFetch({ "GET /api/runs": listOf([run({ status: "failed", level: "Group", owner_name: "Hafiz M." })]) });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!;
    const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(0, 5)).toEqual(["Seri Maju Trading Sdn. Bhd.", "Seri Maju 2025.pdf", "2025", "MFRS, Group", "Failed"]);
    expect(cells[6]).toBe("Hafiz M.");
    expect(within(row).getByText("Failed").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Company", "File", "Year", "Filing", "Status", "Updated", "Owner", ""]);
  });

  it("leaves the year cell empty when the year is not known", async () => {
    mockFetch({ "GET /api/runs": listOf([run({ year: null })]) });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!;
    expect(within(row).getAllByRole("cell")[2].textContent).toBe("");
  });

  it("maps each status to the right look", async () => {
    mockFetch({
      "GET /api/runs": listOf([
        run({ id: 1, status: "extracting" }),
        run({ id: 2, status: "in_review" }),
        run({ id: 3, status: "filed" }),
        run({ id: 4, status: "stopped" }),
        run({ id: 5, status: "needs_answer" }),
        run({ id: 6, status: "ready" }),
      ]),
    });
    render(<RunsPage user={admin} />);
    const table = within(await screen.findByRole("table"));
    const kind = (word: string) => table.getByText(word).closest("[data-kind]")?.getAttribute("data-kind");
    expect(kind("Extracting")).toBe("working");
    expect(kind("In review")).toBe("attention");
    expect(kind("Filed")).toBe("finished");
    expect(kind("Stopped")).toBe("neutral");
    expect(kind("Needs you")).toBe("attention");
    expect(kind("Ready")).toBe("neutral");
  });

  it("shows the server's sentence when the list fails", async () => {
    mockFetch({ "GET /api/runs": { status: 500, body: { detail: "The run list could not be read." } } });
    render(<RunsPage user={admin} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The run list could not be read.");
  });

  it("writes the update time plainly", () => {
    const now = new Date(2026, 10, 18, 15, 0);
    expect(formatUpdated(new Date(2026, 10, 18, 9, 14).toISOString(), now)).toBe("Today, 09:14");
    expect(formatUpdated(new Date(2026, 10, 17, 9, 14).toISOString(), now)).toBe("Yesterday");
    expect(formatUpdated(new Date(2026, 10, 12, 9, 14).toISOString(), now)).toBe("12 Nov");
    expect(formatUpdated(new Date(2025, 10, 12, 9, 14).toISOString(), now)).toBe("12 Nov 2025");
  });
});

describe("Run list search, filters and paging", () => {
  it("asks the server for mine by the signed-in person, and for the runs in review", async () => {
    const spy = mockFetch({ "GET /api/runs": listOf([run()]) });
    render(<RunsPage user={admin} />);
    await screen.findByRole("table");
    expect(asked(spy)).toEqual(["/api/runs"]);

    fireEvent.click(screen.getByRole("radio", { name: "Mine" }));
    await waitFor(() => expect(latest(spy)).toBe("/api/runs?mine=true"));

    fireEvent.click(screen.getByRole("radio", { name: "In review" }));
    await waitFor(() => expect(latest(spy)).toBe("/api/runs?status=in_review"));
    // The view fixes the status, so its filter is locked on it.
    expect(screen.getByLabelText("Status")).toBeDisabled();
    expect(screen.getByLabelText("Status")).toHaveValue("in_review");

    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    await waitFor(() => expect(latest(spy)).toBe("/api/runs"));
    expect(screen.getByLabelText("Status")).toBeEnabled();
  });

  it("searches after a pause in typing and filters by status, standard and date together", async () => {
    const spy = mockFetch({ "GET /api/runs": listOf([run()]) });
    render(<RunsPage user={admin} />);
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Search company or file"), { target: { value: "  logistik " } });
    await waitFor(() => expect(latest(spy)).toBe("/api/runs?q=logistik"));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "working" } });
    fireEvent.change(screen.getByLabelText("Standard"), { target: { value: "MPERS" } });
    fireEvent.change(screen.getByLabelText("Updated"), { target: { value: "year" } });
    const since = new Date(new Date().getFullYear(), 0, 1).toISOString();
    await waitFor(() => expect(latest(spy)).toBe(`/api/runs?q=logistik&status=working&standard=MPERS&updated_since=${since}`));

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(latest(spy)).toBe("/api/runs"));
    expect(screen.getByLabelText("Search company or file")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("says no runs match when the filters leave nothing", async () => {
    mockFetch({ "GET /api/runs": listOf([]) });
    render(<RunsPage user={admin} />);
    await screen.findByText("No runs yet");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });
    expect(await screen.findByText("No runs match")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("counts the rows shown and pages through them on the server", async () => {
    const pageOf = (page: number) => Array.from({ length: 25 }, (_, i) => run({ id: page * 25 + i + 1, company: `Contoh ${page * 25 + i + 1} Sdn. Bhd.` }));
    const spy = mockFetch({
      "GET /api/runs": listOf(pageOf(0), { total: 200 }),
      "GET /api/runs?page=1": listOf(pageOf(1), { total: 200, page: 1 }),
      "GET /api/runs?page=7": listOf(pageOf(7), { total: 200, page: 7 }),
    });
    render(<RunsPage user={admin} />);
    expect(await screen.findByText("1–25 of 200")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getAllByRole("row")).toHaveLength(26);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("26–50 of 200")).toBeInTheDocument();
    expect(screen.getByText("Contoh 26 Sdn. Bhd.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
    expect(latest(spy)).toBe("/api/runs?page=1");

    // A new filter starts again from the first page.
    fireEvent.change(screen.getByLabelText("Standard"), { target: { value: "MFRS" } });
    await waitFor(() => expect(latest(spy)).toBe("/api/runs?standard=MFRS"));
  });

  it("stops at the last page", async () => {
    mockFetch({ "GET /api/runs": listOf([run({ id: 1 }), run({ id: 2 })], { total: 2 }) });
    render(<RunsPage user={admin} />);
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("turns each date choice into the earliest update time, in the person's own time", () => {
    const now = new Date(2026, 10, 25, 10, 30);
    expect(updatedSince("", now)).toBe("");
    expect(updatedSince("today", now)).toBe(new Date(2026, 10, 25).toISOString());
    expect(updatedSince("7", now)).toBe(new Date(2026, 10, 19).toISOString());
    expect(updatedSince("30", now)).toBe(new Date(2026, 9, 27).toISOString());
    expect(updatedSince("year", now)).toBe(new Date(2026, 0, 1).toISOString());
  });
});

describe("Deleting a run", () => {
  const filed = run({ id: 7, company: "Contoh Logistik Sdn. Bhd.", year: 2025, status: "filed" });

  it("names what goes, deletes on confirm and says so", async () => {
    let left = [filed, run({ id: 8, company: "Demo Makanan Sdn. Bhd." })];
    const spy = mockFetch({
      "GET /api/runs": () => listOf(left),
      "GET /api/runs/7/deletion": deletion({ filled_workbook: true }),
      "DELETE /api/runs/7": () => {
        left = left.slice(1);
        return { status: 204 };
      },
    });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Contoh Logistik Sdn. Bhd.")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete run" }));
    // The delete button does not also open the run.
    expect(window.location.hash).toBe("");

    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading")).toHaveTextContent("Delete Contoh Logistik Sdn. Bhd. 2025?");
    expect(dialog.getByText("This removes its 412 figures and 18 notes, the uploaded PDF and filled workbook, and the agents' traces. It can't be undone.")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Delete run" }));

    expect(await screen.findByText("Run deleted")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Contoh Logistik Sdn. Bhd.")).toBeNull());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(asked(spy, "DELETE")).toEqual(["/api/runs/7"]);
  });

  it("keeps the run when the dialog is cancelled", async () => {
    const spy = mockFetch({ "GET /api/runs": listOf([filed]), "GET /api/runs/7/deletion": deletion({ figures: 1, notes: 1 }) });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText("This removes its 1 figure and 1 note, the uploaded PDF, and the agents' traces. It can't be undone.")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(asked(spy, "DELETE")).toEqual([]);
  });

  it("names the PDF alone for a run still at setup", async () => {
    mockFetch({
      "GET /api/runs": listOf([run({ id: 7, company: null, year: null, status: "setup", filename: "Rekaan Solar AFS 2026.pdf" })]),
      "GET /api/runs/7/deletion": deletion({ figures: 0, notes: 0 }),
    });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading")).toHaveTextContent("Delete Rekaan Solar AFS 2026.pdf?");
    expect(dialog.getByText("This removes the uploaded PDF and everything read from it. It can't be undone.")).toBeInTheDocument();
  });

  it("says a working run cannot be deleted yet and offers no delete", async () => {
    mockFetch({
      "GET /api/runs": listOf([{ ...filed, status: "extracting" }]),
      "GET /api/runs/7/deletion": deletion({ allowed: false, refused: { code: "working", detail: "This run is still working, so stop it or wait until it finishes, then delete it." } }),
    });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading")).toHaveTextContent("This run can't be deleted yet");
    expect(dialog.getByText("Contoh Logistik Sdn. Bhd. 2025 is still extracting. Stop it or wait until it finishes, then delete it.")).toBeInTheDocument();
    expect(dialog.getAllByRole("button").map((b) => b.textContent)).toEqual(["Close"]);
    fireEvent.click(dialog.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("tells someone who is not the owner whose run it is", async () => {
    mockFetch({
      "GET /api/runs": listOf([{ ...filed, owner_name: "Farid", owner_email: "farid@firm.my" }]),
      "GET /api/runs/7/deletion": deletion({ allowed: false, refused: { code: "owner", detail: "Only the run's owner or an admin can delete this run." } }),
    });
    render(<RunsPage user={member} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading")).toHaveTextContent("This run isn't yours to delete");
    expect(dialog.getByText("Only its owner, Farid, or an admin can delete Contoh Logistik Sdn. Bhd. 2025.")).toBeInTheDocument();
    expect(dialog.getAllByRole("button").map((b) => b.textContent)).toEqual(["Close"]);
  });

  it("shows the server's sentence when the delete is refused after all", async () => {
    mockFetch({
      "GET /api/runs": listOf([filed]),
      "GET /api/runs/7/deletion": deletion(),
      "DELETE /api/runs/7": { status: 409, body: { detail: "This run is still working, so stop it or wait until it finishes, then delete it." } },
    });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete run" }));
    expect(await screen.findByText("This run is still working, so stop it or wait until it finishes, then delete it.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "This run was not deleted" })).toBeInTheDocument();
    expect(screen.getByText("Contoh Logistik Sdn. Bhd.")).toBeInTheDocument();
  });
});

describe("Clearing abandoned drafts", () => {
  it("is offered to an admin only", async () => {
    mockFetch({ "GET /api/runs": listOf([run()]) });
    const { unmount } = render(<RunsPage user={member} />);
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Clear abandoned drafts" })).toBeNull();
    unmount();
    render(<RunsPage user={admin} />);
    expect(await screen.findByRole("button", { name: "Clear abandoned drafts" })).toBeInTheDocument();
  });

  it("counts the drafts for the chosen age, clears them and says how many went", async () => {
    const spy = mockFetch({
      "GET /api/runs": listOf([run()]),
      "GET /api/admin/drafts?older_than_days=30": { body: { older_than_days: 30, count: 4 } },
      "GET /api/admin/drafts?older_than_days=90": { body: { older_than_days: 90, count: 1 } },
      "GET /api/admin/drafts?older_than_days=7": { body: { older_than_days: 7, count: 0 } },
      "POST /api/admin/drafts/clear": { body: { older_than_days: 90, cleared: 1 } },
    });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Clear abandoned drafts" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading")).toHaveTextContent("Clear abandoned drafts?");
    expect(await dialog.findByText("4 runs are still at setup and have not been touched for 30 days or more. Their uploaded PDFs and everything read from them are removed. It can't be undone.")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "Clear 4 drafts" })).toBeEnabled();

    fireEvent.change(dialog.getByLabelText("Not touched for"), { target: { value: "7" } });
    expect(await dialog.findByText("No runs at setup are that old.")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "Clear 0 drafts" })).toBeDisabled();

    fireEvent.change(dialog.getByLabelText("Not touched for"), { target: { value: "90" } });
    expect(await dialog.findByText("1 run is still at setup and has not been touched for 90 days or more. Their uploaded PDFs and everything read from them are removed. It can't be undone.")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Clear 1 draft" }));

    expect(await screen.findByText("1 draft cleared")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    const post = spy.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({ older_than_days: 90 });
  });

  it("shows the server's sentence when a non-admin is refused", async () => {
    mockFetch({
      "GET /api/runs": listOf([run()]),
      "GET /api/admin/drafts": { status: 403, body: { detail: "Only an admin can do this." } },
    });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Clear abandoned drafts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only an admin can do this.");
    expect(screen.getByRole("button", { name: "Clear 0 drafts" })).toBeDisabled();
  });
});
