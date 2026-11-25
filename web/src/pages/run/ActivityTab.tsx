import { useEffect, useState, type ReactNode } from "react";
import type { RunEvent, ScopeQuestion } from "../../api";
import { Spinner } from "../../components/Spinner";
import { clock } from "./runModel";

/** Rows of the shared agent loop that only count steps or name a tool: not sentences for a person. */
const HIDDEN = new Set(["step", "tool"]);
/** More lines than this fold into one when the run is not busy. */
const FOLD_AFTER = 3;
/** A step with more pages than this shows the first few and a "+N" that opens the rest. */
const PAGES_SHOWN = 3;
/** Rows that say an agent has ended, from the shared agent loop and the notes stage. */
const ENDS = new Set(["finished", "completed", "step_limit", "time_limit", "stopped", "failed"]);

export const activityLines = (events: RunEvent[]) => events.filter((e) => !HIDDEN.has(e.kind));

function Pages({ pages = [], onPage }: { pages?: number[]; onPage: (page: number) => void }) {
  const [all, setAll] = useState(false);
  if (!pages.length) return null;
  const shown = all || pages.length <= PAGES_SHOWN + 1 ? pages : pages.slice(0, PAGES_SHOWN);
  return (
    <span className="pgs">
      {shown.map((p) => (
        <button key={p} type="button" className="pgc" onClick={() => onPage(p)}>
          Page {p}
        </button>
      ))}
      {shown.length < pages.length && (
        <button type="button" className="pgc" aria-label={`${pages.length - shown.length} more pages`} onClick={() => setAll(true)}>
          +{pages.length - shown.length}
        </button>
      )}
    </span>
  );
}

/** What the person answered: their own words, else the choice's label. */
const answerText = (q: ScopeQuestion) => q.answer?.text ?? (q.answer?.choice != null ? q.choices[q.answer.choice]?.label : q.answer?.value) ?? "";

/** How an agent ended, in a few words: "Done, with 2 point(s) left open", "Partly done", "Stopped to ask". */
function ending(lines: RunEvent[]): string {
  const finished = lines.find((e) => e.kind === "finished");
  if (finished) {
    const words = finished.message.replace(/^[^:]*:\s*/, "").replace(/\.$/, "");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  if (lines.some((e) => e.kind === "step_limit" || e.kind === "time_limit")) return "Partly done";
  if (lines.some((e) => e.kind === "failed")) return "Failed";
  if (lines.some((e) => e.kind === "asked")) return "Stopped to ask";
  return "Stopped";
}

interface Group {
  key: string;
  agent: string;
  lines: RunEvent[];
}

/** The agents in the order they started, each with its own lines. A stage that starts again after a question
 * reuses the agents' names, so each "session" row opens a new block rather than adding to the stopped one. */
function groups(lines: RunEvent[]): Group[] {
  const all: Group[] = [];
  const current = new Map<string, Group>();
  for (const e of lines) {
    if (!e.agent) continue;
    let group = current.get(e.agent);
    if (!group || e.kind === "session") {
      group = { key: `${e.agent}-${e.id}`, agent: e.agent, lines: [] };
      current.set(e.agent, group);
      all.push(group);
    }
    group.lines.push(e);
  }
  return all;
}

export interface ActivityTabProps {
  events: RunEvent[];
  busy: boolean;
  /** Extraction waits for a person's answer: the last step is marked, not spinning. */
  waiting?: boolean;
  questions?: ScopeQuestion[];
  onPage: (page: number) => void;
}

/** Each step as a plain sentence. The current step spins while an agent works. When several agents work side
 * by side, each gets a block of its own: its name, its time, and only what it is doing now; its earlier steps
 * open from its name. An answered scope question shows as two lines: the question, then the answer. */
export function ActivityTab({ events, busy, waiting = false, questions = [], onPage }: ActivityTabProps) {
  const [folded, setFolded] = useState(true);
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const [, setNow] = useState(0);
  const lines = activityLines(events);

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!busy) setFolded(true);
  }, [busy]);

  if (lines.length === 0) return <div className="empty">No activity</div>;

  const last = lines[lines.length - 1];
  const agents = groups(lines);
  const several = agents.length > 1;

  const row = (e: RunEvent, current: boolean, since?: string) => {
    const qa = e.kind === "answered" && e.question_id ? questions.find((q) => q.id === e.question_id && q.answer) : undefined;
    if (qa) {
      return (
        <div key={e.id} className="qa">
          <span>{qa.question}</span>
          <span>{answerText(qa)}</span>
        </div>
      );
    }
    const marked = waiting && e === last;
    return (
      <div key={e.id} className={current ? "fl act" : "fl"}>
        <span className="mk">{current ? <Spinner /> : <i className={marked ? "dot on" : "dot"} aria-hidden="true" />}</span>
        <span className="tx">{e.message}</span>
        <span className="mono ct">{current && since ? clock(since, Date.now()) : ""}</span>
        <Pages pages={e.pages} onPage={onPage} />
      </div>
    );
  };

  const fold = (rows: RunEvent[], children: ReactNode) => (
    <>
      <button type="button" className={folded ? "fold" : "fold open"} aria-expanded={!folded} onClick={() => setFolded(!folded)}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" />
        </svg>
        <span>{`Worked through ${rows.length} steps`}</span>
        <span className="mono ct">{clock(rows[0].created_at, rows[rows.length - 1].created_at)}</span>
      </button>
      {!folded && children}
    </>
  );

  if (!several) {
    const jobStart = events.find((e) => e.job_id !== null && e.job_id === last.job_id)?.created_at ?? last.created_at;
    const rows = lines.map((e) => row(e, busy && !waiting && e === last, jobStart));
    if (busy || lines.length <= FOLD_AFTER) return <div className="feed">{rows}</div>;
    return <div className="feed">{fold(lines, rows)}</div>;
  }

  // Several agents: the stage's own lines before the first agent stay on top, the rest go below the blocks.
  const firstAgent = lines.findIndex((e) => e.agent);
  const before = lines.slice(0, firstAgent);
  const after = lines.slice(firstAgent).filter((e) => !e.agent);
  const head = before.map((e) => row(e, false));

  return (
    <div className="feed">
      {!busy && before.length > FOLD_AFTER ? fold(before, head) : head}
      <div className="agents">
        {agents.map(({ key, agent, lines: own }) => {
          const ended = own.some((e) => ENDS.has(e.kind));
          const live = busy && !ended;
          const open = opened[key] ?? false;
          const latest = own[own.length - 1];
          const shown = open ? own : live ? [latest] : [];
          const toggle = () => setOpened({ ...opened, [key]: !open });
          return (
            <div key={key} className={open ? "agent open" : "agent"}>
              <button type="button" className="ah" aria-expanded={open} onClick={toggle}>
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M6 3.5 10.5 8 6 12.5" />
                </svg>
                <span className="ah-name">
                  <span className="nm">{agent}</span>
                  {!live && <span className="st">{` · ${ending(own)}`}</span>}
                </span>
                <span className="mono ct">{clock(own[0].created_at, live ? Date.now() : latest.created_at)}</span>
              </button>
              {shown.map((e) => row(e, live && !waiting && e === latest))}
              {!open && live && own.length > 1 && (
                <button type="button" className="more" onClick={toggle}>
                  {`${own.length - 1} earlier ${own.length === 2 ? "step" : "steps"}`}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {after.map((e) => row(e, false))}
    </div>
  );
}
