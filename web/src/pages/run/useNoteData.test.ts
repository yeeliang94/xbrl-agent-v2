import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Note, RunEvent } from "../../api";
import { mockFetch } from "../../test-utils";
import { commentPlace } from "./CommentsTab";
import { comment } from "./fixtures";
import { noteFields, noteReports, related1, related2, reviewOf, summary } from "./noteFixtures";
import { useNoteData } from "./useNoteData";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const event = (id: number) => ({ id, source: "notes" }) as unknown as RunEvent;

describe("useNoteData", () => {
  it("reads the review text again when another note in the open note's field changes", async () => {
    // Both parts sit in one field here, so a change to part 2 can change what part 1's field looks like.
    const one: Note = related1;
    let two: Note = { ...related2, field: related1.field };
    const fetch = mockFetch({
      "GET /api/runs/1/notes": () => ({ body: { notes: [summary(one), summary(two)] } }),
      "GET /api/runs/1/notes/fields": { body: { fields: noteFields } },
      "GET /api/runs/1/notes/reports": { body: { reports: noteReports } },
      "GET /api/runs/1/notes/8": { body: { note: one } },
      "GET /api/runs/1/notes/8/review": () => ({ body: { review: reviewOf(one) } }),
    });
    const reviews = () => fetch.mock.calls.filter(([url]) => String(url) === "/api/runs/1/notes/8/review").length;
    const { result, rerender } = renderHook(({ events }) => useNoteData(1, 8, events, async () => {}), { initialProps: { events: [] as RunEvent[] } });
    await waitFor(() => expect(result.current.review).not.toBeNull());
    await waitFor(() => expect(result.current.notes).toHaveLength(2));
    const before = reviews();
    two = { ...two, revision: two.revision + 1, fit: { tier: "compact", chars: 30000, limit: 32767 } };
    rerender({ events: [event(1)] });
    await waitFor(() => expect(reviews()).toBe(before + 1));
    expect(result.current.error).toBe("");
  });

  it("shows a failed read as an error, not as no notes", async () => {
    mockFetch({
      "GET /api/runs/1/notes": { status: 401, body: { detail: "Your session ended. Log in again." } },
      "GET /api/runs/1/notes/fields": { body: { fields: noteFields } },
      "GET /api/runs/1/notes/reports": { body: { reports: noteReports } },
    });
    const { result } = renderHook(() => useNoteData(1, null, [], async () => {}));
    await waitFor(() => expect(result.current.error).toBe("Your session ended. Log in again."));
  });
});

describe("note fields", () => {
  it("are read again when a scope answer changes the run's standard or level", async () => {
    const fetch = mockFetch({
      "GET /api/runs/1/notes": { body: { notes: [] } },
      "GET /api/runs/1/notes/fields": { body: { fields: noteFields } },
      "GET /api/runs/1/notes/reports": { body: { reports: [] } },
    });
    const reads = () => fetch.mock.calls.filter(([url]) => String(url) === "/api/runs/1/notes/fields").length;
    const { rerender } = renderHook(({ filing }) => useNoteData(1, null, [], async () => {}, filing), { initialProps: { filing: "MFRS|Company" } });
    await waitFor(() => expect(reads()).toBe(1));
    rerender({ filing: "MPERS|Company" });
    await waitFor(() => expect(reads()).toBe(2));
  });
});

describe("commentPlace", () => {
  it("names a comment on the notes as a whole", () => {
    expect(commentPlace(comment({ target: { ...comment().target, kind: "statement", statement: "NOTES", field_label: null } }))).toBe("The notes");
    expect(commentPlace(comment({ target: { ...comment().target, kind: "statement", statement: "NOTES", report_id: 32, field_label: "Significant accounting judgements" } }))).toBe("Significant accounting judgements");
  });
});
