import {
  cleanup,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Note } from "../../api";
import { NavSlot } from "../../components/AppShell";
import { admin, mockFetch } from "../../test-utils";
import { needs, report, round, runDetail, sofp } from "./fixtures";
import {
  allNotes,
  borrowings,
  noteFields,
  noteReports,
  summary,
} from "./noteFixtures";
import { RunPage } from "./RunPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

// Borrowings the agent was not sure of; the rest as the note fixtures have them.
const unsure: Note = {
  ...borrowings,
  certainty: "unsure",
  certainty_reason: "The hire purchase part may belong under leases.",
};
const notes = allNotes.map((n) => (n.id === unsure.id ? unsure : n));

function show(extra: Record<string, unknown> = {}) {
  const fetch = mockFetch({
    "GET /api/runs/1": { body: { run: runDetail() } },
    "GET /api/runs/1/statements/SOFP": { body: sofp },
    "GET /api/runs/1/checks": { body: { checks: [] } },
    "GET /api/runs/1/needs-you": { body: needs },
    "GET /api/runs/1/comments": { body: { comments: [] } },
    "GET /api/runs/1/rounds": {
      body: { rounds: [], accept_all: { round_id: null, comment_ids: [] } },
    },
    "GET /api/runs/1/rounds/2": { body: { round: round(), report } },
    "GET /api/runs/1/events": {
      body: { events: [], last_id: 0, has_more: false },
    },
    "GET /api/runs/1/question": { body: { question: null } },
    "GET /api/runs/1/questions": { body: { questions: [] } },
    "GET /api/runs/1/notes": { body: { notes: notes.map(summary) } },
    "GET /api/runs/1/notes/fields": { body: { fields: noteFields } },
    "GET /api/runs/1/notes/reports": { body: { reports: noteReports } },
    ...extra,
  } as Parameters<typeof mockFetch>[0]);
  const slot = document.createElement("nav");
  document.body.appendChild(slot);
  render(
    <NavSlot.Provider value={slot}>
      <RunPage runId={1} user={admin} />
    </NavSlot.Provider>,
  );
  return { fetch, nav: within(slot) };
}

const posts = (fetch: ReturnType<typeof mockFetch>, path: string) =>
  fetch.mock.calls
    .filter(([url, init]) => init?.method === "POST" && String(url) === path)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : null));

async function openMap(nav: ReturnType<typeof within>) {
  fireEvent.click(await nav.findByRole("button", { name: /^Placement map/ }));
  return screen.findByRole("heading", { name: "Placement map" });
}

const row = (text: string) =>
  screen
    .getByText(text, { selector: ".pt" })
    .closest(".prow, .pchip") as HTMLElement;

describe("Placement map", () => {
  it("shows every note beside its field, with what needs a look counted in the sidebar", async () => {
    const { nav } = show();
    // Borrowings is unsure; Contingent liabilities is in no field.
    expect(
      await nav.findByRole("button", { name: /^Placement map\s*3$/ }),
    ).toBeInTheDocument();
    await openMap(nav);
    expect(
      within(row("Borrowings")).getByText("Check").closest("[data-kind]"),
    ).toHaveAttribute("data-kind", "check");
    expect(
      within(row("Contingent liabilities"))
        .getByText("Not placed")
        .closest("[data-kind]"),
    ).toHaveAttribute("data-kind", "failure");
    expect(
      within(row("Revenue")).getByText("Revenue", { selector: ".pf" }),
    ).toBeInTheDocument();
    // The split related-party note is one row until opened.
    expect(screen.getByText("2 parts · Related parties")).toBeInTheDocument();
    expect(
      screen.queryByText("Related parties, part 2"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Show the parts of note 22" }),
    );
    expect(screen.getByText("Related parties, part 2")).toBeInTheDocument();

    // The mandatory judgements field has no note: it is listed last, and counted.
    const judgements = screen
      .getByText("Significant accounting judgements and estimates", {
        selector: ".pf",
      })
      .closest(".prow") as HTMLElement;
    expect(
      within(judgements).getByText("Empty").closest("[data-kind]"),
    ).toHaveAttribute("data-kind", "check");

    fireEvent.click(screen.getByRole("radio", { name: "Needs you" }));
    expect(
      screen.queryByText("Revenue", { selector: ".pt" }),
    ).not.toBeInTheDocument();
    expect(row("Borrowings")).toBeInTheDocument();
  });

  it("says why a note needs a look, and Field is right confirms only its field", async () => {
    const { fetch, nav } = show({
      "POST /api/runs/1/notes/4/field/confirm": {
        body: {
          note: { ...unsure, confirmed_by: admin.email, certainty: "sure" },
          history_id: 77,
        },
      },
      "POST /api/runs/1/notes/4/undo": { body: { note: unsure } },
    });
    await openMap(nav);
    fireEvent.click(row("Borrowings"));
    expect(
      await screen.findByText(
        "The hire purchase part may belong under leases.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Field is right" }));
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/notes/4/field/confirm")).toHaveLength(1),
    );
    expect(
      await screen.findByText("Confirmed 14 Borrowings belongs in Borrowings."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/notes/4/undo")).toEqual([
        { history_id: 77 },
      ]),
    );
  });

  it("lets a person confirm a note that needs no look", async () => {
    const { fetch, nav } = show({
      "POST /api/runs/1/notes/2/field/confirm": {
        body: { note: notes[1], history_id: 3 },
      },
    });
    await openMap(nav);
    fireEvent.click(row("Revenue"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Field is right" }),
    );
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/notes/2/field/confirm")).toHaveLength(1),
    );
  });

  it("moves a note to a field found by search", async () => {
    const { fetch, nav } = show({
      "POST /api/runs/1/notes/6/field": {
        body: { note: notes[5], history_id: 5 },
      },
    });
    await openMap(nav);
    fireEvent.click(row("Contingent liabilities"));
    expect(
      await screen.findByText(
        "This note is in no field, so it would be left out of the mTool file.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Find a field" }), {
      target: { value: "other" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Other notes/ }));
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/notes/6/field")).toEqual([
        { node_uuid: "f-other" },
      ]),
    );
    expect(
      await screen.findByText(
        "Moved 24 Contingent liabilities to Other notes.",
      ),
    ).toBeInTheDocument();
  });

  it("shows mTool's order with empty mandatory fields, and moves a note dropped on a field", async () => {
    const { fetch, nav } = show({
      "POST /api/runs/1/notes/4/field": {
        body: { note: notes[3], history_id: 9 },
      },
    });
    await openMap(nav);
    fireEvent.click(screen.getByRole("radio", { name: "mTool order" }));
    expect(screen.getByText("0 of 2 used")).toBeInTheDocument(); // accounting policies: basis and the mandatory one, both empty
    const judgements = screen
      .getByText("Significant accounting judgements and estimates")
      .closest(".prow") as HTMLElement;
    expect(
      within(judgements).getByText("Empty").closest("[data-kind]"),
    ).toHaveAttribute("data-kind", "check");
    expect(
      screen.queryByText("Financial instruments", { selector: ".pl" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Basis of preparation", { selector: ".pl" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Empty fields" }));
    expect(
      screen.getByText("Basis of preparation", { selector: ".pl" }),
    ).toBeInTheDocument();

    // Drag Borrowings onto the catch-all field.
    const data = new Map<string, string>();
    const transfer = {
      types: [] as string[],
      setData: (k: string, v: string) => (
        data.set(k, v),
        transfer.types.push(k)
      ),
      getData: (k: string) => data.get(k) ?? "",
      dropEffect: "",
      effectAllowed: "",
    };
    fireEvent(
      row("Borrowings"),
      Object.assign(createEvent.dragStart(row("Borrowings")), {
        dataTransfer: transfer,
      }),
    );
    const target = screen
      .getByText("Other notes", { selector: ".pl" })
      .closest(".prow") as HTMLElement;
    fireEvent(
      target,
      Object.assign(createEvent.dragOver(target), { dataTransfer: transfer }),
    );
    fireEvent(
      target,
      Object.assign(createEvent.drop(target), { dataTransfer: transfer }),
    );
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/notes/4/field")).toEqual([
        { node_uuid: "f-other" },
      ]),
    );
  });
});
