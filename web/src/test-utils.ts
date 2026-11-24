import { vi } from "vitest";
import type { Model, Run, Settings, User } from "./api";

export interface Reply {
  status?: number;
  body?: unknown;
}

type Handler = Reply | ((init: RequestInit | undefined) => Reply);

/** Replaces fetch with a table of "METHOD /path" answers. Unknown routes give 404. */
export function mockFetch(routes: Record<string, Handler>) {
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    // An exact match first, then the same path without its query.
    const handler = routes[key] ?? routes[key.split("?")[0]];
    const reply: Reply = typeof handler === "function" ? handler(init) : handler ?? { status: 404, body: { detail: "Not found." } };
    const status = reply.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(reply.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

export const admin: User = { email: "aina@firm.my", name: "Aina R.", is_admin: true, must_change_password: false };
export const member: User = { ...admin, email: "wei@firm.my", name: "Wei Jian L.", is_admin: false };

export const run = (over: Partial<Run> = {}): Run => ({
  id: 1,
  company: "Seri Maju Trading Sdn. Bhd.",
  year: 2025,
  standard: "MFRS",
  level: "Company",
  status: "in_review",
  updated_at: new Date().toISOString(),
  owner_name: "Aina R.",
  owner_email: "aina@firm.my",
  filename: "Seri Maju 2025.pdf",
  ...over,
});

export const settings = (): Settings => ({
  route: "direct",
  models: { reading: "gpt-6-luna", extraction: "gpt-6-luna", review: "gpt-6-luna" },
  code_workbench: true,
  claude_sandbox_real_documents: false,
  house_style: {
    body_text: "justified",
    table_font_pt: 10,
    smallest_table_font_pt: 8,
    double_underline: "thick_bottom_border",
    bold_totals: false,
  },
  login: { idle_timeout_minutes: 60, max_attempts: 5, lockout_minutes: 15 },
});

export const models: Model[] = [
  { id: "gpt-6-luna", provider: "openai", family: "luna", label: "GPT-6 Luna", available: true },
  { id: "gpt-6.1-terra", provider: "openai", family: "terra", label: "GPT-6.1 Terra", available: true },
  { id: "claude-opus-5-5", provider: "anthropic", family: "claude", label: "Claude Opus 5.5", available: false },
];
