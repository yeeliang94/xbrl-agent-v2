import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Switch } from "./Switch";

function Harness({ onChange }: { onChange?: (v: boolean) => void }) {
  const [on, setOn] = useState(false);
  return (
    <Switch
      label="Bold totals"
      checked={on}
      onChange={(v) => {
        setOn(v);
        onChange?.(v);
      }}
    />
  );
}

describe("Switch", () => {
  it("toggles on click", () => {
    render(<Harness />);
    const sw = screen.getByRole("switch", { name: "Bold totals" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("toggles once with Space or Enter", () => {
    const changes = vi.fn();
    render(<Harness onChange={changes} />);
    const sw = screen.getByRole("switch");
    fireEvent.keyDown(sw, { key: " " });
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(sw, { key: "Enter" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.keyDown(sw, { key: "a" });
    expect(changes).toHaveBeenCalledTimes(2);
  });

  it("does nothing when disabled", () => {
    const changes = vi.fn();
    render(<Switch label="Locked" checked={false} onChange={changes} disabled />);
    fireEvent.click(screen.getByRole("switch"));
    fireEvent.keyDown(screen.getByRole("switch"), { key: " " });
    expect(changes).not.toHaveBeenCalled();
  });
});
