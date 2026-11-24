import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { admin, member, mockFetch, models, settings } from "../test-utils";
import { SettingsPage } from "./SettingsPage";

afterEach(() => vi.unstubAllGlobals());

const firm = (lines: string[], version = 1) => ({
  company_id: null, version, lines, saved_by: "aina@firm.my", saved_at: "2026-11-22T09:00:00Z", source: "typed", comment_id: null, restored_from: null,
});

function routes(extra = {}) {
  return {
    "GET /api/settings": { body: settings() },
    "GET /api/models": { body: { models } },
    "GET /api/guidance/firm": { body: { guidance: firm(["Leave non-controlling interest blank when the report prints no split."]), versions: [] } },
    ...extra,
  };
}

describe("Settings page", () => {
  it("lists the models and blocks the unavailable ones", async () => {
    mockFetch(routes());
    render(<SettingsPage user={admin} />);
    const reading = (await screen.findByLabelText("Reading")) as HTMLSelectElement;
    expect(reading.value).toBe("gpt-6-luna");
    const options = Array.from(reading.options).map((o) => [o.textContent, o.disabled]);
    expect(options).toEqual([
      ["GPT-6 Luna", false],
      ["GPT-6.1 Terra", false],
      ["Claude Opus 5.5", true],
    ]);
    expect(screen.getByLabelText("Extraction")).toBeInTheDocument();
    expect(screen.getByLabelText("Review")).toBeInTheDocument();
    expect(screen.getByText("Direct")).toBeInTheDocument();
  });

  it("offers exactly the house-style values the contract allows", async () => {
    mockFetch(routes());
    render(<SettingsPage user={admin} />);
    const values = async (label: string) =>
      Array.from(((await screen.findByLabelText(label)) as HTMLSelectElement).options).map((o) => o.value);
    expect(await values("Body text")).toEqual(["justified", "left"]);
    expect(await values("Table font size")).toEqual(["9", "10", "11"]);
    expect(await values("Smallest table font")).toEqual(["8", "9"]);
    expect(await values("Double underline")).toEqual(["thick_bottom_border", "single_bottom_border"]);
  });

  it("shows the gateway set-up when it is live", async () => {
    mockFetch(routes({ "GET /api/settings": { body: { ...settings(), route: "gateway" } } }));
    render(<SettingsPage user={admin} />);
    expect(await screen.findByText("Gateway")).toBeInTheDocument();
  });

  it("saves only the field that changed", async () => {
    const puts: unknown[] = [];
    mockFetch(
      routes({
        "PUT /api/settings": (init: RequestInit | undefined) => {
          const change = JSON.parse(String(init?.body));
          puts.push(change);
          const current = settings();
          return {
            body: {
              ...current,
              ...change,
              models: { ...current.models, ...change.models },
              house_style: { ...current.house_style, ...change.house_style },
            },
          };
        },
      }),
    );
    render(<SettingsPage user={admin} />);
    fireEvent.change(await screen.findByLabelText("Extraction"), { target: { value: "gpt-6.1-terra" } });
    await waitFor(() => expect((screen.getByLabelText("Extraction") as HTMLSelectElement).value).toBe("gpt-6.1-terra"));
    expect(puts[0]).toEqual({ models: { extraction: "gpt-6.1-terra" } });

    fireEvent.click(screen.getByRole("switch", { name: "Code workbench" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Code workbench" })).toHaveAttribute("aria-checked", "false"));
    expect(puts[1]).toEqual({ code_workbench: false });

    fireEvent.change(screen.getByLabelText("Table font size"), { target: { value: "11" } });
    await waitFor(() => expect((screen.getByLabelText("Table font size") as HTMLSelectElement).value).toBe("11"));
    expect(puts[2]).toEqual({ house_style: { table_font_pt: 11 } });
  });

  it("says it is loading until both requests return", async () => {
    let answer: (value: Response) => void = () => {};
    const fetch = mockFetch(routes());
    const models = new Promise<Response>((resolve) => (answer = resolve));
    const real = fetch.getMockImplementation()!;
    fetch.mockImplementation((input, init) => (String(input) === "/api/models" ? models : real(input, init)));
    render(<SettingsPage user={admin} />);
    expect(screen.getByText("Loading settings")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByText("Loading settings")).toBeInTheDocument();
    expect(screen.queryByLabelText("Reading")).not.toBeInTheDocument();
    answer(new Response(JSON.stringify({ models: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    expect(await screen.findByLabelText("Reading")).toBeInTheDocument();
    expect(screen.queryByText("Loading settings")).not.toBeInTheDocument();
  });

  it("shows only the error line when loading fails", async () => {
    mockFetch(routes({ "GET /api/models": { status: 500, body: { detail: "The model list could not be read." } } }));
    render(<SettingsPage user={admin} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The model list could not be read.");
    expect(screen.queryByText("Loading settings")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("notes a model outside the known families beside its role", async () => {
    const odd = { id: "gpt-7-nova", provider: "openai" as const, family: "other" as const, label: "GPT-7 Nova", available: true };
    const saved = { ...settings(), models: { reading: "gpt-6-luna", extraction: "gpt-7-nova", review: "gpt-6-luna" } };
    mockFetch(routes({ "GET /api/settings": { body: saved }, "GET /api/models": { body: { models: [...models, odd] } } }));
    render(<SettingsPage user={admin} />);
    await screen.findByLabelText("Reading");
    const notices = screen.getAllByText("Not a recognised model family. Default settings are used.");
    expect(notices).toHaveLength(1);
    expect(notices[0].closest(".line")).toHaveTextContent(/^Extraction/);
  });

  it("shows the server's sentence when a save fails", async () => {
    mockFetch(routes({ "PUT /api/settings": { status: 400, body: { detail: "That model cannot be used." } } }));
    render(<SettingsPage user={admin} />);
    fireEvent.click(await screen.findByRole("switch", { name: "Bold totals" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That model cannot be used.");
    // Beside the control that failed, not above the panels.
    expect(alert.closest(".line")).toContainElement(screen.getByRole("switch", { name: "Bold totals" }));
    expect(screen.getByRole("switch", { name: "Bold totals" })).toHaveAttribute("aria-checked", "false");
  });

  it("clears a save error when the next save works, and shows a new one beside its own control", async () => {
    let fail = true;
    mockFetch(routes({ "PUT /api/settings": () => (fail ? { status: 422, body: { detail: "Pick a listed model." } } : { body: settings() }) }));
    render(<SettingsPage user={admin} />);
    fireEvent.change(await screen.findByLabelText("Review"), { target: { value: "gpt-6.1-terra" } });
    const alert = await screen.findByRole("alert");
    expect(alert.closest(".line")).toContainElement(screen.getByLabelText("Review"));
    fail = false;
    fireEvent.click(screen.getByRole("switch", { name: "Bold totals" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("tells someone who is not an admin why the controls are greyed out", async () => {
    mockFetch(routes());
    render(<SettingsPage user={member} />);
    expect(await screen.findByText("Only an admin can change these settings.")).toBeInTheDocument();
  });

  it("does not show the admin note to an admin", async () => {
    mockFetch(routes());
    render(<SettingsPage user={admin} />);
    await screen.findByLabelText("Reading");
    expect(screen.queryByText("Only an admin can change these settings.")).toBeNull();
  });

  it("is read-only for a user who is not an admin", async () => {
    const fetch = mockFetch(routes());
    render(<SettingsPage user={member} />);
    await screen.findByLabelText("Reading");
    for (const control of [...screen.getAllByRole("combobox"), ...screen.getAllByRole("switch")]) {
      expect(control).toBeDisabled();
    }
    fireEvent.click(screen.getByRole("switch", { name: "Code workbench" }));
    expect(fetch.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("offers the sign-in limits and saves one at a time", async () => {
    const puts: unknown[] = [];
    mockFetch(
      routes({
        "PUT /api/settings": (init: RequestInit | undefined) => {
          const change = JSON.parse(String(init?.body));
          puts.push(change);
          return { body: { ...settings(), login: { ...settings().login, ...change.login } } };
        },
      }),
    );
    render(<SettingsPage user={admin} />);
    const idle = (await screen.findByLabelText("Sign out after idle")) as HTMLSelectElement;
    expect(idle.value).toBe("60");
    expect(Array.from(idle.options).map((o) => o.textContent)).toContain("1 hour");
    expect((screen.getByLabelText("Attempts before lockout") as HTMLSelectElement).value).toBe("5");
    expect((screen.getByLabelText("Lockout time") as HTMLSelectElement).value).toBe("15");
    fireEvent.change(screen.getByLabelText("Lockout time"), { target: { value: "30" } });
    await waitFor(() => expect((screen.getByLabelText("Lockout time") as HTMLSelectElement).value).toBe("30"));
    expect(puts).toEqual([{ login: { lockout_minutes: 30 } }]);
  });

  it("keeps a saved sign-in limit that is not among the choices", async () => {
    mockFetch(routes({ "GET /api/settings": { body: { ...settings(), login: { idle_timeout_minutes: 45, max_attempts: 7, lockout_minutes: 15 } } } }));
    render(<SettingsPage user={admin} />);
    expect(((await screen.findByLabelText("Sign out after idle")) as HTMLSelectElement).value).toBe("45");
    expect((screen.getByLabelText("Attempts before lockout") as HTMLSelectElement).value).toBe("7");
  });

  it("downloads the server logs and the usage for an admin", async () => {
    const fetch = mockFetch(routes({ "GET /api/settings/records/logs": { body: {} }, "GET /api/settings/records/usage": { body: {} } }));
    const created = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<SettingsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Download server logs" }));
    await waitFor(() => expect(created).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Download usage" }));
    await waitFor(() => expect(created).toHaveBeenCalledTimes(2));
    const urls = fetch.mock.calls.map(([url]) => String(url));
    expect(urls).toContain("/api/settings/records/logs");
    expect(urls).toContain("/api/settings/records/usage");
    expect(click).toHaveBeenCalledTimes(2);
    click.mockRestore();
  });

  it("shows the server's sentence when a download fails", async () => {
    mockFetch(routes({ "GET /api/settings/records/usage": { status: 403, body: { detail: "Only an admin can do this." } } }));
    render(<SettingsPage user={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Download usage" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only an admin can do this.");
  });

  it("does not offer the records to someone who is not an admin", async () => {
    mockFetch(routes());
    render(<SettingsPage user={member} />);
    expect(await screen.findByRole("button", { name: "Download server logs" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download usage" })).toBeDisabled();
  });

  it("lets an admin add a line of firm guidance as a new version", async () => {
    const puts: unknown[] = [];
    mockFetch(
      routes({
        "PUT /api/guidance/firm": (init: RequestInit | undefined) => {
          const body = JSON.parse(String(init?.body));
          puts.push(body);
          return { body: { guidance: firm(body.lines, 2), versions: [] } };
        },
      }),
    );
    render(<SettingsPage user={admin} />);
    fireEvent.change(await screen.findByLabelText("Add to firm guidance"), { target: { value: "Goods in transit are part of inventories." } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Goods in transit are part of inventories.")).toBeInTheDocument();
    expect(puts).toEqual([{ based_on: 1, lines: ["Leave non-controlling interest blank when the report prints no split.", "Goods in transit are part of inventories."] }]);
  });

  it("shows firm guidance read-only to someone who is not an admin", async () => {
    mockFetch(routes());
    render(<SettingsPage user={member} />);
    expect(await screen.findByText("Leave non-controlling interest blank when the report prints no split.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Add to firm guidance")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });
});
