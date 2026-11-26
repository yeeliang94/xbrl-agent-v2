import { useEffect, useState } from "react";
import { api, errorMessage, type KeptLine, type RedoPreview, type StatementCode } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Switch } from "../../components/Switch";
import { Table, type Column } from "../../components/Table";

const HOW = { edited: "Edited", confirmed: "Confirmed" } as const;

const COLUMNS: Column<KeptLine>[] = [
  { key: "label", header: "Line", render: (line) => line.label },
  { key: "how", header: "Kept because", align: "right", muted: true, nowrap: true, render: (line) => HOW[line.how] },
];

export interface RedoDialogProps {
  runId: number;
  statement: StatementCode;
  /** The statement as the screen names it, such as "Financial position". */
  name: string;
  open: boolean;
  onClose: () => void;
  /** The redo is queued: the run is busy again. */
  onStarted: () => Promise<void> | void;
}

/** Asks before a finished statement is filled again. The lines a person edited or confirmed are listed and
 * kept, unless the person switches that off. The other statements are not touched. */
export function RedoDialog({ runId, statement, name, open, onClose, onStarted }: RedoDialogProps) {
  const [preview, setPreview] = useState<RedoPreview | null>(null);
  const [keep, setKeep] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let live = true;
    setPreview(null);
    setKeep(true);
    setError("");
    api.redoPreview(runId, statement).then(
      (found) => live && setPreview(found),
      (failure) => live && setError(errorMessage(failure)),
    );
    return () => {
      live = false;
    };
  }, [open, runId, statement]);

  async function redo() {
    setBusy(true);
    setError("");
    try {
      await api.redoStatement(runId, statement, keep);
      await onStarted();
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  const kept = preview?.kept ?? [];
  const keeping = keep && kept.length > 0;
  const refusal = error || preview?.refusal;
  const label = `Keep the ${kept.length} ${kept.length === 1 ? "line" : "lines"} you edited or confirmed`;

  return (
    <Dialog
      open={open}
      title={`Redo ${name.charAt(0).toLowerCase()}${name.slice(1)}`}
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy || !preview || Boolean(preview.refusal)} onClick={() => void redo()}>
            {kept.length > 0 && !keep ? "Redo and replace all" : "Redo"}
          </Button>
        </>
      }
    >
      {kept.length > 0 && (
        <div className="line">
          <span>{label}</span>
          <Switch label="Keep the lines you edited or confirmed" checked={keep} onChange={setKeep} disabled={busy} />
        </div>
      )}
      {keeping && (
        <div className="redo-kept">
          <Table columns={COLUMNS} rows={kept} rowKey={(line) => `${line.concept_uuid}|${line.entity_scope}`} header={false} />
        </div>
      )}
      {refusal && (
        <p className="error" role="alert">
          {refusal}
        </p>
      )}
    </Dialog>
  );
}
