import { useState } from "react";
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
  const [shown, setShown] = useState<string | null>(null);
  const key = (c: Check) => `${c.name}|${c.entity_scope}`;
  // A check with a line opens it, explanation and all. One without a line unfolds its explanation here.
  const opens = (c: Check) => c.target_concept_uuid !== null;
  const explains = (c: Check) => !opens(c) && c.status !== "passed" && Boolean(c.message);
  const act = (c: Check) => (opens(c) ? onOpen(c) : setShown(shown === key(c) ? null : key(c)));
  const columns: Column<Check>[] = [
    {
      key: "check",
      header: "Check",
      render: (c) => {
        const title = group ? `${c.title}, ${c.entity_scope}` : c.title;
        // The title is a button so the keyboard reaches it; its click reaches the row, which acts.
        return opens(c) || explains(c) ? (
          <div className="check-text">
            <button type="button" className="check-btn" aria-expanded={explains(c) ? shown === key(c) : undefined}>
              {title}
            </button>
            {shown === key(c) && <p className="check-why">{c.message}</p>}
          </div>
        ) : (
          <div className="check-text">{title}</div>
        );
      },
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
          rowKey={key}
          onRowClick={act}
          rowClickable={(c) => opens(c) || explains(c)}
          empty={<div className="empty">No checks yet</div>}
        />
      </div>
    </>
  );
}
