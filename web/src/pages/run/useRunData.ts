import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type AcceptAll,
  errorMessage,
  type Check,
  type Comment,
  type NeedsYou,
  type Round,
  type RoundReport,
  type RunDetail,
  type RunEvent,
  type ScopeQuestion,
  type Statement,
  type StatementCode,
} from "../../api";
import { isBusy } from "./runModel";

/** How often the run screen asks for news while an agent works (backend-plan.md section 2). */
export const POLL_MS = 1000;
/** While extraction waits for a person's answer, nothing moves until someone answers: ask rarely. */
export const WAITING_POLL_MS = 15000;
/** The most events one read asks for. */
const EVENT_PAGE = 500;
/** Every so many polls the run itself is read again, in case an end event was missed. */
const RUN_EVERY = 3;
/** Events after which the figures on screen are read again. */
const FIGURE_KINDS = new Set(["saved", "cleared", "moved", "answered", "checked", "coverage"]);
/** Events that end a stage or a round: the run's status changes. */
const END_KINDS = new Set(["done", "failed", "stopped", "finished", "asked", "answered", "statement"]);

export interface RunData {
  run: RunDetail | null;
  /** The run's statements that are switched on, in filing order. */
  statements: StatementCode[];
  statement: Statement | null;
  checks: Check[];
  needs: NeedsYou | null;
  comments: Comment[];
  rounds: Round[];
  /** The comments Accept all would accept now, as the server counts them. */
  acceptAll: AcceptAll;
  report: RoundReport | null;
  events: RunEvent[];
  /** The open scope question, if extraction waits for an answer. */
  question: ScopeQuestion | null;
  /** Every scope question of the run, oldest first. */
  questions: ScopeQuestion[];
  error: string;
  /** Reads everything again, after a person's change. */
  refresh: () => Promise<void>;
  /** Reads the run again, after a person starts or stops a stage. */
  reloadRun: () => Promise<void>;
}

export function useRunData(runId: number, code: StatementCode | null, order: "report" | "template"): RunData {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [statement, setStatement] = useState<Statement | null>(null);
  const [checks, setChecks] = useState<Check[]>([]);
  const [needs, setNeeds] = useState<NeedsYou | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [acceptAll, setAcceptAll] = useState<AcceptAll>({ round_id: null, comment_ids: [] });
  const [report, setReport] = useState<RoundReport | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [question, setQuestion] = useState<ScopeQuestion | null>(null);
  const [questions, setQuestions] = useState<ScopeQuestion[]>([]);
  const [error, setError] = useState("");
  const lastEvent = useRef(0);
  const view = useRef({ code, order });
  view.current = { code, order };

  const loadStatement = useCallback(async () => {
    const { code: c, order: o } = view.current;
    if (!c) return;
    const loaded = await api.statement(runId, c, o);
    if (view.current.code === c && view.current.order === o) setStatement(loaded);
  }, [runId]);

  const loadRounds = useCallback(async () => {
    const { rounds: list, accept_all } = await api.rounds(runId);
    setRounds(list);
    setAcceptAll(accept_all ?? { round_id: null, comment_ids: [] });
    const last = list[list.length - 1];
    setReport(last ? (await api.round(runId, last.id)).report : null);
  }, [runId]);

  const loadEvents = useCallback(async () => {
    const fresh: RunEvent[] = [];
    // Read until the server says nothing more is waiting, showing each page as it comes.
    for (;;) {
      const next = await api.events(runId, lastEvent.current, EVENT_PAGE, true);
      lastEvent.current = Math.max(lastEvent.current, next.last_id);
      fresh.push(...next.events);
      // Two reads may overlap (a poll and a refresh): keep each event once.
      if (next.events.length) setEvents((old) => [...old, ...next.events.filter((e) => !old.some((o) => o.id === e.id))]);
      if (!next.has_more || next.events.length === 0) break;
    }
    return fresh;
  }, [runId]);

  const loadQuestions = useCallback(async () => {
    const [open, all] = await Promise.all([api.question(runId), api.questions(runId)]);
    setQuestion(open);
    setQuestions(all);
  }, [runId]);

  const loadReview = useCallback(async () => {
    const [c, k, n] = await Promise.all([api.comments(runId), api.checks(runId), api.needsYou(runId), loadQuestions()]);
    setComments(c);
    setChecks(k);
    setNeeds(n);
  }, [runId, loadQuestions]);

  const refresh = useCallback(async () => {
    try {
      setRun(await api.run(runId));
      await Promise.all([loadStatement(), loadReview(), loadRounds(), loadEvents()]);
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [runId, loadStatement, loadReview, loadRounds, loadEvents]);

  // First load: the run, its statements, then everything on screen.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const found = await api.run(runId);
        if (!live) return;
        setRun(found);
        await Promise.all([loadReview(), loadRounds(), loadEvents()]);
      } catch (failure) {
        if (live) setError(errorMessage(failure));
      }
    })();
    return () => {
      live = false;
    };
  }, [runId, loadReview, loadRounds, loadEvents]);

  useEffect(() => {
    setStatement((old) => (old && old.statement === code && old.order === order ? old : null));
    loadStatement().catch((failure) => setError(errorMessage(failure)));
  }, [code, order, loadStatement]);

  // While an agent works, ask for news about once a second; while it waits for an answer, rarely.
  // A hidden tab asks for nothing until it is shown again.
  const busy = run !== null && isBusy(run);
  const waiting = run?.status === "needs_answer";
  useEffect(() => {
    if (!busy) return;
    let live = true;
    let tick = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const every = waiting ? WAITING_POLL_MS : POLL_MS;
    async function poll() {
      if (document.hidden) {
        timer = setTimeout(poll, every);
        return;
      }
      tick += 1;
      try {
        const fresh = await loadEvents();
        if (!live) return;
        if (fresh.some((e) => FIGURE_KINDS.has(e.kind))) await loadStatement();
        if (waiting || fresh.some((e) => END_KINDS.has(e.kind)) || tick % RUN_EVERY === 0) {
          const now = await api.run(runId);
          if (!live) return;
          setRun(now);
          await loadQuestions();
          if (!isBusy(now)) {
            // The closing lines of the stage arrive with the last read.
            await Promise.all([loadStatement(), loadReview(), loadRounds(), loadEvents()]);
            return;
          }
        }
      } catch (failure) {
        if (live) setError(errorMessage(failure));
      }
      if (live) timer = setTimeout(poll, every);
    }
    timer = setTimeout(poll, every);
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [busy, waiting, runId, loadEvents, loadStatement, loadReview, loadRounds, loadQuestions]);

  const statements = useMemo(() => (run?.statements ?? []).map((s) => s.statement), [run?.statements]);
  const reloadRun = useCallback(async () => setRun(await api.run(runId)), [runId]);

  return { run, statements, statement, checks, needs, comments, rounds, acceptAll, report, events, question, questions, error, refresh, reloadRun };
}
