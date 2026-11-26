import { useEffect, useState } from "react";
import { api, errorMessage, type RunCost } from "../../api";
import { Table, type Column } from "../../components/Table";

interface Row {
  agent: string;
  seconds: number;
  cost_usd: number | null;
  /** Calls with no known price: the cost shown is then only part of it. */
  unpriced: number;
  total?: boolean;
}

/** "38:12": minutes and seconds an agent spent waiting on the model. */
export const span = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
/** "$0.94". Blank when no price is known: a missing cost is not zero. "$0.94+" when some calls have no price. */
export const money = (usd: number | null, unpriced = 0) => (usd === null ? "" : `$${usd.toFixed(2)}${unpriced > 0 ? "+" : ""}`);

const figure = (text: string, row: Row) => <span className={row.total ? "mono cost-total" : "mono"}>{text}</span>;

const COLUMNS: Column<Row>[] = [
  { key: "agent", header: "Agent", render: (row) => (row.total ? <span className="cost-whole">{row.agent}</span> : row.agent) },
  { key: "time", header: "Time", align: "right", nowrap: true, render: (row) => figure(span(row.seconds), row) },
  { key: "cost", header: "Cost", align: "right", nowrap: true, render: (row) => figure(money(row.cost_usd, row.unpriced), row) },
];

/** One quiet line at the foot of the Activity tab. Opened, it shows the run's cost and time per agent.
 * The figures are read when it is opened, so a run nobody asks about costs no request. */
export function CostFold({ runId }: { runId: number }) {
  const [open, setOpen] = useState(false);
  const [cost, setCost] = useState<RunCost | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let live = true;
    setError("");
    api.runCost(runId).then(
      (found) => live && setCost(found),
      (failure) => live && setError(errorMessage(failure)),
    );
    return () => {
      live = false;
    };
  }, [open, runId]);

  const rows: Row[] = cost ? [...cost.agents, { agent: "Whole run", ...cost.total, total: true }] : [];

  return (
    <div className="costs">
      <button type="button" className={open ? "fold open" : "fold"} aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" />
        </svg>
        <span>Cost and time</span>
      </button>
      {open && error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {open && cost && (cost.agents.length === 0 ? <div className="empty">No model calls</div> : <Table columns={COLUMNS} rows={rows} rowKey={(row) => row.agent} />)}
    </div>
  );
}
