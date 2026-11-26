import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { admin, member, mockFetch, run } from "../test-utils";
import { AppShell } from "./AppShell";

afterEach(() => vi.unstubAllGlobals());

const shell = (runId: number | null, version: string | null = null, user = member) =>
  render(
    <AppShell user={user} nav={[]} onLogout={() => {}} runId={runId} version={version}>
      <h1>Page</h1>
    </AppShell>,
  );

const forms = (fetch: ReturnType<typeof mockFetch>) =>
  fetch.mock.calls.filter(([url, init]) => String(url) === "/api/issues" && init?.method === "POST").map(([, init]) => init!.body as FormData);

describe("Report an issue, from the shell", () => {
  it("sends the report with the run on screen and the attached screenshot", async () => {
    const detail = { ...run({ id: 7, company: "Demo Durian Trading Sdn Bhd", year: 2025 }), statements: [], failure: null, working_on: null, open_question_id: null, stages: [] };
    const fetch = mockFetch({ "GET /api/runs/7": { body: { run: detail } }, "POST /api/issues": { body: { issue: { id: 15 } } } });
    shell(7);
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("Demo Durian Trading Sdn Bhd, FY2025")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Send" })).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText("What went wrong"), { target: { value: "  The cash flow statement shows last year in both columns.  " } });
    const picture = new File(["png"], "screenshot-25-nov.png", { type: "image/png" });
    fireEvent.change(within(dialog).getByLabelText("Screenshot file"), { target: { files: [picture] } });
    expect(within(dialog).getByText("screenshot-25-nov.png")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("heading", { name: "Issue 15 sent" })).toBeInTheDocument();
    expect(screen.getByText("The admins can see it now, with this run linked.")).toBeInTheDocument();
    const [form] = forms(fetch);
    expect(form.get("text")).toBe("The cash flow statement shows last year in both columns.");
    expect(form.get("run_id")).toBe("7");
    expect((form.get("file") as File).name).toBe("screenshot-25-nov.png");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("sends a report with no run and no screenshot", async () => {
    const fetch = mockFetch({ "POST /api/issues": { body: { issue: { id: 16 } } } });
    shell(null);
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByText("Run")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("What went wrong"), { target: { value: "I could not log in this morning." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(await screen.findByText("The admins can see it now.")).toBeInTheDocument();
    const [form] = forms(fetch);
    expect(form.has("run_id")).toBe(false);
    expect(form.has("file")).toBe(false);
  });

  it("removes an attached screenshot, and keeps the words when the server refuses", async () => {
    const fetch = mockFetch({ "POST /api/issues": { status: 422, body: { detail: "Attach a picture: a PNG, JPEG, GIF or WebP file." } } });
    shell(null);
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    fireEvent.change(screen.getByLabelText("What went wrong"), { target: { value: "The total is wrong." } });
    fireEvent.change(screen.getByLabelText("Screenshot file"), { target: { files: [new File(["x"], "notes.txt")] } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Attach a picture: a PNG, JPEG, GIF or WebP file.");
    expect((screen.getByLabelText("What went wrong") as HTMLTextAreaElement).value).toBe("The total is wrong.");

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("button", { name: "Attach a screenshot" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(forms(fetch)).toHaveLength(2));
    expect(forms(fetch)[1].has("file")).toBe(false);
  });

  it("starts empty each time it is opened", () => {
    mockFetch({});
    shell(null);
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    fireEvent.change(screen.getByLabelText("What went wrong"), { target: { value: "Half a thought" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    expect((screen.getByLabelText("What went wrong") as HTMLTextAreaElement).value).toBe("");
  });
});

describe("The version in the shell", () => {
  it("is shown once known, and left out until then", () => {
    mockFetch({});
    const { unmount } = shell(null, "0.1.0", admin);
    expect(screen.getByText("Version 0.1.0")).toBeInTheDocument();
    unmount();
    shell(null, null, admin);
    expect(screen.queryByText(/^Version/)).toBeNull();
  });
});
