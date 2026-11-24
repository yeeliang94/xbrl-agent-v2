import { useRef, useState } from "react";
import { api, errorMessage, type RunDocument } from "../../api";
import { Button } from "../../components/Button";
import { Failure } from "../../components/Failure";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";
import { navigate } from "../../router";

/**
 * The run's document. With `runId` (setup ready, or reading failed; never
 * while reading), Replace uploads another PDF as a new run, deletes this run
 * and opens the new run's setup page.
 */
export function DocumentPanel({ document, runId }: { document: RunDocument | null; runId?: number }) {
  const input = useRef<HTMLInputElement>(null);
  const [replacing, setReplacing] = useState("");
  const [error, setError] = useState("");

  async function replace(file: File | undefined) {
    if (!file || runId === undefined || replacing) return;
    setError("");
    setReplacing(file.name);
    try {
      const { run } = await api.upload(file);
      try {
        await api.deleteRun(runId);
      } catch {
        // The new run is what the person asked for; the old one stays in the run list.
      }
      navigate({ name: "setup", runId: run.id });
    } catch (failure) {
      setError(errorMessage(failure));
      setReplacing("");
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      {error && <Failure label="Not replaced">{error}</Failure>}
      <Panel title="Document">
        <div className="line">
          <span>{document?.filename ?? ""}</span>
          {document && <span className="meta mono">{document.page_count} pages</span>}
          {runId !== undefined &&
            (replacing ? (
              <Status kind="working">{`Uploading ${replacing}`}</Status>
            ) : (
              <Button size="small" onClick={() => input.current?.click()}>
                Replace
              </Button>
            ))}
          {runId !== undefined && (
            <input
              ref={input}
              type="file"
              accept=".pdf,application/pdf"
              aria-label="Replacement PDF"
              hidden
              onChange={(event) => void replace(event.target.files?.[0])}
            />
          )}
        </div>
      </Panel>
    </>
  );
}

export function SetupHeader({ onStart, starting = false, ready = false }: { onStart?: () => void; starting?: boolean; ready?: boolean }) {
  return (
    <div className="page-header">
      <h1>New run</h1>
      <span className="spacer" />
      <Button variant="quiet" onClick={() => navigate({ name: "runs" })}>
        Cancel
      </Button>
      <Button variant="primary" disabled={!ready || starting} onClick={onStart}>
        Start run
      </Button>
    </div>
  );
}
