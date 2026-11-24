import { useEffect, useState } from "react";
import { api, ApiError, errorMessage, type ReportField } from "../../api";
import { Button } from "../../components/Button";
import { PagePicture } from "../../components/PagePicture";
import { Select } from "../../components/Select";
import { Status } from "../../components/Status";
import { TextInput } from "../../components/TextInput";
import { fieldStatus, pageRange } from "./reportModel";

export interface ReportSideProps {
  runId: number;
  field: ReportField | null;
  busy: boolean;
  onOpenText: () => void;
  onChanged: () => Promise<void>;
}

/** The chosen report field: why it is empty, its value to change, Clear, and the page it was read from. */
export function ReportSide({ runId, field, busy, onOpenText, onChanged }: ReportSideProps) {
  const [typed, setTyped] = useState(field?.value ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setTyped(field?.value ?? "");
  }, [field?.field_id, field?.revision, field?.value]);
  useEffect(() => setError(""), [field?.field_id]);

  if (!field) return <p className="meta">Choose a field to see its page and change it.</p>;
  const status = fieldStatus(field);
  const text = field.kind === "html";

  async function act(work: () => Promise<unknown>) {
    setSaving(true);
    setError("");
    try {
      await work();
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
      // Someone else changed the field first: load their version, so the next save starts from it.
      if (failure instanceof ApiError && failure.status === 409) await onChanged();
    } finally {
      setSaving(false);
    }
  }

  const f = field;
  const save = () => {
    const value = typed.trim();
    if (!value) return setError(`Give a value for ${f.label}, or clear it.`);
    if (value === (f.value ?? "")) return;
    void act(() => api.editReportField(runId, f.report, f.field_id, { revision: f.revision, status: "filled", value, pages: f.pages }));
  };
  const clear = () => void act(() => api.clearReportField(runId, f.report, f.field_id, f.revision));
  const locked = busy || saving;

  return (
    <div className="det">
      <div className="dh">
        <h3>{field.label}</h3>
        {status ? <Status kind={status.kind}>{status.word}</Status> : <span className="meta mono">{pageRange(field.pages)}</span>}
      </div>
      {field.reason && <p>{field.reason}</p>}
      {!text &&
        (field.kind === "choice" ? (
          <Select aria-label={field.label} disabled={locked} options={[{ value: "", label: "" }, ...field.choices.map((c) => ({ value: c, label: c }))]} value={typed} onChange={setTyped} />
        ) : (
          <TextInput aria-label={field.label} type={field.kind === "date" ? "date" : "text"} disabled={locked} value={typed} onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
        ))}
      <div className="bar">
        {text ? (
          field.html && (
            <Button size="small" onClick={onOpenText}>
              Open text
            </Button>
          )
        ) : (
          <Button size="small" disabled={locked || typed.trim() === (field.value ?? "")} onClick={save}>
            Save
          </Button>
        )}
        {field.status !== "cleared" && field.status !== "not_assessed" && (
          <Button variant="quiet" size="small" disabled={locked} onClick={clear}>
            Clear
          </Button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {field.pages.length > 0 && <PagePicture runId={runId} page={field.pages[0]} />}
    </div>
  );
}
