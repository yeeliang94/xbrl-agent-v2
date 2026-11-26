import { useState } from "react";
import { api, errorMessage } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Switch } from "../../components/Switch";

/** "Download traces": one zip of everything recorded for the run, the PDF only when switched on. */
export function TracesDialog({ runId, open, onClose }: { runId: number; open: boolean; onClose: () => void }) {
  const [pdf, setPdf] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function download() {
    setBusy(true);
    setError("");
    try {
      await api.downloadTraces(runId, pdf);
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      title="Download traces"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy} onClick={download}>
            Download
          </Button>
        </>
      }
    >
      <div className="line">
        <span>Include the uploaded PDF</span>
        <Switch label="Include the uploaded PDF" checked={pdf} onChange={setPdf} />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
