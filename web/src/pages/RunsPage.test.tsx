import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { admin, mockFetch, run } from "../test-utils";
import { RunsPage } from "./RunsPage";
import { formatUpdated } from "./runStatus";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("Runs page", () => {
  it("says so when there are no runs", async () => {
    mockFetch({ "GET /api/runs": { body: { runs: [] } } });
    render(<RunsPage user={admin} />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
  });

  it("opens the New run page from its button", async () => {
    mockFetch({ "GET /api/runs": { body: { runs: [] } } });
    render(<RunsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    expect(window.location.hash).toBe("#/runs/new");
  });

  it("shows a reading run by its file name and opens its setup", async () => {
    mockFetch({
      "GET /api/runs": {
        body: { runs: [run({ id: 9, company: null, year: null, standard: null, level: null, status: "reading", filename: "Doc 3.pdf" })] },
      },
    });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Doc 3.pdf")).closest("tr")!;
    const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(0, 4)).toEqual(["Doc 3.pdf", "", "", "Reading"]);
    expect(row.textContent).not.toContain("null");
    expect(within(row).getByText("Reading").closest("[data-kind]")).toHaveAttribute("data-kind", "working");
    fireEvent.click(row);
    expect(window.location.hash).toBe("#/runs/9/setup");
  });

  it("makes only a run that opens something look clickable", async () => {
    window.location.hash = "#/runs";
    mockFetch({
      "GET /api/runs": {
        body: { runs: [run({ id: 9, company: null, status: "setup", filename: "Doc 3.pdf" }), run({ id: 4, company: "Demo", status: "setup", filename: null })] },
      },
    });
    render(<RunsPage user={admin} />);
    const opens = (await screen.findByText("Doc 3.pdf")).closest("tr")!;
    const stays = screen.getByText("Demo").closest("tr")!;
    expect(opens).toHaveClass("click");
    expect(stays).not.toHaveClass("click");
    fireEvent.click(stays);
    expect(window.location.hash).toBe("#/runs");
  });

  it.each([
    ["extracting", null, "#/runs/4"],
    ["ready", null, "#/runs/4"],
    ["in_review", null, "#/runs/4"],
    ["correcting", null, "#/runs/4"],
    ["failed", "extract", "#/runs/4"],
    ["failed", "read", "#/runs/4/setup"],
    ["setup", null, "#/runs/4/setup"],
    ["needs_answer", null, "#/runs/4"],
  ] as const)("opens a %s run (failed stage %s) at %s", async (status, failed_stage, hash) => {
    mockFetch({ "GET /api/runs": { body: { runs: [run({ id: 4, status, failed_stage })] } } });
    render(<RunsPage user={admin} />);
    fireEvent.click((await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!);
    expect(window.location.hash).toBe(hash);
  });

  it("shows a confirmed run as ready", async () => {
    mockFetch({ "GET /api/runs": { body: { runs: [run({ status: "ready" })] } } });
    render(<RunsPage user={admin} />);
    expect((await screen.findByText("Ready")).closest("[data-kind]")).toHaveAttribute("data-kind", "neutral");
  });

  it("shows a run from the contract shape", async () => {
    mockFetch({ "GET /api/runs": { body: { runs: [run({ status: "failed", level: "Group", owner_name: "Hafiz M." })] } } });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!;
    const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(0, 4)).toEqual(["Seri Maju Trading Sdn. Bhd.", "2025", "MFRS, Group", "Failed"]);
    expect(cells[5]).toBe("Hafiz M.");
    expect(within(row).getByText("Failed").closest("[data-kind]")).toHaveAttribute("data-kind", "failure");
  });

  it("leaves the year cell empty when the year is not known", async () => {
    mockFetch({ "GET /api/runs": { body: { runs: [run({ year: null })] } } });
    render(<RunsPage user={admin} />);
    const row = (await screen.findByText("Seri Maju Trading Sdn. Bhd.")).closest("tr")!;
    expect(within(row).getAllByRole("cell")[1].textContent).toBe("");
  });

  it("maps each status to the right look", async () => {
    mockFetch({
      "GET /api/runs": {
        body: {
          runs: [
            run({ id: 1, status: "extracting" }),
            run({ id: 2, status: "in_review" }),
            run({ id: 3, status: "filed" }),
            run({ id: 4, status: "stopped" }),
            run({ id: 5, status: "needs_answer" }),
          ],
        },
      },
    });
    render(<RunsPage user={admin} />);
    await screen.findByText("Extracting");
    const table = within(screen.getByRole("table"));
    const kind = async (word: string) => (await table.findByText(word)).closest("[data-kind]")?.getAttribute("data-kind");
    expect(await kind("Extracting")).toBe("working");
    expect(await kind("In review")).toBe("attention");
    expect(await kind("Filed")).toBe("finished");
    expect(await kind("Stopped")).toBe("neutral");
    expect(await kind("Needs you")).toBe("attention");
  });

  it("filters to mine by email, not by name", async () => {
    mockFetch({
      "GET /api/runs": {
        body: {
          runs: [
            run({ id: 1, company: "Alpha Sdn. Bhd.", status: "in_review", owner_name: "Aina Rahman", owner_email: "aina@firm.my" }),
            run({ id: 2, company: "Beta Sdn. Bhd.", status: "filed", owner_name: "A. Rahman", owner_email: "aina@firm.my" }),
            run({ id: 3, company: "Gamma Berhad", status: "in_review", owner_name: "Aina R.", owner_email: "aina.r@other.my" }),
          ],
        },
      },
    });
    render(<RunsPage user={admin} />);
    await screen.findByText("Alpha Sdn. Bhd.");
    const companies = () => screen.getAllByRole("row").slice(1).map((row) => row.firstChild?.textContent);

    fireEvent.click(screen.getByRole("radio", { name: "Mine" }));
    expect(companies()).toEqual(["Alpha Sdn. Bhd.", "Beta Sdn. Bhd."]);

    fireEvent.click(screen.getByRole("radio", { name: "In review" }));
    expect(companies()).toEqual(["Alpha Sdn. Bhd.", "Gamma Berhad"]);

    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    expect(companies()).toHaveLength(3);
  });

  it("shows the server's sentence when the list fails", async () => {
    mockFetch({ "GET /api/runs": { status: 500, body: { detail: "The run list could not be read." } } });
    render(<RunsPage user={admin} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The run list could not be read.");
  });

  it("writes the update time plainly", () => {
    const now = new Date(2026, 10, 18, 15, 0);
    expect(formatUpdated(new Date(2026, 10, 18, 9, 14).toISOString(), now)).toBe("Today, 09:14");
    expect(formatUpdated(new Date(2026, 10, 17, 9, 14).toISOString(), now)).toBe("Yesterday");
    expect(formatUpdated(new Date(2026, 10, 12, 9, 14).toISOString(), now)).toBe("12 Nov");
    expect(formatUpdated(new Date(2025, 10, 12, 9, 14).toISOString(), now)).toBe("12 Nov 2025");
  });
});
