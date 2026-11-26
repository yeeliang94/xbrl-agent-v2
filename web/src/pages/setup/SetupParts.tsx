import { useRef, useState, type ReactNode } from "react";
import { api, errorMessage, type RunDocument } from "../../api";
import { Button } from "../../components/Button";
import { Failure } from "../../components/Failure";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";
import { navigate } from "../../router";
import { ACCEPT } from "../NewRunPage";

/**
 * The run's document. With `runId` (setup ready, or reading failed; never
 * while reading), Replace uploads another file as a new run, deletes this run
 * and opens the new run's setup page.
 */
/** "38 pages", or for a workbook its sheets: "10 sheets". */
export function documentCount(document: RunDocument): string {
  const count = document.kind === "excel" && document.sheets ? document.sheets.length : document.page_count;
  const word = document.kind === "excel" && document.sheets ? "sheet" : "page";
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

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
          {document && <span className="meta mono">{documentCount(document)}</span>}
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
              accept={ACCEPT}
              aria-label="Replacement file"
              hidden
              onChange={(event) => void replace(event.target.files?.[0])}
            />
          )}
        </div>
        {/* An Excel sheet whose formulas were saved without a result: those cells read as empty. */}
        {document?.sheets?.filter((s) => s.notice).map((s) => (
          <p key={s.name}>{s.notice}</p>
        ))}
      </Panel>
    </>
  );
}

export function SetupHeader({ onStart, starting = false, ready = false, action }: { onStart?: () => void; starting?: boolean; ready?: boolean; /** Stop or Try again, while the document is still being read. */ action?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>New run</h1>
      <span className="spacer" />
      <Button variant="quiet" onClick={() => navigate({ name: "runs" })}>
        Cancel
      </Button>
      {action}
      <Button variant="primary" disabled={!ready || starting} onClick={onStart}>
        Start run
      </Button>
    </div>
  );
}
