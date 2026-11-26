import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Issue } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Panel } from "../../components/Panel";
import { Segmented } from "../../components/Segmented";
import { Status } from "../../components/Status";
import { Table, type Column } from "../../components/Table";
import { TextArea } from "../../components/TextArea";
import { stamp } from "./words";

type Filter = "open" | "closed" | "all";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "all", label: "All" },
];

const reporter = (issue: Issue) => issue.reporter_name || issue.reporter_email;
const state = (issue: Issue) => <Status kind={issue.status === "open" ? "attention" : "finished"}>{issue.status === "open" ? "Open" : "Closed"}</Status>;

const COLUMNS: Column<Issue>[] = [
  { key: "id", header: "No.", render: (i) => i.id },
  { key: "when", header: "Reported", muted: true, nowrap: true, render: (i) => stamp(i.created_at) },
  { key: "who", header: "Person", nowrap: true, render: reporter },
  { key: "text", header: "What went wrong", cut: true, render: (i) => i.text },
  { key: "run", header: "Run", muted: true, nowrap: true, render: (i) => i.run_label.split(",")[0] },
  { key: "status", header: "Status", render: state },
];

/** What people reported, with a status and a note. Admins only. */
export function IssuesTab() {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("open");
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(() => {
    setError("");
    setIssues(null);
    api
      .issues()
      .then(setIssues)
      .catch((problem) => setError(errorMessage(problem)));
  }, []);
  useEffect(load, [load]);

  if (error) {
    return (
      <Panel className="sec">
        <div className="line">
          <span className="error" role="alert">
            {error}
          </span>
          <Button size="small" onClick={load}>
            Try again
          </Button>
        </div>
      </Panel>
    );
  }
  if (issues === null) return <p className="empty">Loading issues</p>;

  const shown = issues.filter((i) => filter === "all" || i.status === filter);
  const chosen = issues.find((i) => i.id === openId);
  let empty = "";
  if (issues.length === 0) empty = "No issues reported";
  else if (shown.length === 0) empty = `No ${filter} issues`;

  return (
    <Panel className="sec">
      <div className="line">
        <h2>Issues</h2>
        {issues.length > 0 && <Segmented label="Show" options={FILTERS} value={filter} onChange={setFilter} />}
      </div>
      {empty ? <p className="empty">{empty}</p> : <Table columns={COLUMNS} rows={shown} rowKey={(i) => String(i.id)} onRowClick={(i) => setOpenId(i.id)} />}
      {chosen && (
        <IssueDialog
          issue={chosen}
          onClose={() => setOpenId(null)}
          onChanged={(issue) => {
            setIssues((list) => (list ?? []).map((i) => (i.id === issue.id ? issue : i)));
            setOpenId(null);
          }}
          onDeleted={() => {
            setIssues((list) => (list ?? []).filter((i) => i.id !== chosen.id));
            setOpenId(null);
          }}
        />
      )}
    </Panel>
  );
}

interface IssueDialogProps {
  issue: Issue;
  onClose: () => void;
  onChanged: (issue: Issue) => void;
  onDeleted: () => void;
}

/** One issue: the report, its run's traces, the admin's note, and close, reopen or delete. */
function IssueDialog({ issue, onClose, onChanged, onDeleted }: IssueDialogProps) {
  const [note, setNote] = useState(issue.note);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const open = issue.status === "open";

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (problem) {
      setError(errorMessage(problem));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  const saveNote = () => act(async () => onChanged(await api.changeIssue(issue.id, { note })));
  // Closing or reopening keeps what is in the note box too.
  const toggle = () => act(async () => onChanged(await api.changeIssue(issue.id, { note, status: open ? "closed" : "open" })));
  const remove = () =>
    act(async () => {
      await api.deleteIssue(issue.id);
      onDeleted();
    });

  if (confirming) {
    return (
      <Dialog
        open
        title={`Delete issue ${issue.id}?`}
        onClose={onClose}
        actions={
          <>
            <Button variant="quiet" onClick={() => setConfirming(false)}>Cancel</Button>
            <Button variant="primary" disabled={busy} onClick={remove}>
              Delete issue
            </Button>
          </>
        }
      >
        <p className="meta">The report and its screenshot are removed. The run is kept.</p>
      </Dialog>
    );
  }

  let run = "None";
  if (issue.run_label) run = issue.run_id === null ? `${issue.run_label} (deleted)` : issue.run_label;

  return (
    <Dialog
      open
      wide
      title={`Issue ${issue.id}`}
      titleAside={state(issue)}
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" disabled={busy} onClick={() => setConfirming(true)}>
            Delete
          </Button>
          <span className="spacer" />
          <Button disabled={busy} onClick={saveNote}>
            Save note
          </Button>
          <Button variant="primary" disabled={busy} onClick={toggle}>
            {open ? "Close issue" : "Reopen"}
          </Button>
        </>
      }
    >
      <p>{issue.text}</p>
      <div className="kv">
        <span>Reported</span>
        <span>
          {reporter(issue)}, {stamp(issue.created_at)}
        </span>
        <span>Run</span>
        <span>{run}</span>
        <span>Screenshot</span>
        <span>
          {issue.file_name ? (
            <>
              {issue.file_name}{" "}
              <Button variant="quiet" size="small" aria-label="Download the screenshot" onClick={() => act(() => api.downloadIssueFile(issue))}>
                Download
              </Button>
            </>
          ) : (
            "None"
          )}
        </span>
      </div>
      {issue.run_id !== null && (
        <div>
          <Button disabled={busy} onClick={() => act(() => api.downloadIssueTraces(issue))}>
            Download this run's traces
          </Button>
        </div>
      )}
      <label className="field">
        <span>Note</span>
        <TextArea value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
