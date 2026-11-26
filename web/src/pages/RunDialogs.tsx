// The run list's dialogs: delete one run, and clear abandoned drafts (admin).
import { useEffect, useState } from "react";
import { api, errorMessage, type Run, type RunDeletion } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { Select } from "../components/Select";
import { RUN_STATUS } from "./runStatus";

/** A run by its company and year, or by its file until setup names the company. */
export const runName = (run: Run) => (run.company ? [run.company, run.year].filter(Boolean).join(" ") : run.filename ?? `Run ${run.id}`);

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What goes with the run, named in the confirm dialog. */
export function whatGoes(run: Run, found: RunDeletion): string {
  if (!run.company) return "the uploaded PDF and everything read from it";
  const files = found.filled_workbook ? "the uploaded PDF and filled workbook" : "the uploaded PDF";
  return `its ${count(found.figures, "figure", "figures")} and ${count(found.notes, "note", "notes")}, ${files}, and the agents' traces`;
}

export interface DeleteAsk {
  run: Run;
  /** What the server says about deleting it; a sentence when that could not be read. */
  found: RunDeletion | string;
}

/** Confirms a delete, or says why the run stays: it is still working, or it is someone else's. */
export function DeleteRunDialog({ ask, onClose, onDeleted }: { ask: DeleteAsk | null; onClose: () => void; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setDeleting(false);
    setError("");
  }, [ask]);
  if (!ask) return null;
  const { run, found } = ask;
  const name = runName(run);
  const close = <Button onClick={onClose}>Close</Button>;

  if (typeof found === "string" || error) {
    return (
      <Dialog open title="This run was not deleted" onClose={onClose} actions={close}>
        <p>{typeof found === "string" ? found : error}</p>
      </Dialog>
    );
  }
  if (found.refused?.code === "working") {
    const doing = ["reading", "extracting", "correcting"].includes(run.status) ? RUN_STATUS[run.status].label.toLowerCase() : "working";
    return (
      <Dialog open title="This run can't be deleted yet" onClose={onClose} actions={close}>
        <p>{`${name} is still ${doing}. Stop it or wait until it finishes, then delete it.`}</p>
      </Dialog>
    );
  }
  if (found.refused) {
    return (
      <Dialog open title="This run isn't yours to delete" onClose={onClose} actions={close}>
        <p>{`Only its owner, ${run.owner_name || run.owner_email}, or an admin can delete ${name}.`}</p>
      </Dialog>
    );
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.deleteRun(run.id);
      onDeleted();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  return (
    <Dialog
      open
      title={`Delete ${name}?`}
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={deleting} onClick={() => void remove()}>
            Delete run
          </Button>
        </>
      }
    >
      <p>{`This removes ${whatGoes(run, found)}. It can't be undone.`}</p>
    </Dialog>
  );
}

const AGES = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

/** An admin clears runs still at setup that nobody has touched for a chosen number of days. */
export function ClearDraftsDialog({ open, onClose, onCleared }: { open: boolean; onClose: () => void; onCleared: (cleared: number) => void }) {
  const [days, setDays] = useState(30);
  const [found, setFound] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setFound(null);
    setError("");
    setClearing(false);
    api
      .abandonedDrafts(days)
      .then((n) => live && setFound(n))
      .catch((failure) => live && setError(errorMessage(failure)));
    return () => {
      live = false;
    };
  }, [open, days]);

  if (!open) return null;
  const n = found ?? 0;

  async function clear() {
    setClearing(true);
    try {
      onCleared(await api.clearDrafts(days));
    } catch (failure) {
      setError(errorMessage(failure));
      setClearing(false);
    }
  }

  let words = "Looking for drafts";
  if (error) words = error;
  else if (found === 0) words = "No runs at setup are that old.";
  else if (found !== null) {
    words = `${count(n, "run is", "runs are")} still at setup and ${n === 1 ? "has" : "have"} not been touched for ${days} days or more. Their uploaded PDFs and everything read from them are removed. It can't be undone.`;
  }

  return (
    <Dialog
      open
      title="Clear abandoned drafts?"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={n === 0 || clearing || error !== ""} onClick={() => void clear()}>
            {`Clear ${count(n, "draft", "drafts")}`}
          </Button>
        </>
      }
    >
      <div className="line drafts-age">
        <span>Not touched for</span>
        <Select aria-label="Not touched for" options={AGES} value={String(days)} onChange={(value) => setDays(Number(value))} />
      </div>
      <p className={error ? "error" : undefined} role={error ? "alert" : undefined}>
        {words}
      </p>
    </Dialog>
  );
}
