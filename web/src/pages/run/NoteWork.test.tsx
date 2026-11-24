import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Note, RunDetail } from "../../api";
import { NavSlot } from "../../components/AppShell";
import { admin, mockFetch } from "../../test-utils";
import { needs, report, round, runDetail, sofp } from "./fixtures";
import { allNotes, contingent, corp, heading, instruments, noteFields, noteReports, related1, revenue, reviewOf, summary } from "./noteFixtures";
import { RunPage } from "./RunPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

type Over = { detail?: Partial<RunDetail>; notes?: Note[]; extra?: Record<string, unknown>; house?: Parameters<typeof reviewOf>[1] };

// The server's notes as they now are: changes answered by `answer` and `echoLook` are kept here, so
// the note and its review text read back as changed.
let live = new Map<number, Note>();
let house: Parameters<typeof reviewOf>[1] = {};

/** The server's answer to a change: the note with a new revision, kept so later reads see it. */
const answer = (n: Note) => {
  const next = { ...n, revision: (live.get(n.id)?.revision ?? n.revision) + 1 };
  live.set(n.id, next);
  return { body: { note: next } };
};

function routes({ detail = {}, notes = allNotes, extra = {}, house: style = {} }: Over = {}) {
  live = new Map(notes.map((n) => [n.id, n]));
  house = style;
  const byId: Record<string, unknown> = {};
  for (const n of notes) {
    byId[`GET /api/runs/1/notes/${n.id}`] = () => ({ body: { note: live.get(n.id) } });
    byId[`GET /api/runs/1/notes/${n.id}/review`] = () => ({ body: { review: reviewOf(live.get(n.id)!, house) } });
  }
  return {
    "GET /api/runs/1": { body: { run: runDetail(detail) } },
    "GET /api/runs/1/statements/SOFP": { body: sofp },
    "GET /api/runs/1/checks": { body: { checks: [] } },
    "GET /api/runs/1/needs-you": { body: needs },
    "GET /api/runs/1/comments": { body: { comments: [] } },
    "GET /api/runs/1/rounds": { body: { rounds: [], accept_all: { round_id: null, comment_ids: [] } } },
    "GET /api/runs/1/rounds/2": { body: { round: round(), report } },
    "GET /api/runs/1/events": { body: { events: [], last_id: 0, has_more: false } },
    "GET /api/runs/1/question": { body: { question: null } },
    "GET /api/runs/1/questions": { body: { questions: [] } },
    "GET /api/runs/1/notes": { body: { notes: notes.map(summary) } },
    "GET /api/runs/1/notes/fields": { body: { fields: noteFields } },
    "GET /api/runs/1/notes/reports": { body: { reports: noteReports } },
    ...byId,
    ...extra,
  } as Parameters<typeof mockFetch>[0];
}

const posts = (fetch: ReturnType<typeof mockFetch>, path: string) =>
  fetch.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url) === path).map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : null));

function show(over: Over = {}) {
  const fetch = mockFetch(routes(over));
  const slot = document.createElement("nav");
  document.body.appendChild(slot);
  render(
    <NavSlot.Provider value={slot}>
      <RunPage runId={1} user={admin} />
    </NavSlot.Provider>,
  );
  return { fetch, nav: within(slot) };
}

async function openNote(nav: ReturnType<typeof within>, template: string, note?: string) {
  fireEvent.click(await nav.findByRole("button", { name: new RegExp(`^${template}`) }));
  if (note) fireEvent.click(await nav.findByRole("button", { name: new RegExp(`^${note}`) }));
}

/** The server's answer to a look change: the note, and the history row it wrote (900 plus the new revision). */
const echoLook = (n: Note) => (init: RequestInit | undefined) => {
  const out = answer({ ...(live.get(n.id) ?? n), blocks: JSON.parse(String(init?.body)).blocks });
  return { body: { ...out.body, history_id: 900 + out.body.note.revision } };
};
const reply = (n: Note) => () => answer(n);

describe("Notes screen", () => {
  it("lists notes by template with counts, and opens a note on the page", async () => {
    const { nav } = show();
    expect(await nav.findByRole("button", { name: /^List of notes\s*3$/ })).toBeInTheDocument();
    await openNote(nav, "List of notes", "Revenue");
    expect(await screen.findByText("17. Revenue")).toBeInTheDocument();
    expect(screen.getByText("Check formatting").closest("[data-kind]")).toHaveAttribute("data-kind", "attention");
    expect(nav.getByRole("button", { name: /^Not placed/ })).toBeInTheDocument();
  });

  it("sends a look change for the chosen scope and redraws the note", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/look": echoLook(revenue) } });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByText("11,930,400"));
    fireEvent.click(screen.getByRole("radio", { name: "Row" }));
    expect(screen.getByRole("heading", { name: "Row: Sale of hardware" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/look")).toHaveLength(1));
    const sent = posts(fetch, "/api/runs/1/notes/2/look")[0].blocks;
    expect(sent[2].rows[1].cells.map((c: { look: { bold: boolean } }) => c.look.bold)).toEqual([true, true, true]);
    expect(sent[2].rows[2].cells[0].look.bold).toBe(false);
    // The page redraws from the server's new review text.
    await waitFor(() => expect(screen.getByText("Sale of hardware").tagName).toBe("STRONG"));
    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true");
  });

  it("undoes the person's own look change with the button and with Cmd+Z", async () => {
    const { fetch, nav } = show({
      extra: { "POST /api/runs/1/notes/2/look": echoLook(revenue), "POST /api/runs/1/notes/2/undo": reply(revenue) },
    });
    await openNote(nav, "List of notes", "Revenue");
    expect(await screen.findByRole("button", { name: "Undo" })).toBeDisabled();
    fireEvent.click(screen.getByText("17. Revenue"));
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/look")).toHaveLength(2));
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/undo")).toEqual([{ history_id: 900 + revenue.revision + 2 }]));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/undo")).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled());
  });

  it("draws the server's review text, with the house style's double line", async () => {
    const cell = () => screen.getByText("18,642,300").closest("td") as HTMLElement;
    const first = show();
    await openNote(first.nav, "List of notes", "Revenue");
    await screen.findByText("18,642,300");
    expect(cell().getAttribute("style")).toContain("border-bottom: 2.5px solid");
    fireEvent.click(cell());
    expect(screen.getByText("Double underline shown as thick border")).toBeInTheDocument();
    cleanup();
    const second = show({ house: { double: "single_bottom_border" } });
    await openNote(second.nav, "List of notes", "Revenue");
    await screen.findByText("18,642,300");
    expect(cell().getAttribute("style")).toContain("border-bottom: 0.75px solid");
    fireEvent.click(cell());
    expect(screen.getByText("Double underline shown as single border")).toBeInTheDocument();
  });

  it("draws no styling at all when the field fits mTool only without it", async () => {
    const { nav } = show({ house: { tier: "flat" } });
    await openNote(nav, "List of notes", "Revenue");
    const total = (await screen.findByText("18,642,300")).closest("table") as HTMLElement;
    expect(total.querySelectorAll("[style]")).toHaveLength(0);
  });

  it("selects a block, a cell, a row and a column on the review text", async () => {
    const { nav } = show();
    await openNote(nav, "List of notes", "Revenue");
    const heading = (await screen.findByText("17. Revenue")).closest("[role=button]") as HTMLElement;
    fireEvent.click(heading);
    expect(heading).toHaveAttribute("aria-pressed", "true");
    expect(heading).toHaveClass("hit");
    const hits = () => Array.from(document.querySelectorAll("td.hit")).map((c) => c.textContent);
    fireEvent.click(screen.getByText("10,412,900"));
    expect(heading).not.toHaveClass("hit");
    expect(hits()).toEqual(["10,412,900"]);
    fireEvent.click(screen.getByRole("radio", { name: "Row" }));
    expect(hits()).toEqual(["Sale of hardware", "11,930,400", "10,412,900"]);
    fireEvent.click(screen.getByRole("radio", { name: "Column" }));
    expect(hits()).toEqual(["2024", "10,412,900", "5,792,900", "16,205,800"]);
    // A look the agent was not sure of is marked on its cell.
    expect(screen.getByText("6,711,900").closest("td")).toHaveClass("ns");
    fireEvent.keyDown(screen.getByText("6,711,900").closest("td")!, { key: "Enter" });
    expect(hits()).toEqual(["2025", "11,930,400", "6,711,900", "18,642,300"]);
  });

  it("never undoes a field change or Confirm: undo takes back only the person's own look changes", async () => {
    const { fetch, nav } = show({
      extra: {
        "POST /api/runs/1/notes/2/look": echoLook(revenue),
        "POST /api/runs/1/notes/2/confirm": () => answer({ ...live.get(2)!, format_state: "fine" }),
        "POST /api/runs/1/notes/2/field": () => answer({ ...live.get(2)!, field: { node_uuid: "f-other", label: "Disclosure of other notes" } }),
      },
    });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByText("17. Revenue"));
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/confirm")).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled());
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    // A new look change can be undone again; a field change after it ends that.
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Field" }), { target: { value: "f-other" } });
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/field")).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled());
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    expect(posts(fetch, "/api/runs/1/notes/2/undo")).toEqual([]);
  });

  it("moves a note to another field, or out of every field", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/field": reply({ ...revenue, field: null, template_id: null }) } });
    await openNote(nav, "List of notes", "Revenue");
    const field = await screen.findByRole("combobox", { name: "Field" });
    expect(within(field).getByRole("option", { name: /Significant accounting policies/ })).toBeDisabled();
    fireEvent.change(field, { target: { value: "f-other" } });
    fireEvent.change(field, { target: { value: "" } });
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/field")).toEqual([{ node_uuid: "f-other" }, { node_uuid: null }]));
  });

  it("confirms a note that needs checking", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/confirm": reply({ ...revenue, format_state: "fine" }) } });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/confirm")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull());
  });

  it("keeps Copy for mTool off for a field that is too long or a note not placed, and copies otherwise", async () => {
    const { nav } = show({ extra: { "GET /api/runs/1/notes/2/prepared": { body: { prepared: { node_uuid: "f-rev", revision: `r${revenue.revision}`, html: "<p>17. Revenue</p>", tier: "full", chars: 18, limit: 32767 } } } } });
    await openNote(nav, "List of notes", "Financial instruments");
    expect(await screen.findByText(instruments.blocks[0].kind === "heading" ? instruments.blocks[0].text : "")).toBeInTheDocument();
    expect(screen.getByText("Too long for mTool").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(screen.getByRole("button", { name: "Copy for mTool" })).toBeDisabled();
    await openNote(nav, "Not placed");
    expect(await screen.findByText("24. Contingent liabilities")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy for mTool" })).toBeDisabled();
    await openNote(nav, "List of notes", "Revenue");
    await screen.findByText("17. Revenue");
    document.execCommand = vi.fn(() => true);
    fireEvent.click(screen.getByRole("button", { name: "Copy for mTool" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows a skeleton while notes are being placed", async () => {
    const working = { stages: [{ name: "notes", status: "working", started_at: null, finished_at: null, error: null }] };
    const first = show({ detail: { status: "extracting", ...working } });
    await openNote(first.nav, "List of notes");
    await waitFor(() => expect(screen.getByRole("status", { name: "Notes are being placed" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Copy for mTool" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bold" })).toBeDisabled();
  });

  it("says when a template has no notes", async () => {
    const second = show({ notes: [contingent] });
    await openNote(second.nav, "Issued capital");
    expect(await screen.findByText("No notes in this template")).toBeInTheDocument();
  });

  it("switches between the parts of a split note, and shows its figures", async () => {
    const { nav } = show();
    await openNote(nav, "Related parties", "Related parties, part 1");
    expect(await screen.findByText("22. Related parties")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Figures" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Advance to a director, 2025" })).toHaveTextContent("42,000");
    fireEvent.click(screen.getByRole("radio", { name: "Part 2" }));
    expect(await screen.findByText("(b) Compensation of key management personnel")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Part 2" })).toHaveAttribute("aria-checked", "true");
  });

  it("shows a gap, a missing field, and Keep on a not sure look", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/look": echoLook(revenue) } });
    await openNote(nav, "List of notes", "Trade receivables");
    fireEvent.click(await screen.findByText("Page 24 ends here"));
    expect(screen.getByRole("heading", { name: "Gap in source" })).toBeInTheDocument();
    await openNote(nav, "Accounting policies");
    expect(await screen.findByText("No note in the report fills this field")).toBeInTheDocument();
    expect(screen.getByText("Missing")).toBeInTheDocument();
    await openNote(nav, "List of notes", "Revenue");
    const row = (await screen.findByText("Paragraph, alignment")).closest(".gl") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/look")[0].blocks[1].look.unsure).toEqual([]));
  });

  it("comments on part of a note with its block and scope", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/comments": { body: { comment: {} } } } });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByText("2025"));
    fireEvent.click(screen.getByRole("radio", { name: "Column" }));
    fireEvent.click(screen.getByRole("button", { name: "Columns misaligned" }));
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() =>
      expect(posts(fetch, "/api/runs/1/comments")).toEqual([{ target: { kind: "note", note_id: 2, note_part: { block: "p27b2", scope: "column", row: null, column: 1 } }, text: "Columns misaligned" }]),
    );
    fireEvent.click(screen.getByRole("button", { name: "Redo from source" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments")[1]).toEqual({ target: { kind: "note", note_id: 2, note_part: null }, text: "Redo from source" }));
  });

  it("picks among many parts from a dropdown, and keeps the field and Copy in the header", async () => {
    const parts = Array.from({ length: 8 }, (_, i) => ({ ...related1, id: 40 + i, part: i + 1, parts: 8, figures: null, blocks: [heading(30, i, `Part ${i + 1} of the note`)] }));
    const { nav } = show({ notes: [corp, ...parts] });
    await openNote(nav, "Related parties", "Related parties, part 1");
    const pick = await screen.findByRole("combobox", { name: "Part" });
    expect(screen.queryByRole("radio", { name: "Part 1" })).toBeNull();
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toContain("Part 8 of 8");
    expect(screen.getByRole("combobox", { name: "Field" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy for mTool" })).toBeInTheDocument();
    fireEvent.change(pick, { target: { value: "44" } });
    expect(await screen.findByText("Part 5 of the note")).toBeInTheDocument();
    // Each part's link names its part, and says so in full when it is cut short.
    expect(nav.getByRole("button", { name: /^Related parties, part 5/ })).toHaveAttribute("title", "Related parties, part 5");
  });

  it("asks a person to check a note placed with doubt, counts it, and Confirm settles it", async () => {
    const unsure = { ...corp, certainty: "unsure" as const, certainty_reason: "The note reads like a basis of preparation note." };
    const { fetch, nav } = show({ notes: [unsure, revenue], extra: { "POST /api/runs/1/notes/1/confirm": () => answer({ ...unsure, certainty: "sure" }) } });
    expect(await nav.findByRole("button", { name: /^Corporate information\s*1$/ })).toBeInTheDocument();
    await openNote(nav, "Corporate information");
    expect((await screen.findByText("Check field")).closest("[data-kind]")).toHaveAttribute("data-kind", "attention");
    expect(screen.getByText("The note reads like a basis of preparation note.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/1/confirm")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Check field")).toBeNull());
  });

  it("sends one look change at a time, and undoes by the history row the server names", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/look": echoLook(revenue), "POST /api/runs/1/notes/2/undo": reply(revenue) } });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByText("11,930,400"));
    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    // While the first change is on its way the toolbar waits, so a quick second click is not raced.
    expect(screen.getByRole("button", { name: "Italic" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Italic" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Italic" })).toBeEnabled());
    expect(posts(fetch, "/api/runs/1/notes/2/look")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Italic" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/look")).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/undo")).toEqual([{ history_id: 900 + revenue.revision + 2 }]));
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/history"))).toBe(false);
  });

  it("gives no undo for a look change whose history row the server does not name", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/notes/2/look": (init: RequestInit | undefined) => answer({ ...live.get(2)!, blocks: JSON.parse(String(init?.body)).blocks }) } });
    await openNote(nav, "List of notes", "Revenue");
    fireEvent.click(await screen.findByText("11,930,400"));
    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/notes/2/look")).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Bold" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });

  it("says so when the notes cannot be read, rather than showing no notes", async () => {
    show({ extra: { "GET /api/runs/1/notes": { status: 500, body: { detail: "The notes could not be read." } } } });
    expect(await screen.findByText("The notes could not be read.")).toBeInTheDocument();
  });

  it("copies only the text on screen: a newer field text is drawn first", async () => {
    const reviews = () => fetch.mock.calls.filter(([url]) => String(url) === "/api/runs/1/notes/2/review").length;
    const { fetch, nav } = show({ extra: { "GET /api/runs/1/notes/2/prepared": { body: { prepared: { node_uuid: "f-rev", revision: "r99", html: "<p>17. Revenue</p>", tier: "full", chars: 18, limit: 32767 } } } } });
    await openNote(nav, "List of notes", "Revenue");
    await screen.findByText("17. Revenue");
    const before = reviews();
    document.execCommand = vi.fn(() => true);
    fireEvent.click(screen.getByRole("button", { name: "Copy for mTool" }));
    expect(await screen.findByText(/The field changed since it was drawn/)).toBeInTheDocument();
    expect(document.execCommand).not.toHaveBeenCalled();
    expect(reviews()).toBe(before + 1);
  });

  it("opens the notes from a Needs you item on the notes as a whole", async () => {
    const whole = { items: [{ kind: "agent_comment" as const, title: "The notes", message: "Notes 3 and 4 are missing from the PDF.", statement: "NOTES" as const }], passed: 0 };
    show({ extra: { "GET /api/runs/1/needs-you": { body: whole } } });
    fireEvent.click(await screen.findByRole("button", { name: /^The notes/ }));
    expect(await screen.findByRole("heading", { name: "Corporate information", level: 2 })).toBeInTheDocument();
  });

  it("comments on a missing field from its panel", async () => {
    const { fetch, nav } = show({ extra: { "POST /api/runs/1/comments": { body: { comment: {} } } } });
    await openNote(nav, "Accounting policies");
    expect(await screen.findByText("No note in the report fills this field")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Note 2.4 covers the judgements." } });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(posts(fetch, "/api/runs/1/comments")).toEqual([{ target: { kind: "statement", statement: "NOTES", report_id: 32 }, text: "Note 2.4 covers the judgements." }]));
  });
});
