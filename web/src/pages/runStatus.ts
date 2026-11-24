import type { RunStatus } from "../api";
import type { StatusKind } from "../components/Status";

/** How each run status reads in the list. */
export const RUN_STATUS: Record<RunStatus, { label: string; kind: StatusKind }> = {
  reading: { label: "Reading", kind: "working" },
  setup: { label: "Setup", kind: "attention" },
  ready: { label: "Ready", kind: "neutral" },
  extracting: { label: "Extracting", kind: "working" },
  needs_answer: { label: "Needs you", kind: "attention" },
  in_review: { label: "In review", kind: "attention" },
  correcting: { label: "Correcting", kind: "working" },
  filed: { label: "Filed", kind: "finished" },
  failed: { label: "Failed", kind: "failure" },
  stopped: { label: "Stopped", kind: "neutral" },
};

const pad = (n: number) => String(n).padStart(2, "0");

/** "Today, 09:14", "Yesterday", "12 Nov", or "12 Nov 2024" for another year. */
export function formatUpdated(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(when)) / 86_400_000);
  if (days === 0) return `Today, ${pad(when.getHours())}:${pad(when.getMinutes())}`;
  if (days === 1) return "Yesterday";
  const month = when.toLocaleString("en-GB", { month: "short" });
  const base = `${when.getDate()} ${month}`;
  return when.getFullYear() === now.getFullYear() ? base : `${base} ${when.getFullYear()}`;
}
