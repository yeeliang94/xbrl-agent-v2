import { useRef, useState, type DragEvent } from "react";
import { api, errorMessage } from "../api";
import { Button } from "../components/Button";
import { Failure } from "../components/Failure";
import { Panel } from "../components/Panel";
import { Status } from "../components/Status";
import { navigate } from "../router";
import "./NewRunPage.css";

/** Upload a PDF to start a run. The server reads it and the setup page follows. */
export function NewRunPage() {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState("");
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);

  async function upload(file: File | undefined) {
    if (!file || uploading) return;
    setError("");
    setUploading(file.name);
    try {
      const { run } = await api.upload(file);
      navigate({ name: "setup", runId: run.id });
    } catch (failure) {
      setError(errorMessage(failure));
      setUploading("");
      if (input.current) input.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setOver(false);
    void upload(event.dataTransfer.files[0]);
  }

  return (
    <>
      <div className="page-header">
        <h1>New run</h1>
      </div>
      <div className="narrow">
        {error && <Failure label="Upload failed">{error}</Failure>}
        <Panel>
          <div
            className={over ? "drop over" : "drop"}
            onDragOver={(event) => {
              event.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
          >
            <div>
              {uploading ? (
                <Status kind="working">{`Uploading ${uploading}`}</Status>
              ) : (
                <>
                  <span>Drop a PDF</span>
                  <Button onClick={() => input.current?.click()}>Choose file</Button>
                </>
              )}
              <input
                ref={input}
                type="file"
                accept=".pdf,application/pdf"
                aria-label="PDF file"
                hidden
                onChange={(event) => void upload(event.target.files?.[0])}
              />
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
