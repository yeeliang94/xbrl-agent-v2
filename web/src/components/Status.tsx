import { Spinner } from "./Spinner";
import "./Status.css";

export type StatusKind = "finished" | "attention" | "check" | "neutral" | "failure" | "working";

/**
 * A status is a dot and a word. Working shows the spinner instead of the dot.
 * Check is the quiet one for a long list (owner, 24 November 2026): a hollow ring and a grey word.
 * A failure is the one exception: a filled dark-orange label with no dot.
 */
export function Status({ kind, children }: { kind: StatusKind; children: string }) {
  return (
    <span className={`status ${kind}`} data-kind={kind}>
      {kind === "working" ? <Spinner small /> : kind === "failure" ? null : <i className="status-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
