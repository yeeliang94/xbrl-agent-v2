import { useEffect, useRef, useState } from "react";
import { api, errorMessage, type Fill, type StartingWorkbook } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Status } from "../../components/Status";
import { Table, type Column } from "../../components/Table";
import { PlacementsCheck } from "./PlacementsCheck";
import { POLL_MS } from "./useRunData";

/** The longest wait between two asks after failed ones. */
export const MAX_POLL_MS = 10000;

interface Line {
  id: string;
  name: string;
  reason: string;
}

const LINE_COLUMNS: Column<Line>[] = [
  { key: "name", header: "Line", render: (line) => line.name },
  { key: "reason", header: "Reason", align: "right", muted: true, render: (line) => line.reason },
];

const TEMPLATE_WORDS: Record<string, string> = {
  unknown: "Template not recognised",
  probably_compatible: "Template not on the known list",
};

const active = (fill: Fill | null) => fill !== null && (fill.job_status === "queued" || fill.job_status === "filling");
/** The fill is ready but its places are still being looked for (step 12). */
const looking = (fill: Fill | null) => fill?.job_status === "ready" && (fill.investigation === "queued" || fill.investigation === "working");
/** A search for places takes minutes, so it is asked after less often than a fill. */
const LOOKING_POLL_MS = 3000;

/**
 * "Prepare mTool file": choose the run's mTool template and fill a copy of it. While it fills the
 * dialog waits; once ready it becomes the receipt, with the counts, every line not written and
 * Download. Opened again, it picks up a fill still running, or shows the latest ready fill's receipt,
 * from which another template can be chosen. A run with a starting workbook fills that workbook, so
 * nothing is chosen (step 10g).
 */
export function FillDialog({ runId, open, onClose }: { runId: number; open: boolean; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [fill, setFill] = useState<Fill | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [misses, setMisses] = useState(0);
  const [checking, setChecking] = useState(false);
  // undefined while asking: null for a run filled from a template, else the workbook attached at setup.
  const [starting, setStarting] = useState<StartingWorkbook | null | undefined>(undefined);
  const input = useRef<HTMLInputElement>(null);

  // On open: the fill still running, or the latest ready one with its receipt; otherwise start fresh.
  useEffect(() => {
    if (!open) return;
    let gone = false;
    setFile(null);
    setFill(null);
    setError("");
    setMisses(0);
    setChecking(false);
    setStarting(undefined);
    // Until the server says whether the run has a starting workbook, nothing is offered to fill.
    api.startingWorkbook(runId).then(
      (book) => !gone && setStarting(book),
      (failure) => !gone && setError(errorMessage(failure)),
    );
    api
      .fills(runId)
      .then(async (fills) => {
        const last = fills[fills.length - 1] ?? null;
        if (gone || last === null) return;
        if (active(last)) setFill(last);
        else if (last.job_status === "ready") {
          const full = await api.fill(runId, last.id);
          if (!gone) setFill(full);
        }
      })
      .catch(() => undefined);
    return () => {
      gone = true;
    };
  }, [open, runId]);

  // Ask for the fill until it is ready or failed. A failed ask is shown and asked again, waiting longer each time.
  const fillId = fill?.id;
  const waiting = open && (active(fill) || looking(fill));
  useEffect(() => {
    if (!waiting || fillId === undefined) return;
    let gone = false;
    const timer = setTimeout(async () => {
      try {
        const next = await api.fill(runId, fillId);
        if (gone) return;
        setError("");
        setMisses(0);
        setFill(next);
      } catch (failure) {
        if (gone) return;
        setError(errorMessage(failure));
        setMisses((n) => n + 1);
      }
    }, Math.min((looking(fill) ? LOOKING_POLL_MS : POLL_MS) * 2 ** misses, MAX_POLL_MS));
    return () => {
      gone = true;
      clearTimeout(timer);
    };
  }, [waiting, fillId, fill, runId, misses]);

  async function start() {
    if (!file && !starting) return;
    setSending(true);
    setError("");
    setMisses(0);
    try {
      setFill(await api.startFill(runId, starting ? null : file));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSending(false);
    }
  }

  async function download() {
    if (!fill) return;
    setSending(true);
    setError("");
    try {
      await api.downloadFill(runId, fill);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSending(false);
    }
  }

  function choose(next: File | undefined) {
    if (next) {
      setFile(next);
      setFill(null);
      setError("");
    }
    if (input.current) input.current.value = "";
  }

  const errorLine = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );
  const picker = (
    <input ref={input} type="file" hidden accept=".xlsx,.xlsm" aria-label="mTool template" onChange={(e) => choose(e.target.files?.[0])} />
  );

  if (checking && fill) {
    const back = (next: Fill) => {
      setChecking(false);
      setMisses(0);
      setFill(next);
    };
    return <PlacementsCheck runId={runId} fill={fill} open={open} onCancel={() => setChecking(false)} onFilled={back} />;
  }

  if (fill?.job_status === "ready" && fill.receipt) {
    const { counts, template } = fill.receipt;
    const compatibility = template.compatibility ?? "known";
    const check = fill.status === "needs review" || compatibility !== "known";
    const templateWords = TEMPLATE_WORDS[compatibility] ?? "Check the template";
    const toCheck = fill.investigation === "done" && (fill.placements_open ?? 0) > 0;
    const lines: Line[] = [
      ...template.reasons.map((reason, i) => ({ id: `template|${i}`, name: reason, reason: templateWords })),
      ...fill.receipt.lines,
    ];
    return (
      <Dialog
        open={open}
        title={check ? "mTool file needs a check" : "mTool file ready"}
        onClose={onClose}
        actions={
          <>
            <Button variant="quiet" onClick={onClose}>
              Close
            </Button>
            <Button variant={toCheck ? "outline" : "primary"} disabled={sending} onClick={download}>
              Download
            </Button>
            {toCheck && (
              <Button variant="primary" onClick={() => setChecking(true)}>
                Check placements
              </Button>
            )}
          </>
        }
      >
        <div className="stats">
          <div className="stat">
            <b>{counts.written}</b>
            <span>Written</span>
          </div>
          {starting && (
            <div className="stat">
              <b>{counts.kept_in_workbook ?? 0}</b>
              <span>Kept from the workbook</span>
            </div>
          )}
          <div className="stat">
            <b>{counts.not_written}</b>
            <span>{starting ? "Not written" : "Skipped"}</span>
          </div>
          {!starting && (
            <div className="stat">
              <b>{counts.notes}</b>
              <span>Notes</span>
            </div>
          )}
        </div>
        {looking(fill) && <Status kind="working">Looking for places in the template</Status>}
        {fill.investigation === "failed" && (
          <div className="fill-failure" role="alert">
            <Status kind="failure">Search for places failed</Status>
            <p>{fill.investigation_error ?? "The search for places did not finish."}</p>
          </div>
        )}
        {lines.length > 0 && (
          <div className="receipt-lines">
            <Table columns={LINE_COLUMNS} rows={lines} rowKey={(line) => line.id} header={false} />
          </div>
        )}
        <div className="line">
          <span>{fill.template_filename}</span>
          {starting ? (
            <Button size="small" disabled={sending} onClick={start}>
              Fill again
            </Button>
          ) : (
            <Button size="small" onClick={() => input.current?.click()}>
              Replace
            </Button>
          )}
        </div>
        {!starting && picker}
        {errorLine}
      </Dialog>
    );
  }

  const filling = active(fill) || sending;
  if (starting === undefined) {
    return (
      <Dialog
        open={open}
        title="Prepare mTool file"
        onClose={onClose}
        actions={
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
        }
      >
        {errorLine || <Status kind="working">Loading</Status>}
      </Dialog>
    );
  }
  if (starting) {
    return (
      <Dialog
        open={open}
        title="Prepare mTool file"
        onClose={onClose}
        actions={
          <>
            <Button variant="quiet" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={filling} onClick={start}>
              Fill workbook
            </Button>
          </>
        }
      >
        <div className="line">
          <span>{starting.filename}</span>
          {filling ? <Status kind="working">Filling</Status> : <span className="meta">Starting workbook</span>}
        </div>
        <p>The run's figures, notes and reports go into the workbook attached at setup. The figures that came from it stay exactly as they are.</p>
        {fill?.job_status === "failed" && (
          <div className="fill-failure" role="alert">
            <Status kind="failure">Fill failed</Status>
            <p>{fill.error ?? "The fill did not finish."}</p>
          </div>
        )}
        {errorLine}
      </Dialog>
    );
  }
  const name = file?.name ?? fill?.template_filename ?? null;
  return (
    <Dialog
      open={open}
      title="Prepare mTool file"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!file || filling} onClick={start}>
            Fill template
          </Button>
        </>
      }
    >
      <div className="line">
        <span className={name ? undefined : "meta"}>{name ?? "No template chosen"}</span>
        {filling ? (
          <Status kind="working">Filling</Status>
        ) : (
          <Button size="small" onClick={() => input.current?.click()}>
            {name ? "Replace" : "Choose template"}
          </Button>
        )}
      </div>
      {picker}
      {fill?.job_status === "failed" && (
        <div className="fill-failure" role="alert">
          <Status kind="failure">Fill failed</Status>
          <p>{fill.error ?? "The fill did not finish."}</p>
        </div>
      )}
      {errorLine}
    </Dialog>
  );
}
