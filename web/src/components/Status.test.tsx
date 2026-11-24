import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Status, type StatusKind } from "./Status";

describe("Status", () => {
  it.each<StatusKind>(["finished", "attention", "neutral"])("shows a dot and the word for %s", (kind) => {
    const { container } = render(<Status kind={kind}>Word</Status>);
    expect(screen.getByText("Word")).toHaveAttribute("data-kind", kind);
    expect(container.querySelector(".status-dot")).not.toBeNull();
    expect(container.querySelector(".spin")).toBeNull();
  });

  it("shows a failure as a filled label with no dot", () => {
    const { container } = render(<Status kind="failure">Failed</Status>);
    expect(screen.getByText("Failed")).toHaveAttribute("data-kind", "failure");
    expect(container.querySelector(".status-dot")).toBeNull();
    expect(container.querySelector(".spin")).toBeNull();
  });

  it("shows the spinner instead of the dot while working", () => {
    const { container } = render(<Status kind="working">Extracting</Status>);
    expect(screen.getByText("Extracting")).toHaveAttribute("data-kind", "working");
    expect(container.querySelector(".spin")).not.toBeNull();
    expect(container.querySelector(".status-dot")).toBeNull();
  });
});
