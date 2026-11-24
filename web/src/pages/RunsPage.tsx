import { useEffect, useState } from "react";
import { api, errorMessage, type Run, type User } from "../api";
import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import { Segmented } from "../components/Segmented";
import { Status } from "../components/Status";
import { Table, type Column } from "../components/Table";
import { navigate } from "../router";
import { formatUpdated, RUN_STATUS } from "./runStatus";
import "./RunsPage.css";

type Filter = "all" | "mine" | "in_review";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "mine", label: "Mine" },
  { value: "in_review", label: "In review" },
];

const COLUMNS: Column<Run>[] = [
  // Until setup names the company, a run is known by its file.
  { key: "company", header: "Company", render: (run) => run.company ?? run.filename ?? "" },
  { key: "year", header: "Year", render: (run) => (run.year === null ? "" : <span className="mono">{run.year}</span>) },
  {
    key: "filing",
    header: "Filing",
    render: (run) => [run.standard, run.level].filter(Boolean).join(", "),
  },
  {
    key: "status",
    header: "Status",
    render: (run) => {
      const status = RUN_STATUS[run.status] ?? { label: run.status, kind: "neutral" as const };
      return <Status kind={status.kind}>{status.label}</Status>;
    },
  },
  { key: "updated", header: "Updated", muted: true, render: (run) => formatUpdated(run.updated_at) },
  { key: "owner", header: "Owner", muted: true, render: (run) => run.owner_name },
];

/** Runs still being read or set up, and a failed reading, open their setup page. */
function opensSetup(run: Run): boolean {
  if (run.filename === null) return false;
  return run.status === "reading" || run.status === "setup" || (run.status === "failed" && run.failed_stage !== "extract");
}

/** Every run past setup opens the run screen, a failed extraction included. */
function opensRun(run: Run): boolean {
  return !opensSetup(run) && run.status !== "reading" && run.status !== "setup" && !(run.status === "failed" && run.failed_stage !== "extract");
}

function openRun(run: Run): void {
  navigate(opensSetup(run) ? { name: "setup", runId: run.id } : { name: "run", runId: run.id });
}

export function RunsPage({ user }: { user: User }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    let live = true;
    api
      .runs()
      .then((list) => live && setRuns(list))
      .catch((failure) => live && setError(errorMessage(failure)));
    return () => {
      live = false;
    };
  }, []);

  const shown = (runs ?? []).filter((run) => {
    if (filter === "mine") return run.owner_email === user.email;
    if (filter === "in_review") return run.status === "in_review";
    return true;
  });

  let empty = "No runs yet";
  if (error) empty = error;
  else if (runs === null) empty = "Loading runs";
  else if (runs.length > 0) empty = "No runs here";

  return (
    <>
      <div className="page-header">
        <h1>Runs</h1>
        <span className="spacer" />
        <Segmented label="Show" options={FILTERS} value={filter} onChange={setFilter} />
        <Button variant="primary" onClick={() => navigate({ name: "new-run" })}>
          New run
        </Button>
      </div>
      <Panel className="runs-panel">
        <Table
          columns={COLUMNS}
          rows={shown}
          rowKey={(run) => String(run.id)}
          onRowClick={openRun}
          rowClickable={(run) => opensSetup(run) || opensRun(run)}
          empty={<div className={error ? "empty error" : "empty"} role={error ? "alert" : undefined}>{empty}</div>}
        />
      </Panel>
    </>
  );
}
