import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, run } from "../test-utils";
import { NewRunPage } from "./NewRunPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const pdf = () => new File(["%PDF-1.7"], "Doc 3.pdf", { type: "application/pdf" });

describe("New run page", () => {
  it("asks for a PDF only", () => {
    mockFetch({});
    render(<NewRunPage />);
    expect(screen.getByText("Drop a PDF")).toBeInTheDocument();
    expect(screen.queryByText(/Word/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
    expect(screen.getByLabelText("PDF file")).toHaveAttribute("accept", ".pdf,application/pdf");
  });

  it("uploads the chosen file and goes to the run's setup", async () => {
    const fetch = mockFetch({ "POST /api/runs": { body: { run: run({ id: 12, status: "reading" }), document: {} } } });
    render(<NewRunPage />);
    fireEvent.change(screen.getByLabelText("PDF file"), { target: { files: [pdf()] } });
    await waitFor(() => expect(window.location.hash).toBe("#/runs/12/setup"));
    const [, init] = fetch.mock.calls.find(([url]) => url === "/api/runs")!;
    const body = init?.body as FormData;
    expect((body.get("file") as File).name).toBe("Doc 3.pdf");
  });

  it("takes a dropped file", async () => {
    mockFetch({ "POST /api/runs": { body: { run: run({ id: 4 }), document: {} } } });
    render(<NewRunPage />);
    fireEvent.drop(screen.getByText("Drop a PDF").closest(".drop")!, { dataTransfer: { files: [pdf()] } });
    await waitFor(() => expect(window.location.hash).toBe("#/runs/4/setup"));
  });

  it("shows the server's refusal as a failure and stays", async () => {
    mockFetch({ "POST /api/runs": { status: 422, body: { detail: "Save the Word file as a PDF in Word, then upload the PDF." } } });
    render(<NewRunPage />);
    fireEvent.change(screen.getByLabelText("PDF file"), { target: { files: [new File(["x"], "a.docx")] } });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Save the Word file as a PDF in Word, then upload the PDF.");
    expect(screen.getByText("Upload failed").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
  });
});
