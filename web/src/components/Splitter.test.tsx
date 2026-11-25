import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Splitter } from "./Splitter";

function Harness({ panel }: { panel: "start" | "end" }) {
  const [width, setWidth] = useState(400);
  return <Splitter label="Side panel width" width={width} min={320} max={() => 440} panel={panel} onChange={setWidth} at="0px" />;
}

describe("Splitter", () => {
  it("resizes a side panel with the arrow keys, never past its minimum or maximum", () => {
    render(<Harness panel="end" />);
    const handle = screen.getByRole("separator", { name: "Side panel width" });
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "416");
    for (let i = 0; i < 5; i++) fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "440");
    for (let i = 0; i < 20; i++) fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle).toHaveAttribute("aria-valuenow", "320");
  });
});
