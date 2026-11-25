import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityTab } from "./ActivityTab";
import { event } from "./fixtures";

const placing = "Placing the notes";
const figures = "Share capital and related parties";

const sideBySide = [
  event(1, "Started notes with gpt-6-luna."),
  event(2, "Working on placing the notes.", { kind: "session", agent: placing }),
  event(3, "Working on share capital and related parties.", { kind: "session", agent: figures }),
  event(4, "I'm reading notes 1 to 6.", { kind: "looked", agent: placing, pages: [22, 23] }),
  event(5, "I'm entering the share capital table.", { kind: "looked", agent: figures, pages: [31] }),
  event(6, "I'm placing the accounting policies.", { kind: "looked", agent: placing }),
];

describe("ActivityTab", () => {
  it("shows the first three pages of a long step and opens the rest", () => {
    const onPage = vi.fn();
    render(<ActivityTab events={[event(1, "I'm reading the statements.", { pages: [14, 15, 16, 17, 18, 19] })]} busy onPage={onPage} />);
    expect(screen.getAllByRole("button", { name: /^Page / })).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "3 more pages" }));
    expect(screen.getAllByRole("button", { name: /^Page / })).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Page 19" }));
    expect(onPage).toHaveBeenCalledWith(19);
  });

  it("gives each agent working side by side its own block with only its latest step", () => {
    render(<ActivityTab events={sideBySide} busy onPage={() => {}} />);
    expect(screen.getByRole("button", { name: new RegExp(placing) })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("I'm placing the accounting policies.")).toBeInTheDocument();
    expect(screen.getByText("I'm entering the share capital table.")).toBeInTheDocument();
    expect(screen.queryByText("I'm reading notes 1 to 6.")).toBeNull();
    // The stage's own line before the agents stays on top.
    expect(screen.getByText("Started notes with gpt-6-luna.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2 earlier steps" }));
    expect(screen.getByText("I'm reading notes 1 to 6.")).toBeInTheDocument();
    expect(screen.queryByText("Working on share capital and related parties.")).toBeNull();
  });

  it("folds finished agents to their name and how they ended", () => {
    const events = [
      ...sideBySide,
      event(7, "Placing the notes: done.", { kind: "finished", agent: placing }),
      event(8, "Share capital and related parties: done, with 2 point(s) left open.", { kind: "finished", agent: figures }),
      event(9, "The notes are placed: 6 of 6 listed note(s).", { kind: "done" }),
    ];
    render(<ActivityTab events={events} busy={false} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: new RegExp(`${figures} · Done, with 2 point\\(s\\) left open`) })).toBeInTheDocument();
    expect(screen.getByText("The notes are placed: 6 of 6 listed note(s).")).toBeInTheDocument();
    expect(screen.queryByText("I'm reading notes 1 to 6.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(placing) }));
    expect(screen.getByText("I'm reading notes 1 to 6.")).toBeInTheDocument();
  });

  it("shows a stage that starts again after a question as fresh blocks, with the stopped ones saying why", () => {
    const events = [
      event(2, "Working on placing the notes.", { kind: "session", agent: placing }),
      event(3, "Working on share capital and related parties.", { kind: "session", agent: figures }),
      event(4, "Stopped to ask about the standard.", { kind: "asked", agent: figures }),
      event(5, "Stopped to ask.", { kind: "stopped", agent: figures }),
      event(6, "Stopped to ask.", { kind: "stopped", agent: placing }),
      event(7, "Working on placing the notes.", { kind: "session", agent: placing }),
      event(8, "I'm placing the accounting policies.", { kind: "looked", agent: placing }),
    ];
    render(<ActivityTab events={events} busy onPage={() => {}} />);
    expect(screen.getByRole("button", { name: new RegExp(`${figures} · Stopped to ask`) })).toBeInTheDocument();
    const blocks = screen.getAllByRole("button", { name: new RegExp(`^${placing}`) });
    expect(blocks).toHaveLength(2);
    expect(blocks[1]).not.toHaveTextContent("Stopped");
    expect(screen.getByText("I'm placing the accounting policies.")).toBeInTheDocument();
  });
});
