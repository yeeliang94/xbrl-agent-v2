import { useEffect, useState } from "react";
import type { RunEvent, ScopeQuestion } from "../../api";
import { Spinner } from "../../components/Spinner";
import { clock } from "./runModel";

/** Rows of the shared agent loop that only count steps or name a tool: not sentences for a person. */
const HIDDEN = new Set(["step", "tool"]);
/** More lines than this fold into one when the run is not busy. */
const FOLD_AFTER = 3;

export const activityLines = (events: RunEvent[]) => events.filter((e) => !HIDDEN.has(e.kind));

function Pages({ pages = [], onPage }: { pages?: number[]; onPage: (page: number) => void }) {
  if (!pages.length) return <span />;
  return (
    <span className="pgs">
      {pages.map((p) => (
        <button key={p} type="button" className="pgc" onClick={() => onPage(p)}>
          Page {p}
        </button>
      ))}
    </span>
  );
}

/** What the person answered: their own words, else the choice's label. */
const answerText = (q: ScopeQuestion) => q.answer?.text ?? (q.answer?.choice != null ? q.choices[q.answer.choice]?.label : q.answer?.value) ?? "";

export interface ActivityTabProps {
  events: RunEvent[];
  busy: boolean;
  /** Extraction waits for a person's answer: the last step is marked, not spinning. */
  waiting?: boolean;
  questions?: ScopeQuestion[];
  onPage: (page: number) => void;
}

/** Each step as a plain sentence. The current step spins while an agent works.
 * An answered scope question shows as two lines: the question, then the answer. */
export function ActivityTab({ events, busy, waiting = false, questions = [], onPage }: ActivityTabProps) {
  const [open, setOpen] = useState(false);
  const [, setNow] = useState(0);
  const lines = activityLines(events);

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!busy) setOpen(false);
  }, [busy]);

  if (lines.length === 0) return <div className="empty">No activity</div>;

  const last = lines[lines.length - 1];
  const jobStart = events.find((e) => e.job_id !== null && e.job_id === last.job_id)?.created_at ?? last.created_at;
  const rows = lines.map((e) => {
    const qa = e.kind === "answered" && e.question_id ? questions.find((q) => q.id === e.question_id && q.answer) : undefined;
    if (qa) {
      return (
        <div key={e.id} className="qa">
          <span>{qa.question}</span>
          <span>{answerText(qa)}</span>
        </div>
      );
    }
    const current = busy && !waiting && e === last;
    const marked = waiting && e === last;
    return (
      <div key={e.id} className={current ? "fl act" : "fl"}>
        <span>{current ? <Spinner /> : <i className={marked ? "dot on" : "dot"} aria-hidden="true" />}</span>
        <span className="tx">{e.message}</span>
        <Pages pages={e.pages} onPage={onPage} />
        <span className="mono ct">{current ? clock(jobStart, Date.now()) : ""}</span>
      </div>
    );
  });

  if (busy || lines.length <= FOLD_AFTER) return <div className="feed">{rows}</div>;
  return (
    <div className="feed">
      <button type="button" className={open ? "fold open" : "fold"} aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" />
        </svg>
        <span>{`Worked through ${lines.length} steps`}</span>
        <span className="mono ct">{clock(lines[0].created_at, last.created_at)}</span>
      </button>
      {open && rows}
    </div>
  );
}
