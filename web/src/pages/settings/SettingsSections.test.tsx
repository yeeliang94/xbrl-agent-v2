import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminUser, AuditEntry, Issue, User } from "../../api";
import { mockFetch, models, settings } from "../../test-utils";
import { SettingsPage } from "../SettingsPage";

afterEach(() => vi.unstubAllGlobals());

const mira: User = { email: "mira@samplefirm.example", name: "Mira Quillfeather", is_admin: true, must_change_password: false };
const odell: User = { email: "odell@samplefirm.example", name: "Odell Brambleworth", is_admin: false, must_change_password: false };

const account = (user: User, over: Partial<AdminUser> = {}): AdminUser => ({
  ...user,
  disabled: false,
  has_password: true,
  created_at: "2026-10-01T08:00:00.000000Z",
  password_set_at: "2026-10-01T08:00:00.000000Z",
  last_sign_in_at: "2026-11-25T09:12:00.000000Z",
  ...over,
});
const jonty = account({ email: "jonty@samplefirm.example", name: "Jonty Applecross", is_admin: false, must_change_password: false }, { disabled: true, last_sign_in_at: null });

const base = {
  "GET /api/settings": { body: settings() },
  "GET /api/models": { body: { models } },
};

function show(user: User, section: string, routes: Record<string, unknown> = {}) {
  const fetch = mockFetch({ ...base, ...routes } as Parameters<typeof mockFetch>[0]);
  render(<SettingsPage user={user} />);
  fireEvent.click(screen.getByRole("radio", { name: section }));
  return fetch;
}

const sent = (fetch: ReturnType<typeof mockFetch>, method: string) =>
  fetch.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method).map(([url, init]) => ({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined }));

describe("Settings sections by role", () => {
  it("shows an admin every section and anyone else only Account and General", () => {
    mockFetch(base);
    const { unmount } = render(<SettingsPage user={mira} />);
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual(["Account", "General", "System", "Users", "Audit log", "Issues"]);
    unmount();
    render(<SettingsPage user={odell} />);
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual(["Account", "General"]);
  });

  it("opens on Account, with the person's email and role", () => {
    mockFetch(base);
    render(<SettingsPage user={odell} />);
    expect(screen.getByRole("heading", { name: "Odell Brambleworth" })).toBeInTheDocument();
    expect(screen.getByText("odell@samplefirm.example")).toBeInTheDocument();
    expect(screen.getByText("User")).toBeInTheDocument();
  });
});

describe("Account", () => {
  const fill = (current: string, next: string, again: string) => {
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
    fireEvent.change(screen.getByLabelText("New password again"), { target: { value: again } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  };

  it("changes the person's own password and says so", async () => {
    const fetch = show(odell, "Account", { "POST /api/auth/change-password": { status: 204 } });
    fill("old-password-1", "maple-orbit-4821", "maple-orbit-4821");
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(sent(fetch, "POST")).toEqual([{ url: "/api/auth/change-password", body: { current_password: "old-password-1", new_password: "maple-orbit-4821" } }]);
    expect((screen.getByLabelText("New password") as HTMLInputElement).value).toBe("");
  });

  it("does not ask the server when the two new passwords differ", () => {
    const fetch = show(odell, "Account");
    fill("old-password-1", "maple-orbit-4821", "maple-orbit-4822");
    expect(screen.getByRole("alert")).toHaveTextContent("The two new passwords do not match.");
    expect(sent(fetch, "POST")).toEqual([]);
  });

  it("shows the server's sentence when the current password is wrong", async () => {
    show(odell, "Account", { "POST /api/auth/change-password": { status: 403, body: { detail: "The current password is wrong." } } });
    fill("not-it", "maple-orbit-4821", "maple-orbit-4821");
    expect(await screen.findByRole("alert")).toHaveTextContent("The current password is wrong.");
    expect(screen.queryByText("Password changed")).toBeNull();
  });
});

describe("Users", () => {
  const list = { "GET /api/admin/users": { body: { users: [account(mira), account(odell), jonty] } } };

  it("lists everyone with role, status and last sign-in", async () => {
    show(mira, "Users", list);
    const row = (await screen.findByText("Jonty Applecross")).closest("tr")!;
    expect(row).toHaveTextContent("jonty@samplefirm.example");
    expect(row).toHaveTextContent("User");
    expect(row).toHaveTextContent("Disabled");
    expect(row).toHaveTextContent("Never");
    expect(screen.getByText("Mira Quillfeather").closest("tr")).toHaveTextContent("Admin");
    expect(screen.getByText("Mira Quillfeather").closest("tr")).toHaveTextContent("Active");
  });

  it("adds a user and shows the temporary password once", async () => {
    const wren = account({ email: "wren@samplefirm.example", name: "Wren Dapplemoor", is_admin: true, must_change_password: true }, { last_sign_in_at: null });
    const fetch = show(mira, "Users", { ...list, "POST /api/admin/users": { body: { user: wren, temporary_password: "maple-orbit-4821-kite" } } });
    fireEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a name and an email.");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Wren Dapplemoor" } });
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "wren@samplefirm.example" } });
    expect(within(dialog).getByRole("radio", { name: "User" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Admin" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add user" }));

    expect(await screen.findByRole("heading", { name: "Temporary password for Wren" })).toBeInTheDocument();
    expect(screen.getByText("maple-orbit-4821-kite")).toBeInTheDocument();
    expect(sent(fetch, "POST")).toEqual([{ url: "/api/admin/users", body: { email: "wren@samplefirm.example", name: "Wren Dapplemoor", is_admin: true } }]);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText("maple-orbit-4821-kite")).toBeNull();
    expect(screen.getByText("Wren Dapplemoor").closest("tr")).toHaveTextContent("Admin");
  });

  it("shows the server's sentence when the email is already used", async () => {
    show(mira, "Users", { ...list, "POST /api/admin/users": { status: 409, body: { detail: "An account with this email already exists." } } });
    fireEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Odell" } });
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "odell@samplefirm.example" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("An account with this email already exists.");
  });

  it("makes a user an admin, and saves only when the role changed", async () => {
    const fetch = show(mira, "Users", { ...list, "POST /api/admin/users/odell%40samplefirm.example/admin": { body: { user: account({ ...odell, is_admin: true }) } } });
    fireEvent.click(await screen.findByText("Odell Brambleworth"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Save role" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Admin" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent(fetch, "POST")).toEqual([{ url: "/api/admin/users/odell%40samplefirm.example/admin", body: { is_admin: true } }]);
    expect(screen.getByText("Odell Brambleworth").closest("tr")).toHaveTextContent("Admin");
  });

  it("shows the refusal when the last admin would be removed", async () => {
    const refusal = "Mira Quillfeather is the only admin. Make someone else an admin first.";
    show(mira, "Users", {
      ...list,
      "POST /api/admin/users/mira%40samplefirm.example/admin": { status: 409, body: { detail: refusal } },
      "POST /api/admin/users/mira%40samplefirm.example/disable": { status: 409, body: { detail: refusal } },
    });
    fireEvent.click(await screen.findByText("Mira Quillfeather"));
    const dialog = screen.getByRole("dialog");
    // An admin's own password is changed on Account, so there is no reset here.
    expect(within(dialog).queryByRole("button", { name: "Reset password" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("radio", { name: "User" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save role" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(refusal);
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent(refusal));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("disables one user and enables another", async () => {
    const fetch = show(mira, "Users", {
      ...list,
      "POST /api/admin/users/odell%40samplefirm.example/disable": { body: { user: account(odell, { disabled: true }) } },
      "POST /api/admin/users/jonty%40samplefirm.example/enable": { body: { user: { ...jonty, disabled: false } } },
    });
    fireEvent.click(await screen.findByText("Odell Brambleworth"));
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(screen.getByText("Odell Brambleworth").closest("tr")).toHaveTextContent("Disabled"));
    fireEvent.click(screen.getByText("Jonty Applecross"));
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));
    await waitFor(() => expect(screen.getByText("Jonty Applecross").closest("tr")).toHaveTextContent("Active"));
    expect(sent(fetch, "POST").map((c) => c.url)).toEqual(["/api/admin/users/odell%40samplefirm.example/disable", "/api/admin/users/jonty%40samplefirm.example/enable"]);
  });

  it("resets a password only after a confirmation, then shows the new temporary one", async () => {
    const fetch = show(mira, "Users", {
      ...list,
      "POST /api/admin/users/odell%40samplefirm.example/reset-password": { body: { user: account(odell, { must_change_password: true } as Partial<AdminUser>), temporary_password: "kite-4821-orbit" } },
    });
    fireEvent.click(await screen.findByText("Odell Brambleworth"));
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    expect(screen.getByRole("heading", { name: "Reset Odell's password?" })).toBeInTheDocument();
    expect(sent(fetch, "POST")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    expect(await screen.findByRole("heading", { name: "Temporary password for Odell" })).toBeInTheDocument();
    expect(screen.getByText("kite-4821-orbit")).toBeInTheDocument();
  });

  it("says when the users cannot be loaded and tries again", async () => {
    let fail = true;
    show(mira, "Users", { "GET /api/admin/users": () => (fail ? { status: 500, body: { detail: "The users could not be loaded." } } : { body: { users: [account(mira)] } }) });
    expect(screen.getByText("Loading users")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The users could not be loaded.");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Mira Quillfeather")).toBeInTheDocument();
  });
});

describe("Audit log", () => {
  const entry = (id: number, over: Partial<AuditEntry>): AuditEntry => ({
    id, at: "2026-11-25T09:40:00.000000Z", actor_email: mira.email, actor_name: mira.name, action: "user_added", target: "wren@samplefirm.example", target_name: "Wren Dapplemoor", detail: { is_admin: false }, ...over,
  });
  const people = [{ email: mira.email, name: mira.name }, { email: odell.email, name: odell.name }];
  const events = [
    entry(9, { action: "setting_changed", target: "login.max_attempts", target_name: "", detail: { setting: "Attempts before lockout", from: "5", to: "10" } }),
    entry(8, { action: "drafts_cleared", target: "2 runs", target_name: "", detail: null }),
    entry(7, { action: "issue_closed", target: "11", target_name: "", detail: null }),
    entry(6, { action: "role_changed", target: odell.email, target_name: odell.name, detail: { is_admin: true } }),
    entry(5, { action: "password_changed", target: mira.email, target_name: mira.name, detail: null }),
    entry(4, { action: "run_archived", target: "12", target_name: "", detail: null }),
    entry(3, {}),
  ];

  it("lists what was done in plain words, newest first as the server sends it", async () => {
    show(mira, "Audit log", { "GET /api/admin/audit": { body: { events, total: 7, has_more: false, people } } });
    await screen.findByText("Changed setting");
    const rows = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell").slice(1).map((c) => c.textContent));
    expect(rows).toEqual([
      ["Mira Quillfeather", "Changed setting", "Attempts before lockout: 5 to 10"],
      ["Mira Quillfeather", "Cleared abandoned drafts", "2 runs"],
      ["Mira Quillfeather", "Closed issue", "Issue 11"],
      ["Mira Quillfeather", "Changed role", "Odell Brambleworth: user to admin"],
      ["Mira Quillfeather", "Changed own password", ""],
      ["Mira Quillfeather", "Run archived", "12"],
      ["Mira Quillfeather", "Added user", "Wren Dapplemoor, user"],
    ]);
    expect(screen.getByText("1–7 of 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("filters by person and by action, and pages twenty at a time", async () => {
    const page = (from: number, total: number) => ({ body: { events: [entry(100 - from, {})], total, has_more: from + 20 < total, people } });
    const fetch = show(mira, "Audit log", {
      "GET /api/admin/audit?offset=0&limit=20": page(0, 64),
      "GET /api/admin/audit?offset=20&limit=20": page(20, 64),
      "GET /api/admin/audit?offset=0&limit=20&actor=odell%40samplefirm.example": page(0, 5),
      "GET /api/admin/audit?offset=0&limit=20&actor=odell%40samplefirm.example&group=issues": { body: { events: [], total: 0, has_more: false, people } },
    });
    expect(await screen.findByText("1–1 of 64")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("21–21 of 64")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    expect(Array.from((screen.getByLabelText("Person") as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(["Everyone", "Mira Quillfeather", "Odell Brambleworth"]);
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: odell.email } });
    expect(await screen.findByText("1–1 of 5")).toBeInTheDocument(); // back on the first page
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "issues" } });
    expect(await screen.findByText("No entries match")).toBeInTheDocument();
    expect(screen.getByLabelText("Action")).toBeInTheDocument(); // the filters stay, to be changed back
    expect(fetch.mock.calls.map(([url]) => String(url)).filter((u) => u.includes("/audit"))).toEqual([
      "/api/admin/audit?offset=0&limit=20",
      "/api/admin/audit?offset=20&limit=20",
      "/api/admin/audit?offset=0&limit=20&actor=odell%40samplefirm.example",
      "/api/admin/audit?offset=0&limit=20&actor=odell%40samplefirm.example&group=issues",
    ]);
  });

  it("says when nothing is recorded yet, with no filters to use", async () => {
    show(mira, "Audit log", { "GET /api/admin/audit": { body: { events: [], total: 0, has_more: false, people: [] } } });
    expect(await screen.findByText("Nothing recorded yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Person")).toBeNull();
  });
});

describe("Issues", () => {
  const issue = (over: Partial<Issue>): Issue => ({
    id: 14, created_at: "2026-11-24T16:05:00.000000Z", updated_at: "2026-11-24T16:05:00.000000Z", reporter_email: odell.email, reporter_name: odell.name,
    text: "The balance sheet total does not match the report.", run_id: 3, run_label: "Demo Durian Trading Sdn Bhd, FY2025", status: "open", note: "", file_name: "balance-sheet-total.png", ...over,
  });
  const closed = issue({ id: 11, status: "closed", text: "I could not download the filled workbook.", run_id: null, run_label: "", file_name: null, note: "Resolved with the user." });
  const list = { "GET /api/issues": { body: { issues: [issue({}), closed] } } };

  it("shows the open issues first and the others on request", async () => {
    show(mira, "Issues", list);
    const row = (await screen.findByText("The balance sheet total does not match the report.")).closest("tr")!;
    expect(row).toHaveTextContent("Odell Brambleworth");
    expect(row).toHaveTextContent("Demo Durian Trading Sdn Bhd");
    expect(row).not.toHaveTextContent("FY2025");
    expect(row).toHaveTextContent("Open");
    expect(screen.queryByText("I could not download the filled workbook.")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Closed" }));
    expect(screen.getByText("I could not download the filled workbook.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("says when there are no issues, or none of the kind asked for", async () => {
    show(mira, "Issues", { "GET /api/issues": { body: { issues: [closed] } } });
    expect(await screen.findByText("No open issues")).toBeInTheDocument();
  });

  it("says when no issue has been reported", async () => {
    show(mira, "Issues", { "GET /api/issues": { body: { issues: [] } } });
    expect(await screen.findByText("No issues reported")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Open" })).toBeNull();
  });

  it("downloads the run's traces from the issue, then closes it with a note", async () => {
    const fetch = show(mira, "Issues", {
      ...list,
      "GET /api/issues/14/traces": { body: {} },
      "PATCH /api/issues/14": { body: { issue: issue({ status: "closed", note: "Fixed with a guidance line." }) } },
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(await screen.findByText("The balance sheet total does not match the report."));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Issue 14" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Demo Durian Trading Sdn Bhd, FY2025");
    expect(dialog).toHaveTextContent("balance-sheet-total.png");

    fireEvent.click(within(dialog).getByRole("button", { name: "Download this run's traces" }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(fetch.mock.calls.map(([url]) => String(url))).toContain("/api/issues/14/traces");

    fireEvent.change(within(dialog).getByLabelText("Note"), { target: { value: "Fixed with a guidance line." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Close issue" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent(fetch, "PATCH")).toEqual([{ url: "/api/issues/14", body: { note: "Fixed with a guidance line.", status: "closed" } }]);
    expect(screen.queryByText("The balance sheet total does not match the report.")).toBeNull(); // no longer among the open ones
    click.mockRestore();
  });

  it("offers no traces for an issue with no run, and reopens a closed one", async () => {
    const fetch = show(mira, "Issues", { ...list, "PATCH /api/issues/11": { body: { issue: { ...closed, status: "open" } } } });
    fireEvent.click(await screen.findByRole("radio", { name: "Closed" }));
    fireEvent.click(screen.getByText("I could not download the filled workbook."));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Download this run's traces" })).toBeNull();
    expect((within(dialog).getByLabelText("Note") as HTMLTextAreaElement).value).toBe("Resolved with the user.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent(fetch, "PATCH")[0].body).toEqual({ note: "Resolved with the user.", status: "open" });
  });

  it("deletes an issue only after a confirmation", async () => {
    const fetch = show(mira, "Issues", { ...list, "DELETE /api/issues/14": { status: 204 } });
    fireEvent.click(await screen.findByText("The balance sheet total does not match the report."));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("heading", { name: "Delete issue 14?" })).toBeInTheDocument();
    expect(screen.getByText("The report and its screenshot are removed. The run is kept.")).toBeInTheDocument();
    expect(sent(fetch, "DELETE")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Delete issue" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent(fetch, "DELETE").map((c) => c.url)).toEqual(["/api/issues/14"]);
    expect(screen.getByText("No open issues")).toBeInTheDocument();
  });
});

describe("System: the connection test", () => {
  it("tests the connection and shows one sentence per model, a failure in the filled label", async () => {
    let answer: (value: Response) => void = () => {};
    const fetch = show(mira, "System", { "GET /api/settings": { body: { ...settings(), models: { reading: "gpt-6-luna", extraction: "gpt-6-luna", review: "claude-opus-5-5" } } } });
    const real = fetch.getMockImplementation()!;
    const pending = new Promise<Response>((resolve) => (answer = resolve));
    fetch.mockImplementation((input, init) => (String(input) === "/api/admin/connection-test" ? pending : real(input, init)));

    const panel = (await screen.findByRole("heading", { name: "Connection" })).closest("section")!;
    expect(within(panel).queryByText("gpt-6-luna")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Test connection" }));
    expect(within(panel).getByRole("button", { name: "Test connection" })).toBeDisabled();
    expect(within(panel).getAllByText(/gpt-6-luna|claude-opus-5-5/)).toHaveLength(2); // each model once, while it waits

    const results = [
      { model: "gpt-6-luna", ok: true, seconds: 1.2, sentence: "Answered in 1.2 seconds" },
      { model: "claude-opus-5-5", ok: false, seconds: 0.4, sentence: "The model service says this key may not use this model." },
    ];
    answer(new Response(JSON.stringify({ results }), { status: 200, headers: { "Content-Type": "application/json" } }));
    expect(await within(panel).findByText("Answered in 1.2 seconds")).toBeInTheDocument();
    const failed = within(panel).getByText("The model service says this key may not use this model.").closest(".line")!;
    expect(failed).toHaveTextContent("claude-opus-5-5");
    expect(within(failed as HTMLElement).getByText("Failed")).toHaveAttribute("data-kind", "failure");
    expect(within(panel).getByRole("button", { name: "Test connection" })).toBeEnabled();
    expect(fetch.mock.calls.some(([url, init]) => String(url) === "/api/admin/connection-test" && init?.method === "POST")).toBe(true);
  });

  it("says when the test itself could not run", async () => {
    show(mira, "System", { "POST /api/admin/connection-test": { status: 500, body: { detail: "The test could not be run." } } });
    fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The test could not be run.");
  });
});
