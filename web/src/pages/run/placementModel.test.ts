import { describe, expect, it } from "vitest";
import type { NoteField } from "../../api";
import {
  borrowings,
  contingent,
  noteFields,
  related1,
  related2,
  revenue,
  summary,
} from "./noteFixtures";
import {
  flagOf,
  placeFields,
  reportRows,
  searchFields,
  shortName,
  suggest,
  templateSections,
} from "./placementModel";

// Three more list-of-notes fields, in mTool's order: the list's fields sit together.
const fields = placeFields([
  ...noteFields.slice(0, 8),
  {
    ...noteFields[4],
    field_id: "f-cash",
    label: "Disclosure of cash and cash equivalents",
  },
  { ...noteFields[4], field_id: "f-oi", label: "Disclosure of other income" },
  {
    ...noteFields[4],
    field_id: "f-kmp-l",
    label: "Disclosure of key management personnel compensation",
  },
  ...noteFields.slice(8),
] as NoteField[]);
const at = (id: string, over = {}) => ({
  ...summary(revenue),
  field: { node_uuid: id, label: id },
  ...over,
});

describe("placement map model", () => {
  it("names a field without mTool's repeated opening words", () => {
    expect(shortName("Disclosure of other income")).toBe("Other income");
    expect(
      shortName("Description of accounting policy for borrowing costs"),
    ).toBe("Borrowing costs");
    expect(shortName("*Disclosure of other notes to accounts")).toBe(
      "Other notes to accounts",
    );
  });

  it("flags a note in no field, one the agent was unsure of, and one whose title reads like another field", () => {
    expect(flagOf(summary(contingent), fields)).toMatchObject({
      kind: "not_placed",
    });
    expect(
      flagOf(
        {
          ...summary(borrowings),
          certainty: "unsure",
          certainty_reason: "Maybe leases.",
        },
        fields,
      ),
    ).toEqual({ kind: "check", why: "Maybe leases." });
    const wrong = flagOf(at("f-rev", { title: "Other income" }), fields);
    expect(wrong).toMatchObject({
      kind: "check",
      why: "The title reads closer to Other income than to Revenue.",
    });
    expect(
      flagOf(at("f-other", { title: "Other income" }), fields),
    ).toMatchObject({
      kind: "check",
      why: "This sits in the catch-all field, but mTool has a field named Other income.",
    });
    expect(flagOf(summary(revenue), fields)).toEqual({ kind: "placed" });
  });

  it("takes a person's confirm or move as settling the field", () => {
    expect(
      flagOf(
        at("f-rev", { title: "Other income", confirmed_by: "ana@firm.com" }),
        fields,
      ),
    ).toEqual({ kind: "confirmed" });
  });

  it("does not match a split part with no heading of its own by its whole note's title", () => {
    expect(flagOf(summary(related2), fields)).toEqual({ kind: "placed" });
    expect(
      flagOf(
        { ...summary(related2), part_title: "Key management personnel" },
        fields,
      ),
    ).toEqual({ kind: "placed" });
  });

  it("suggests fields by name and by the everyday words reports use", () => {
    expect(
      suggest(at("f-other", { title: "Directors' remuneration" }), fields).map(
        (f) => f.short,
      ),
    ).toContain("Key management personnel compensation");
    expect(searchFields("bank", fields).map((f) => f.short)).toEqual([
      "Cash and cash equivalents",
    ]);
    expect(searchFields("zzz", fields)).toEqual([]);
  });

  it("lists notes in report order with a split note as one row of parts", () => {
    const rows = reportRows([
      summary(related2),
      summary(revenue),
      summary(related1),
    ]);
    expect(
      rows.map((r) =>
        r.kind === "note" ? r.note.title : `${r.title} (${r.parts.length})`,
      ),
    ).toEqual(["Revenue", "Related parties (2)"]);
  });

  it("shows used and mandatory fields in mTool order, and every field when asked", () => {
    const notes = [summary(revenue)];
    const list = templateSections(fields, notes, false).find(
      (s) => s.name === "List of notes",
    )!;
    expect(list.rows.map((r) => r.field.short)).toEqual(["Revenue"]);
    expect([list.used, list.total]).toEqual([1, 8]);
    const policies = templateSections(fields, notes, false).find(
      (s) => s.name === "Accounting policies",
    )!;
    expect(policies.rows.map((r) => r.field.short)).toEqual([
      "Significant accounting judgements and estimates",
    ]);
    expect(
      templateSections(fields, notes, true).find(
        (s) => s.name === "List of notes",
      )!.rows,
    ).toHaveLength(8);
  });
});
