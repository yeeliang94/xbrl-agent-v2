import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Segmented } from "./Segmented";

const OPTIONS = [
  { value: "all", label: "All" },
  { value: "mine", label: "Mine" },
  { value: "review", label: "In review" },
];

function Harness() {
  const [value, setValue] = useState("all");
  return <Segmented label="Show" options={OPTIONS} value={value} onChange={setValue} />;
}

const checked = () => screen.getAllByRole("radio").find((r) => r.getAttribute("aria-checked") === "true")?.textContent;

describe("Segmented control", () => {
  it("selects the clicked choice", () => {
    render(<Harness />);
    expect(checked()).toBe("All");
    fireEvent.click(screen.getByRole("radio", { name: "In review" }));
    expect(checked()).toBe("In review");
  });

  it("moves with the arrow keys and wraps round", () => {
    render(<Harness />);
    const all = screen.getByRole("radio", { name: "All" });
    all.focus();
    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(checked()).toBe("Mine");
    expect(screen.getByRole("radio", { name: "Mine" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("radio", { name: "Mine" }), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("radio", { name: "All" }), { key: "ArrowLeft" });
    expect(checked()).toBe("In review");
  });

  it("keeps only the chosen item in the tab order", () => {
    render(<Harness />);
    const tabbable = screen.getAllByRole("radio").filter((r) => r.tabIndex === 0);
    expect(tabbable.map((r) => r.textContent)).toEqual(["All"]);
  });
});
