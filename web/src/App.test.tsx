import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { admin, mockFetch, settings } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("session", () => {
  it("shows Login when the server does not know the user", async () => {
    mockFetch({ "GET /api/auth/me": { status: 401, body: { detail: "Log in first." } } });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows the server's sentence when login fails", async () => {
    mockFetch({
      "GET /api/auth/me": { status: 401, body: { detail: "Log in first." } },
      "POST /api/auth/login/password": { status: 401, body: { detail: "The email or password is wrong." } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "aina@firm.my" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The email or password is wrong.");
    expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("enters the app after a successful login", async () => {
    const fetch = mockFetch({
      "GET /api/auth/me": { status: 401, body: { detail: "Log in first." } },
      "POST /api/auth/login/password": { body: { user: admin } },
      "GET /api/runs": { body: { runs: [] } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "aina@firm.my" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: "Runs" })).toBeInTheDocument();
    expect(screen.getByText("Aina R.")).toBeInTheDocument();
    const login = fetch.mock.calls.find(([url]) => url === "/api/auth/login/password");
    expect(JSON.parse(String(login?.[1]?.body))).toEqual({ email: "aina@firm.my", password: "secret" });
  });

  it("returns to Login when any call answers 401", async () => {
    mockFetch({
      "GET /api/auth/me": { body: { user: admin } },
      "GET /api/runs": { body: { runs: [] } },
      "GET /api/settings": { status: 401, body: { detail: "Your session has ended." } },
      "GET /api/models": { body: { models: [] } },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Runs" })).toBeInTheDocument();
    await act(async () => {
      window.location.hash = "#/settings";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("asks for a new password before anything else", async () => {
    let changed = false;
    mockFetch({
      "GET /api/auth/me": () => ({ body: { user: { ...admin, must_change_password: !changed } } }),
      "POST /api/auth/change-password": () => {
        changed = true;
        return { status: 204 };
      },
      "GET /api/runs": { body: { runs: [] } },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Change password" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "temp" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "longer-one" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "longer-one" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("heading", { name: "Runs" })).toBeInTheDocument();
  });

  it("logs out from the sidebar", async () => {
    const fetch = mockFetch({
      "GET /api/auth/me": { body: { user: admin } },
      "GET /api/runs": { body: { runs: [] } },
      "POST /api/auth/logout": { status: 204 },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url, init]) => url === "/api/auth/logout" && init?.method === "POST")).toBe(true);
  });

  it("opens Settings from the sidebar", async () => {
    mockFetch({
      "GET /api/auth/me": { body: { user: admin } },
      "GET /api/runs": { body: { runs: [] } },
      "GET /api/settings": { body: settings() },
      "GET /api/models": { body: { models: [] } },
    });
    render(<App />);
    const link = await screen.findByRole("link", { name: "Settings" });
    await act(async () => {
      window.location.hash = link.getAttribute("href") ?? "";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });
});
