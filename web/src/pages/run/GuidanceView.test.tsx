import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../../test-utils";
import { guidance } from "./fixtures";
import { GuidanceView } from "./GuidanceView";

afterEach(() => vi.unstubAllGlobals());

const LINE = "Goods in transit are part of inventories.";

function routes(extra = {}) {
  return {
    "GET /api/runs/1/guidance": { body: { firm: guidance(["Leave non-controlling interest blank."], 1, null), company: guidance([LINE], 2), company_id: 4 } },
    "GET /api/companies/4/guidance": { body: { company: { id: 4, name: "Seri Maju" }, guidance: guidance([LINE], 2), versions: [] } },
    "GET /api/guidance/firm": { body: { guidance: guidance(["Leave non-controlling interest blank."], 1, null), versions: [] } },
    ...extra,
  };
}

describe("Run guidance", () => {
  it("shows the company's guidance to change and the firm's to read", async () => {
    mockFetch(routes());
    render(<GuidanceView runId={1} />);
    expect(await screen.findByText(LINE)).toBeInTheDocument();
    expect(await screen.findByText("Leave non-controlling interest blank.")).toBeInTheDocument();
    expect(screen.getByLabelText("Add to guidance for this company")).toBeInTheDocument();
    expect(screen.queryByLabelText("Add to firm guidance")).toBeNull();
  });

  it("removes a line by saving a new version based on the one shown", async () => {
    const puts: unknown[] = [];
    mockFetch(
      routes({
        "PUT /api/companies/4/guidance": (init: RequestInit | undefined) => {
          puts.push(JSON.parse(String(init?.body)));
          return { body: { guidance: guidance([], 3), versions: [] } };
        },
      }),
    );
    render(<GuidanceView runId={1} />);
    fireEvent.click(await screen.findByRole("button", { name: `Remove "${LINE}"` }));
    await waitFor(() => expect(screen.queryByText(LINE)).toBeNull());
    expect(puts).toEqual([{ based_on: 2, lines: [] }]);
  });

  it("shows a stale save's sentence beside the panel and reloads the newer version", async () => {
    let reads = 0;
    mockFetch(
      routes({
        "GET /api/companies/4/guidance": () => {
          reads += 1;
          const lines = reads === 1 ? [LINE] : [LINE, "Added by someone else."];
          return { body: { company: { id: 4, name: "Seri Maju" }, guidance: guidance(lines, reads + 1), versions: [] } };
        },
        "PUT /api/companies/4/guidance": { status: 409, body: { detail: "Someone else changed this guidance. Reload it and try again." } },
      }),
    );
    render(<GuidanceView runId={1} />);
    fireEvent.change(await screen.findByLabelText("Add to guidance for this company"), { target: { value: "New line." } });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Someone else changed this guidance.");
    expect(alert.closest(".line")).toHaveTextContent("Guidance for this company");
    expect(await screen.findByText("Added by someone else.")).toBeInTheDocument();
  });

  it("says when the run has no company yet", async () => {
    mockFetch(routes({ "GET /api/runs/1/guidance": { body: { firm: guidance([], 0, null), company: null, company_id: null } } }));
    render(<GuidanceView runId={1} />);
    expect(await screen.findByText("This run has no company yet.")).toBeInTheDocument();
  });
});
