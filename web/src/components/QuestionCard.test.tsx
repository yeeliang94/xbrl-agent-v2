import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuestionCard } from "./QuestionCard";

function setup() {
  const onChoose = vi.fn();
  const onOther = vi.fn();
  const onPage = vi.fn();
  render(
    <QuestionCard
      question="Are the amounts in RM or RM thousands?"
      evidence={[{ text: "No unit is printed above the statements", pages: [7] }]}
      choices={[
        { label: "RM", effect: "Figures are filed as printed", suggested: true },
        { label: "RM thousands", effect: "Every figure is filed multiplied by 1,000" },
      ]}
      onChoose={onChoose}
      onOther={onOther}
      onPage={onPage}
    />,
  );
  return { onChoose, onOther, onPage };
}

describe("Question card", () => {
  it("shows the question, the evidence, the choices and the key hint", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Are the amounts in RM or RM thousands?" })).toBeInTheDocument();
    expect(screen.getByText("Suggested").closest("button")).toHaveTextContent("RM");
    expect(screen.getByText("Press 1 to 3 to choose")).toBeInTheDocument();
  });

  it("picks a choice with its number key and opens a page from the evidence", () => {
    const { onChoose, onPage } = setup();
    fireEvent.keyDown(document.body, { key: "2" });
    expect(onChoose).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "Page 7" }));
    expect(onPage).toHaveBeenCalledWith(7);
  });

  it("moves to the text box with the last number and sends the person's own answer", () => {
    const { onChoose, onOther } = setup();
    fireEvent.keyDown(document.body, { key: "3" });
    const box = screen.getByLabelText("Something else");
    expect(box).toHaveFocus();
    expect(onChoose).not.toHaveBeenCalled();
    // Numbers typed in the box are text, not choices.
    fireEvent.keyDown(box, { key: "1" });
    expect(onChoose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "Ringgit, as printed" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onOther).toHaveBeenCalledWith("Ringgit, as printed");
  });

  it("ignores numbers beyond the choices", () => {
    const { onChoose } = setup();
    fireEvent.keyDown(document.body, { key: "4" });
    expect(onChoose).not.toHaveBeenCalled();
  });
});
