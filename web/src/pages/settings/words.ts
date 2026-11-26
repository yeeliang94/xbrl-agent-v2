// Small wording helpers the Settings sections share.
import type { AuditEntry } from "../../api";

const pad = (n: number) => String(n).padStart(2, "0");

/** "25 Nov 2026, 09:40" in the reader's own time. */
export function stamp(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const month = when.toLocaleString("en-GB", { month: "short" });
  return `${when.getDate()} ${month} ${when.getFullYear()}, ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

export const firstName = (person: { name: string; email: string }) => person.name.trim().split(/\s+/)[0] || person.email;

export type Role = "admin" | "user";

export const ROLES: { id: Role; name: string; may: string }[] = [
  { id: "admin", name: "Admin", may: "Everything a user may do, plus users, settings and the audit log." },
  { id: "user", name: "User", may: "Uploads reports, runs the agents and corrects figures and notes." },
];

export const roleOf = (person: { is_admin: boolean }): Role => (person.is_admin ? "admin" : "user");
export const roleName = (role: Role) => (role === "admin" ? "Admin" : "User");

const ACTIONS: Record<string, string> = {
  user_added: "Added user",
  user_disabled: "Disabled user",
  user_enabled: "Enabled user",
  password_reset: "Reset password",
  password_changed: "Changed own password",
  role_changed: "Changed role",
  setting_changed: "Changed setting",
  run_deleted: "Deleted run",
  drafts_cleared: "Cleared abandoned drafts",
  issue_updated: "Updated issue",
  issue_closed: "Closed issue",
  issue_reopened: "Reopened issue",
  issue_deleted: "Deleted issue",
  issue_traces_downloaded: "Downloaded traces",
};

/** The action as a person reads it. One the screen does not know yet is shown in its own words. */
export function auditAction(entry: AuditEntry): string {
  const known = ACTIONS[entry.action];
  if (known) return known;
  const words = entry.action.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const auditPerson = (entry: AuditEntry) => entry.actor_name || entry.actor_email;

export function auditDetail(entry: AuditEntry): string {
  const detail = entry.detail ?? {};
  const who = entry.target_name || entry.target;
  const role = (admin: unknown) => (admin ? "admin" : "user");
  switch (entry.action) {
    case "user_added":
      return `${who}, ${role(detail.is_admin)}`;
    case "role_changed":
      return `${who}: ${role(!detail.is_admin)} to ${role(detail.is_admin)}`;
    case "password_changed":
      return "";
    case "setting_changed":
      return `${String(detail.setting ?? entry.target)}: ${String(detail.from)} to ${String(detail.to)}`;
    case "issue_updated":
      return `Issue ${entry.target}: note saved`;
    case "issue_traces_downloaded":
      return `Issue ${entry.target}, run ${String(detail.run_id ?? "")}`.trim();
    default:
      return entry.action.startsWith("issue_") ? `Issue ${entry.target}` : who;
  }
}
