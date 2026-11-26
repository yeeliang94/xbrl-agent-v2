import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { TextArea } from "./TextArea";

/** "Report an issue", from anywhere in the app. With a run on screen, the report carries that run. */
export function ReportIssueDialog({ runId, onClose }: { runId: number | null; onClose: () => void }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [runName, setRunName] = useState(runId === null ? "" : `Run ${runId}`);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (runId === null) return;
    let live = true;
    api
      .run(runId)
      .then((run) => {
        if (!live) return;
        if (run.company) setRunName(run.year ? `${run.company}, FY${run.year}` : run.company);
        else if (run.filename) setRunName(run.filename);
      })
      .catch(() => {}); // the run's number is shown instead
    return () => {
      live = false;
    };
  }, [runId]);

  async function send() {
    setBusy(true);
    setError("");
    try {
      setSent((await api.reportIssue(text.trim(), runId, file)).id);
    } catch (problem) {
      setError(errorMessage(problem));
    } finally {
      setBusy(false);
    }
  }

  if (sent !== null) {
    return (
      <Dialog
        open
        title={`Issue ${sent} sent`}
        onClose={onClose}
        actions={
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        }
      >
        <p className="meta">The admins can see it now{runId === null ? "" : ", with this run linked"}.</p>
      </Dialog>
    );
  }

  return (
    <Dialog
      open
      title="Report an issue"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={busy || !text.trim()} onClick={send}>
            Send
          </Button>
        </>
      }
    >
      <label className="field">
        <span>What went wrong</span>
        <TextArea value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {runId !== null && (
        <div className="line">
          <span className="meta">Run</span>
          <span>{runName}</span>
        </div>
      )}
      <div className="line">
        <span className="meta">Screenshot</span>
        <input
          ref={picker}
          type="file"
          hidden
          aria-label="Screenshot file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        {file ? (
          <>
            <span>{file.name}</span>
            <Button variant="quiet" size="small" onClick={() => setFile(null)}>
              Remove
            </Button>
          </>
        ) : (
          <Button size="small" onClick={() => picker.current?.click()}>
            Attach a screenshot
          </Button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
