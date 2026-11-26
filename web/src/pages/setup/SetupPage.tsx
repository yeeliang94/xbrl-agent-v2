import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type DocumentMap, type ReadProgress, type RunDocument, type RunEvent, type SuggestedSetup } from "../../api";
import { Button } from "../../components/Button";
import { Failure } from "../../components/Failure";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";
import { activityLines } from "../run/ActivityTab";
import { SetupForm } from "./SetupForm";
import { DocumentPanel, SetupHeader } from "./SetupParts";
import "./SetupPage.css";

/** How often the page asks for reading news (backend-plan.md section 2). */
export const POLL_MS = 1000;
/** After a failed ask, the page waits this long and asks again. */
export const RETRY_MS = 3000;
const FEED_LINES = 6;

type Loaded = { setup: SuggestedSetup; map: DocumentMap };

const pad = (n: number) => String(n).padStart(2, "0");

/** "01:12" from the start of reading. */
export function elapsed(from: string | null, to: string | number): string {
  if (!from) return "";
  const seconds = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
}

function ReadingPanel({ read, events }: { read: ReadProgress; events: RunEvent[] }) {
  const { total, waiting } = read.pages;
  const done = total - waiting;
  const stopped = read.status === "stopped";
  // Stop takes effect once the pages being read are finished: no page is cut off half read.
  const stopping = !stopped && Boolean(read.stop_requested);
  const page = Math.min(done + 1, total);
  const label = stopping
    ? waiting > 0 ? `Stopping after page ${page}` : "Stopping"
    : total === 0 ? "Waiting to read" : waiting > 0 ? `Reading page ${page} of ${total}` : "Mapping the document";
  const shown = activityLines(events).slice(-FEED_LINES);
  return (
    <Panel className="sec">
      <div className="line">
        <span>{stopped ? <Status kind="neutral">Reading stopped</Status> : <Status kind="working">{label}</Status>}</span>
        <span className="meta mono">{stopped ? `${done} of ${total} pages read` : elapsed(read.started_at, Date.now())}</span>
      </div>
      <div className="prog" role="progressbar" aria-label="Pages read" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
        <i style={{ width: total ? `${(100 * done) / total}%` : "0%" }} />
      </div>
      <div className="feed">
        {shown.map((event, index) => (
          <div key={event.id} className={index === shown.length - 1 && !stopped ? "fl act" : "fl"}>
            <span className="dot" aria-hidden="true" />
            <span>{event.message}</span>
            <span className="mono">{elapsed(read.started_at, event.created_at)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function FailedPanel({ read, onRetry, retrying }: { read: ReadProgress; onRetry: () => void; retrying: boolean }) {
  return (
    <Panel className="sec">
      <div className="line">
        <span>
          <Status kind="failure">Reading failed</Status>
        </span>
        <Button disabled={retrying} onClick={onRetry}>
          Try again
        </Button>
      </div>
      <p>{read.error ?? "Reading stopped."}</p>
    </Panel>
  );
}

/** The setup page: reading progress (which a person may stop), a failed or stopped reading, then the setup form. */
export function SetupPage({ runId }: { runId: number }) {
  const [document, setDocument] = useState<RunDocument | null>(null);
  const [read, setRead] = useState<ReadProgress | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [round, setRound] = useState(0);
  const lastEvent = useRef(0);

  useEffect(() => {
    api.document(runId).then(setDocument, (failure) => setError(errorMessage(failure)));
  }, [runId]);

  // Ask for news about once a second until reading is done or failed. A
  // failed ask is shown and tried again after a short wait.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const [progress, page] = await Promise.all([api.readProgress(runId), api.events(runId, lastEvent.current)]);
        if (!live) return;
        lastEvent.current = page.last_id;
        if (page.events.length) setEvents((old) => [...old, ...page.events]);
        setRead(progress);
        if (progress.status === "done") {
          const [setup, map] = await Promise.all([api.suggestedSetup(runId), api.documentMap(runId)]);
          if (live) setLoaded({ setup, map });
          return;
        }
        setPollError("");
        if (progress.status === "failed" || progress.status === "stopped") return;
      } catch (failure) {
        if (!live) return;
        setPollError(errorMessage(failure));
        timer = setTimeout(poll, RETRY_MS);
        return;
      }
      timer = setTimeout(poll, POLL_MS);
    }
    void poll();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [runId, round]);

  const retry = useCallback(async () => {
    setRetrying(true);
    setError("");
    try {
      setRead(await api.retryReading(runId));
      setRound((n) => n + 1);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setRetrying(false);
    }
  }, [runId]);

  const stop = useCallback(async () => {
    setStopping(true);
    setError("");
    try {
      setRead(await api.stopReading(runId));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setStopping(false);
    }
  }, [runId]);

  // A hidden sheet brought in: the run reads its new pages, so the page shows reading again.
  const readAgain = useCallback((next: RunDocument) => {
    setDocument(next);
    setLoaded(null);
    setRead(null);
    setRound((n) => n + 1);
  }, []);

  if (loaded && document) return <SetupForm runId={runId} document={document} setup={loaded.setup} map={loaded.map} onRead={readAgain} />;

  // While the document is read the header offers Stop; once stopped, Try again reads on from the pages kept.
  const settled = read?.status === "failed" || read?.status === "stopped";
  let action = null;
  if (read?.status === "stopped") {
    action = (
      // Not primary: Start run stays the header's one primary button, as on a failed reading.
      <Button disabled={retrying} onClick={retry}>
        Try again
      </Button>
    );
  } else if (read && read.status !== "failed" && read.status !== "done") {
    action = read.stop_requested ? <Button disabled>Stopping</Button> : <Button disabled={stopping} onClick={stop}>Stop</Button>;
  }

  return (
    <>
      <SetupHeader action={action ?? undefined} />
      <div className="narrow">
        {error && <Failure label="Not loaded">{error}</Failure>}
        {pollError && <Failure label="Not updated">{pollError}</Failure>}
        <DocumentPanel document={document} runId={settled ? runId : undefined} />
        {read?.status === "failed" ? (
          <FailedPanel read={read} onRetry={retry} retrying={retrying} />
        ) : (
          read && <ReadingPanel read={read} events={events} />
        )}
      </div>
    </>
  );
}
