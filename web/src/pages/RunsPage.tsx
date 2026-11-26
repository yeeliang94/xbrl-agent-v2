import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Run, type RunList, type RunQuery, type Standard, type User } from "../api";
import { Button } from "../components/Button";
import { Icon, IconButton } from "../components/IconButton";
import { Panel } from "../components/Panel";
import { Segmented } from "../components/Segmented";
import { Select } from "../components/Select";
import { Status } from "../components/Status";
import { Table, type Column } from "../components/Table";
import { TextInput } from "../components/TextInput";
import { Toast } from "../components/Toast";
import { navigate } from "../router";
import { ClearDraftsDialog, DeleteRunDialog, type DeleteAsk } from "./RunDialogs";
import { formatUpdated, RUN_STATUS } from "./runStatus";
import "./RunsPage.css";

type View = "all" | "mine" | "in_review";
type DateFilter = "" | "today" | "7" | "30" | "year";

const VIEWS: { value: View; label: string }[] = [
  { value: "all", label: "All" },
  { value: "mine", label: "Mine" },
  { value: "in_review", label: "In review" },
];
const STATUSES = [
  { value: "", label: "Any status" },
  { value: "setup", label: "Setup" },
  { value: "working", label: "Working" },
  { value: "needs_answer", label: "Needs you" },
  { value: "in_review", label: "In review" },
  { value: "ready", label: "Ready" },
  { value: "filed", label: "Filed" },
  { value: "failed", label: "Failed" },
  { value: "stopped", label: "Stopped" },
];
const STANDARDS = [
  { value: "", label: "Any standard" },
  { value: "MFRS", label: "MFRS" },
  { value: "MPERS", label: "MPERS" },
];
const DATES = [
  { value: "", label: "Any time" },
  { value: "today", label: "Today" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "year", label: "This year" },
];
/** How long typing rests before the list is asked for again. */
const SEARCH_PAUSE_MS = 250;

/** The earliest update time a date filter lets through, in the person's own time zone. */
export function updatedSince(filter: DateFilter, now: Date = new Date()): string {
  if (filter === "") return "";
  if (filter === "year") return new Date(now.getFullYear(), 0, 1).toISOString();
  const daysBack = filter === "today" ? 0 : Number(filter) - 1;
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysBack).toISOString();
}

/** Runs still being read or set up, and a failed reading, open their setup page. */
function opensSetup(run: Run): boolean {
  if (run.filename === null) return false;
  if (run.status === "stopped") return run.failed_stage === "read";   // reading stopped: tried again from setup
  return run.status === "reading" || run.status === "setup" || (run.status === "failed" && run.failed_stage !== "extract");
}

/** Every run past setup opens the run screen, a failed extraction included. */
function opensRun(run: Run): boolean {
  return !opensSetup(run) && run.status !== "reading" && run.status !== "setup" && !(run.status === "failed" && run.failed_stage !== "extract");
}

export const REFRESH_MS = 5000;

function openRun(run: Run): void {
  navigate(opensSetup(run) ? { name: "setup", runId: run.id } : { name: "run", runId: run.id });
}

function columns(onDelete: (run: Run) => void): Column<Run>[] {
  return [
    { key: "company", header: "Company", render: (run) => run.company ?? "" },
    // Until setup names the company, a run is known by its file.
    { key: "file", header: "File", muted: true, width: "var(--runs-file-w)", render: (run) => run.filename ?? "" },
    { key: "year", header: "Year", width: "var(--runs-year-w)", render: (run) => (run.year === null ? "" : <span className="mono">{run.year}</span>) },
    { key: "filing", header: "Filing", width: "var(--runs-filing-w)", render: (run) => [run.standard, run.level].filter(Boolean).join(", ") },
    {
      key: "status",
      header: "Status",
      width: "var(--runs-status-w)",
      render: (run) => {
        const status = RUN_STATUS[run.status] ?? { label: run.status, kind: "neutral" as const };
        return <Status kind={status.kind}>{status.label}</Status>;
      },
    },
    { key: "updated", header: "Updated", muted: true, width: "var(--runs-updated-w)", render: (run) => formatUpdated(run.updated_at) },
    { key: "owner", header: "Owner", muted: true, width: "var(--runs-owner-w)", render: (run) => run.owner_name },
    {
      key: "delete",
      header: "",
      width: "var(--runs-delete-w)",
      render: (run) => (
        <IconButton
          label="Delete run"
          onClick={(event) => {
            event.stopPropagation();
            onDelete(run);
          }}
        >
          <Icon name="trash" />
        </IconButton>
      ),
    },
  ];
}

export function RunsPage({ user }: { user: User }) {
  const [list, setList] = useState<RunList | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("all");
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [standard, setStandard] = useState("");
  const [date, setDate] = useState<DateFilter>("");
  const [page, setPage] = useState(0);
  const [reloads, setReloads] = useState(0);
  const [ask, setAsk] = useState<DeleteAsk | null>(null);
  const [drafts, setDrafts] = useState(false);
  const [toast, setToast] = useState("");

  // The search waits for a pause in typing, then starts again from the first page.
  useEffect(() => {
    if (typed.trim() === q) return;
    const timer = window.setTimeout(() => {
      setQ(typed.trim());
      setPage(0);
    }, SEARCH_PAUSE_MS);
    return () => window.clearTimeout(timer);
  }, [typed, q]);

  // The list refreshes itself, so a run's status moves without a reload.
  // The next request waits for the last reply, so an old reply never lands after a newer one.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let runsSeen = false;
    const query: RunQuery = {
      q,
      status: (view === "in_review" ? "in_review" : status) as RunQuery["status"],
      standard: standard as Standard | "",
      updated_since: updatedSince(date),
      mine: view === "mine",
      page,
    };
    const load = async () => {
      // A hidden tab waits; it catches up on its next turn once shown.
      if (document.hidden && runsSeen) {
        timer = setTimeout(load, REFRESH_MS);
        return;
      }
      runsSeen = true;
      try {
        const found = await api.runs(query);
        if (!live) return;
        setError("");
        setList(found);
        // The server gives the last page when the one asked for no longer exists.
        setPage((old) => (old === found.page ? old : found.page));
      } catch (failure) {
        if (live) setError(errorMessage(failure));
      }
      if (live) timer = setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q, status, standard, date, view, page, reloads]);

  const filtered = typed.trim() !== "" || status !== "" || standard !== "" || date !== "";
  const change = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setPage(0);
  };
  const reset = () => {
    setTyped("");
    setQ("");
    setStatus("");
    setStandard("");
    setDate("");
    setPage(0);
  };
  const reload = () => setReloads((n) => n + 1);

  function askDelete(run: Run) {
    api
      .runDeletion(run.id)
      .then((found) => setAsk({ run, found }))
      .catch((failure) => setAsk({ run, found: errorMessage(failure) }));
  }

  const runs = list?.runs ?? [];
  const total = list?.total ?? 0;
  const perPage = list?.per_page ?? 25;
  const from = page * perPage;

  let empty = "No runs yet";
  if (error) empty = error;
  else if (list === null) empty = "Loading runs";
  else if (filtered || view !== "all") empty = "No runs match";

  const clearToast = useCallback(() => setToast(""), []);

  return (
    <>
      <div className="page-header">
        <h1>Runs</h1>
        <span className="spacer" />
        <Segmented label="Show" options={VIEWS} value={view} onChange={change(setView)} />
        <Button variant="primary" onClick={() => navigate({ name: "new-run" })}>
          New run
        </Button>
      </div>
      <Panel className="runs-panel" padded={false}>
        <div className="runs-tools">
          <TextInput
            type="search"
            className="runs-search"
            placeholder="Search company or file"
            aria-label="Search company or file"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          <Select aria-label="Status" options={STATUSES} disabled={view === "in_review"} value={view === "in_review" ? "in_review" : status} onChange={change(setStatus)} />
          <Select aria-label="Standard" options={STANDARDS} value={standard} onChange={change(setStandard)} />
          <Select aria-label="Updated" options={DATES} value={date} onChange={change((value: string) => setDate(value as DateFilter))} />
          {filtered && (
            <Button variant="quiet" onClick={reset}>
              Clear filters
            </Button>
          )}
        </div>
        <div className="runs-body">
          {runs.length === 0 || error ? (
            <div className={error ? "empty error" : "empty"} role={error ? "alert" : undefined}>
              {empty}
            </div>
          ) : (
            <Table
              columns={columns(askDelete)}
              rows={runs}
              rowKey={(run) => String(run.id)}
              onRowClick={openRun}
              rowClickable={(run) => opensSetup(run) || opensRun(run)}
            />
          )}
        </div>
        <div className="runs-foot">
          {user.is_admin && (
            <Button variant="quiet" onClick={() => setDrafts(true)}>
              Clear abandoned drafts
            </Button>
          )}
          <span className="spacer" />
          {runs.length > 0 && !error && (
            <>
              <span className="meta mono runs-count">{`${from + 1}–${from + runs.length} of ${total}`}</span>
              <Button size="small" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <Button size="small" disabled={from + runs.length >= total} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </>
          )}
        </div>
      </Panel>
      <DeleteRunDialog
        ask={ask}
        onClose={() => setAsk(null)}
        onDeleted={() => {
          setAsk(null);
          setToast("Run deleted");
          reload();
        }}
      />
      <ClearDraftsDialog
        open={drafts}
        onClose={() => setDrafts(false)}
        onCleared={(cleared) => {
          setDrafts(false);
          setToast(`${cleared} ${cleared === 1 ? "draft" : "drafts"} cleared`);
          reload();
        }}
      />
      <Toast text={toast} onDone={clearToast} />
    </>
  );
}
