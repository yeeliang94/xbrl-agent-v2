import type { Check, CheckStatus, StatementCode } from "../../api";
import { Status, type StatusKind } from "../../components/Status";
import { Table, type Column } from "../../components/Table";

const LOOK: Record<CheckStatus, { kind: StatusKind; word: string }> = {
  passed: { kind: "finished", word: "Passed" },
  failed: { kind: "failure", word: "Failed" },
  warning: { kind: "attention", word: "Warning" },
  not_applicable: { kind: "neutral", word: "Not applicable" },
  not_assessed: { kind: "neutral", word: "Not assessed" },
};

/** The statement a check's line sits on: its first comparand's, else the first in the run. */
export function checkStatement(check: Check, fallback: StatementCode): StatementCode {
  const named = check.comparands.find((c) => c.statement)?.statement?.toUpperCase();
  return (named as StatementCode | undefined) ?? fallback;
}

export function ChecksView({ checks, group, busy, onOpen }: { checks: Check[]; group: boolean; busy: boolean; onOpen: (check: Check) => void }) {
  const columns: Column<Check>[] = [
    {
      key: "check",
      header: "Check",
      render: (c) => (
        <div className="check-text">
          <div>{group ? `${c.title}, ${c.entity_scope}` : c.title}</div>
          {c.status !== "passed" && c.message && <div className="l2">{c.message}</div>}
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      align: "right",
      render: (c) => (busy ? <Status kind="neutral">Waiting</Status> : <Status kind={LOOK[c.status].kind}>{LOOK[c.status].word}</Status>),
    },
  ];
  return (
    <>
      <div className="wh">
        <h2>Checks</h2>
      </div>
      <div className="wb">
        <Table
          columns={columns}
          rows={checks}
          rowKey={(c) => `${c.name}|${c.entity_scope}`}
          onRowClick={onOpen}
          rowClickable={(c) => c.target_concept_uuid !== null}
          empty={<div className="empty">No checks yet</div>}
        />
      </div>
    </>
  );
}
