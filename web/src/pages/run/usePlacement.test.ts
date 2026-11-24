import { describe, expect, it } from "vitest";
import { borrowings, summary } from "./noteFixtures";
import { canUndo } from "./usePlacement";

describe("placement undo", () => {
  const done = { text: "", noteId: borrowings.id, historyId: 77, revision: 5 };
  it("holds while the note is still as the change left it", () => {
    expect(canUndo(done, [{ ...summary(borrowings), revision: 5 }])).toBe(true);
  });
  it("lapses once anything else changes the note, so Undo never wipes that change", () => {
    expect(canUndo(done, [{ ...summary(borrowings), revision: 6 }])).toBe(
      false,
    );
    expect(
      canUndo({ ...done, historyId: null }, [
        { ...summary(borrowings), revision: 5 },
      ]),
    ).toBe(false);
  });
});
