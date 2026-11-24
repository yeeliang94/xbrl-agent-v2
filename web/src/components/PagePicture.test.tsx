import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PagePicture } from "./PagePicture";

describe("Page picture", () => {
  it("shows the page, and a quiet line when the run has no page picture", () => {
    render(<PagePicture runId={1} page={7} />);
    const picture = screen.getByRole("img", { name: "Page 7" });
    expect(picture).toHaveAttribute("src", "/api/runs/1/pages/7/image");
    fireEvent.error(picture);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("No page picture for this run")).toBeInTheDocument();
  });
});
