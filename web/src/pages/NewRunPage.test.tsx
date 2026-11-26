import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, run } from "../test-utils";
import { fileSize, fileType, NewRunPage } from "./NewRunPage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const pdf = () => new File(["%PDF-1.7"], "Doc 3.pdf", { type: "application/pdf" });
const choose = (files: File[]) => fireEvent.change(screen.getByLabelText("PDF, Word or Excel files"), { target: { files } });

describe("New run page", () => {
  it("asks for a PDF, Word or Excel file, one or several", () => {
    mockFetch({});
    render(<NewRunPage />);
    expect(screen.getByText("Drop a PDF, Word or Excel file")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
    const input = screen.getByLabelText("PDF, Word or Excel files");
    expect(input).toHaveAttribute("accept", ".pdf,.docx,.xlsx");
    expect(input).toHaveAttribute("multiple");
  });

  it("shows a chosen file with its kind and size, then uploads it and goes to its setup", async () => {
    const fetch = mockFetch({ "POST /api/runs": { body: { run: run({ id: 12, status: "reading" }), document: {} } } });
    render(<NewRunPage />);
    choose([new File(["PK"], "Statements 2025.docx")]);
    expect(screen.getByText("Statements 2025.docx")).toBeInTheDocument();
    expect(screen.getByText("Word document")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(window.location.hash).toBe("#/runs/12/setup"));
    const [, init] = fetch.mock.calls.find(([url]) => url === "/api/runs")!;
    expect(((init?.body as FormData).get("file") as File).name).toBe("Statements 2025.docx");
  });

  it("lets a chosen file be removed before upload", () => {
    mockFetch({});
    render(<NewRunPage />);
    choose([pdf()]);
    fireEvent.click(screen.getByRole("button", { name: "Remove Doc 3.pdf" }));
    expect(screen.getByText("Drop a PDF, Word or Excel file")).toBeInTheDocument();
  });

  it("takes a dropped file", async () => {
    mockFetch({ "POST /api/runs": { body: { run: run({ id: 4 }), document: {} } } });
    render(<NewRunPage />);
    fireEvent.drop(screen.getByText("Drop a PDF, Word or Excel file").closest(".drop")!, { dataTransfer: { files: [pdf()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(window.location.hash).toBe("#/runs/4/setup"));
  });

  it("shows the server's refusal as a failure and stays", async () => {
    const refusal = "Old.doc is in the old Word format. Save it as .docx and upload that.";
    mockFetch({ "POST /api/runs": { status: 422, body: { detail: refusal } } });
    render(<NewRunPage />);
    choose([new File(["x"], "Old.doc")]);
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.getByText("Not uploaded").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
  });

  it("makes each of several files its own run waiting at setup, and says which were refused", async () => {
    let next = 20;
    const fetch = mockFetch({
      "POST /api/runs": (init) => {
        const name = ((init?.body as FormData).get("file") as File).name;
        if (name === "Locked.xlsx") return { status: 422, body: { detail: "Locked.xlsx is protected by a password. Remove the password and upload it again." } };
        next += 1;
        return { body: { run: run({ id: next, status: "reading" }), document: {} } };
      },
    });
    render(<NewRunPage />);
    choose([pdf(), new File(["PK"], "Accounts.xlsx"), new File(["PK"], "Locked.xlsx")]);
    fireEvent.click(screen.getByRole("button", { name: "Start 3 runs" }));

    expect(await screen.findByText("2 runs waiting at setup")).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([url]) => url === "/api/runs")).toHaveLength(3);
    expect(screen.getByText("Locked.xlsx is protected by a password. Remove the password and upload it again.")).toBeInTheDocument();
    expect(screen.getAllByText("Uploaded")).toHaveLength(2);
    expect(screen.getByText("Refused").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
    expect(window.location.hash).toBe("");
    fireEvent.click(screen.getAllByRole("button", { name: "Set up" })[0]);
    expect(window.location.hash).toMatch(/^#\/runs\/2[12]\/setup$/);
    expect(screen.getByRole("button", { name: "Add more files" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View runs" }));
    expect(window.location.hash).toBe("#/runs");
  });

  it("names each kind and size in plain words", () => {
    expect([fileType("a.PDF"), fileType("b.docx"), fileType("c.xlsx"), fileType("d.csv")]).toEqual(["PDF", "Word document", "Excel workbook", ""]);
    expect([fileSize(4.2 * 1024 * 1024), fileSize(10)]).toEqual(["4.2 MB", "0.1 MB"]);
  });
});
