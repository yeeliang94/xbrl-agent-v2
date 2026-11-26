import { useEffect, useState } from "react";
import { api, errorMessage, type AuditEntry, type AuditGroup, type AuditPage } from "../../api";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";
import { Select, type SelectOption } from "../../components/Select";
import { Table, type Column } from "../../components/Table";
import { auditAction, auditDetail, auditPerson, stamp } from "./words";

const PAGE = 20;

const GROUPS: SelectOption[] = [
  { value: "", label: "All actions" },
  { value: "users", label: "Users" },
  { value: "settings", label: "Settings" },
  { value: "runs", label: "Runs" },
  { value: "issues", label: "Issues" },
];

const COLUMNS: Column<AuditEntry>[] = [
  { key: "when", header: "When", muted: true, nowrap: true, render: (e) => stamp(e.at) },
  { key: "person", header: "Person", nowrap: true, render: auditPerson },
  { key: "action", header: "Action", nowrap: true, render: auditAction },
  { key: "detail", header: "Detail", muted: true, cut: true, render: auditDetail },
];

/** Who did what, newest first, by person and by kind of action, twenty to a page. Admins only. */
export function AuditTab() {
  const [actor, setActor] = useState("");
  const [group, setGroup] = useState<AuditGroup | "">("");
  const [page, setPage] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [log, setLog] = useState<AuditPage | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setError("");
    api
      .audit({ actor, group, offset: page * PAGE, limit: PAGE })
      .then((loaded) => live && setLog(loaded))
      .catch((problem) => live && setError(errorMessage(problem)));
    return () => {
      live = false;
    };
  }, [actor, group, page, attempt]);

  if (error) {
    return (
      <Panel className="sec">
        <div className="line">
          <span className="error" role="alert">
            {error}
          </span>
          <Button size="small" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      </Panel>
    );
  }
  if (log === null) return <p className="empty">Loading the audit log</p>;

  const filtered = actor !== "" || group !== "";
  const people: SelectOption[] = [
    { value: "", label: "Everyone" },
    ...log.people.map((p) => ({ value: p.email, label: p.name || p.email })),
  ];
  const from = page * PAGE;

  return (
    <Panel className="sec">
      <div className="line">
        <h2>Audit log</h2>
        {(log.total > 0 || filtered) && (
          <>
            <div className="ctl">
              <Select
                aria-label="Person"
                options={people}
                value={actor}
                onChange={(v) => {
                  setActor(v);
                  setPage(0);
                }}
              />
            </div>
            <div className="ctl">
              <Select
                aria-label="Action"
                options={GROUPS}
                value={group}
                onChange={(v) => {
                  setGroup(v as AuditGroup | "");
                  setPage(0);
                }}
              />
            </div>
          </>
        )}
      </div>
      {log.total === 0 ? (
        <p className="empty">{filtered ? "No entries match" : "Nothing recorded yet"}</p>
      ) : (
        <>
          <Table columns={COLUMNS} rows={log.events} rowKey={(e) => String(e.id)} />
          <div className="pager">
            <span className="meta mono">{`${from + 1}–${from + log.events.length} of ${log.total}`}</span>
            <Button size="small" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button size="small" disabled={!log.has_more} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        </>
      )}
    </Panel>
  );
}
