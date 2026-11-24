import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <Dialog
        open={open}
        title="Prepare mTool file"
        onClose={() => setOpen(false)}
        actions={
          <>
            <Button variant="quiet" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary">Prepare</Button>
          </>
        }
      />
    </>
  );
}

describe("Dialog", () => {
  it("opens and closes with its buttons", () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).toBeNull();
    screen.getByRole("button", { name: "Open" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("dialog", { name: "Prepare mTool file" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("closes with Escape and with a click outside", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.mouseDown(screen.getByRole("dialog").parentElement!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps Tab inside the dialog", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    const prepare = screen.getByRole("button", { name: "Prepare" });
    prepare.focus();
    fireEvent.keyDown(prepare, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("button", { name: "Cancel" }), { key: "Tab", shiftKey: true });
    expect(prepare).toHaveFocus();
  });
});
