import { useEffect, useRef, useState } from "react";
import { api, errorMessage, type StartingWorkbook } from "../../api";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";

/** "MFRS, Company, RM": what the workbook says of itself, the parts it says. */
export function workbookSays(book: StartingWorkbook): string {
  const { standard, level, unit } = book.workbook;
  return [standard, level, unit === "RM'000" ? "RM thousands" : unit].filter(Boolean).join(", ");
}

/**
 * A part-filled mTool workbook to start from, attached at setup (step 10d). Its figures are imported
 * when the run starts; a workbook that does not fit the setup is refused then, with the reason.
 */
export function StartingWorkbookPanel({ runId, onBusy }: { runId: number; onBusy: (busy: boolean) => void }) {
  const [book, setBook] = useState<StartingWorkbook | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  const [refusal, setRefusal] = useState("");
  const input = useRef<HTMLInputElement>(null);
  // The run must not start while the workbook is still being attached or removed.
  useEffect(() => onBusy(busy !== ""), [busy, onBusy]);

  useEffect(() => {
    let gone = false;
    // A failed look shows the panel as empty: attaching then says plainly what is wrong, if anything.
    api.startingWorkbook(runId).then(
      (found) => !gone && setBook(found),
      () => !gone && setBook(null),
    );
    return () => {
      gone = true;
    };
  }, [runId]);

  async function attach(file: File | undefined) {
    if (input.current) input.current.value = "";
    if (!file) return;
    setBusy(`Uploading ${file.name}`);
    setRefusal("");
    try {
      setBook(await api.attachStartingWorkbook(runId, file));
    } catch (failure) {
      setRefusal(errorMessage(failure));
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    setBusy("Removing");
    setRefusal("");
    try {
      await api.removeStartingWorkbook(runId);
      setBook(null);
    } catch (failure) {
      setRefusal(errorMessage(failure));
    } finally {
      setBusy("");
    }
  }

  if (book === undefined) return null;
  const choose = (label: string) => (
    <Button size="small" disabled={busy !== ""} onClick={() => input.current?.click()}>
      {label}
    </Button>
  );
  return (
    <Panel className="sec">
      <div className="line">
        <h2>Starting workbook</h2>
        {busy ? (
          <Status kind="working">{busy}</Status>
        ) : book ? (
          <Button variant="quiet" size="small" onClick={remove}>
            Remove
          </Button>
        ) : refusal ? (
          <>
            <Status kind="failure">Not attached</Status>
            {choose("Attach another")}
          </>
        ) : (
          choose("Attach workbook")
        )}
      </div>
      {book && (
        <div className="line">
          <span>{book.filename}</span>
          <span className="meta">{workbookSays(book)}</span>
        </div>
      )}
      {refusal && <p role="alert">{refusal}</p>}
      <input ref={input} type="file" hidden accept=".xlsx,.xlsm" aria-label="Starting workbook" onChange={(e) => void attach(e.target.files?.[0])} />
    </Panel>
  );
}
