import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PagePicture } from "./PagePicture";

describe("Page picture", () => {
  it("shows the page once its picture loads", () => {
    render(<PagePicture runId={1} page={7} />);
    expect(screen.queryByRole("img")).toBeNull();
    const picture = screen.getByRole("img", { name: "Page 7", hidden: true });
    expect(picture).toHaveAttribute("src", "/api/runs/1/pages/7/image");
    fireEvent.load(picture);
    expect(screen.getByRole("img", { name: "Page 7" })).toBeVisible();
    expect(screen.getByText("Page 7")).toBeInTheDocument();
  });

  it("leaves nothing in its place when the run has no page picture", () => {
    const { container } = render(<PagePicture runId={1} page={7} />);
    fireEvent.error(screen.getByRole("img", { name: "Page 7", hidden: true }));
    expect(container).toBeEmptyDOMElement();
  });

  it("says quietly that there is no picture when the page is opened on its own", () => {
    render(<PagePicture runId={1} page={7} titled={false} />);
    fireEvent.error(screen.getByRole("img", { name: "Page 7" }));
    expect(screen.getByText("No page picture for this run")).toBeInTheDocument();
  });
});
