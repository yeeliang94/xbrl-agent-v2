// Users, the audit log, issues and housekeeping (docs/api-contract.md, "Go-live A1, A2 and A7").
import { downloadFile, postForm, request } from "./client";
import type { User } from "./types";

export interface AdminUser extends User {
  disabled: boolean;
  has_password: boolean;
  created_at: string;
  password_set_at: string | null;
  last_sign_in_at: string | null;
}

export type AuditGroup = "users" | "settings" | "runs" | "issues";

export interface AuditEntry {
  id: number;
  at: string;
  actor_email: string;
  actor_name: string;
  action: string;
  target: string;
  target_name: string;
  detail: Record<string, unknown> | null;
}

export interface AuditPage {
  events: AuditEntry[];
  /** How many rows match the filters, on every page. */
  total: number;
  has_more: boolean;
  /** Everyone with a row in the log, for the "Person" filter. */
  people: { email: string; name: string }[];
}

export interface AuditQuery {
  actor?: string;
  group?: AuditGroup | "";
  offset?: number;
  limit?: number;
}

export type IssueStatus = "open" | "closed";

export interface Issue {
  id: number;
  created_at: string;
  updated_at: string;
  reporter_email: string;
  reporter_name: string;
  text: string;
  /** Null when no run was on screen, or the run has since been deleted. */
  run_id: number | null;
  /** The run's name when the issue was reported; "" when there was no run. */
  run_label: string;
  status: IssueStatus;
  note: string;
  file_name: string | null;
}

export interface ConnectionResult {
  model: string;
  ok: boolean;
  seconds: number;
  sentence: string;
}

const userPath = (email: string) => `/api/admin/users/${encodeURIComponent(email)}`;

function auditPath({ actor, group, offset = 0, limit = 20 }: AuditQuery): string {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (actor) query.set("actor", actor);
  if (group) query.set("group", group);
  return `/api/admin/audit?${query}`;
}

export const adminApi = {
  version: () => request<{ version: string }>("GET", "/api/health").then((r) => r.version),
  users: () => request<{ users: AdminUser[] }>("GET", "/api/admin/users").then((r) => r.users),
  addUser: (email: string, name: string, is_admin: boolean) =>
    request<{ user: AdminUser; temporary_password: string }>("POST", "/api/admin/users", { email, name, is_admin }),
  disableUser: (email: string) => request<{ user: AdminUser }>("POST", `${userPath(email)}/disable`).then((r) => r.user),
  enableUser: (email: string) => request<{ user: AdminUser }>("POST", `${userPath(email)}/enable`).then((r) => r.user),
  resetPassword: (email: string) => request<{ user: AdminUser; temporary_password: string }>("POST", `${userPath(email)}/reset-password`),
  setAdmin: (email: string, is_admin: boolean) => request<{ user: AdminUser }>("POST", `${userPath(email)}/admin`, { is_admin }).then((r) => r.user),
  audit: (query: AuditQuery) => request<AuditPage>("GET", auditPath(query)),
  reportIssue: (text: string, runId: number | null, file: File | null) => {
    const form = new FormData();
    form.append("text", text);
    if (runId !== null) form.append("run_id", String(runId));
    if (file) form.append("file", file);
    return postForm<{ issue: Issue }>("/api/issues", form).then((r) => r.issue);
  },
  issues: () => request<{ issues: Issue[] }>("GET", "/api/issues?status=all").then((r) => r.issues),
  changeIssue: (id: number, change: { status?: IssueStatus; note?: string }) =>
    request<{ issue: Issue }>("PATCH", `/api/issues/${id}`, change).then((r) => r.issue),
  deleteIssue: (id: number) => request<void>("DELETE", `/api/issues/${id}`),
  downloadIssueFile: (issue: Issue) => downloadFile(`/api/issues/${issue.id}/file`, issue.file_name ?? `issue-${issue.id}`),
  downloadIssueTraces: (issue: Issue) => downloadFile(`/api/issues/${issue.id}/traces`, `run-${issue.run_id}-traces.zip`),
  testConnection: () => request<{ results: ConnectionResult[] }>("POST", "/api/admin/connection-test").then((r) => r.results),
};
