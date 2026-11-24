import type { Report, ReportField, Reports } from "../../api";
import { Button } from "../../components/Button";
import { Status } from "../../components/Status";
import { fieldStatus, pageRange, shownValue, textPreview } from "./reportModel";

function Row({ field, selected, onSelect }: { field: ReportField; selected: boolean; onSelect: () => void }) {
  const status = fieldStatus(field);
  const preview = field.kind === "html" ? textPreview(field) : "";
  const value = field.kind === "html" ? preview && <span className="meta">{preview}</span> : shownValue(field);
  return (
    <tr className={selected ? "click sel" : "click"} onClick={onSelect}>
      <td>
        <button type="button" className="pick-name" aria-pressed={selected} onClick={(e) => (e.stopPropagation(), onSelect())}>
          {field.label}
        </button>
      </td>
      <td className="val">
        {value}
        {status && <Status kind={status.kind}>{status.word}</Status>}
      </td>
      <td className="meta mono r nw">{pageRange(field.pages)}</td>
    </tr>
  );
}

/** One report's fields in template order: the label, the value or why it is empty, and the page. */
export function ReportFields({ report, selected, onSelect }: { report: Report; selected: string | null; onSelect: (fieldId: string) => void }) {
  return (
    <>
      <div className="wh">
        <h2>{report.name}</h2>
        <span className="spacer" />
        <span className="meta">{`${report.total} fields`}</span>
      </div>
      <div className="wb">
        <table className="tbl ftbl">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Value</th>
              <th scope="col" className="r">
                Page
              </th>
            </tr>
          </thead>
          <tbody>
            {report.fields.map((field) => (
              <Row key={field.field_id} field={field} selected={selected === field.field_id} onSelect={() => onSelect(field.field_id)} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** A report's wording as mTool gets it, on the A4 page. */
export function ReportText({ field, onBack }: { field: ReportField; onBack: () => void }) {
  return (
    <>
      <div className="wh">
        <h2>{field.label}</h2>
        <span className="spacer" />
        <span className="meta mono">{pageRange(field.pages)}</span>
        <Button variant="quiet" size="small" onClick={onBack}>
          Back to fields
        </Button>
      </div>
      <div className="stage">
        <div className="a4">
          {field.html ? <div className="prep" dangerouslySetInnerHTML={{ __html: field.html }} /> : <p className="empty">No text saved.</p>}
        </div>
      </div>
    </>
  );
}

export interface ReportWorkProps {
  report: Report | null;
  field: ReportField | null;
  /** The narrative is open on its page instead of the fields. */
  text: boolean;
  error: string;
  /** The reports stage: a failed or stopped one says why above the fields; none means no report was found. */
  stage: Reports["stage"];
  onSelect: (fieldId: string) => void;
  onBack: () => void;
}

/** The work panel for a report: its fields, or its wording once opened. */
function StageLine({ stage }: { stage: Reports["stage"] }) {
  if (stage === null)
    return <p className="work-failure meta">The Reader found no directors' report, statement by directors or auditors' report, so the reports agent did not run.</p>;
  if (stage.status !== "failed" && stage.status !== "stopped") return null;
  return (
    <div className="work-failure" role={stage.status === "failed" ? "alert" : undefined}>
      <Status kind={stage.status === "failed" ? "failure" : "neutral"}>{stage.status === "failed" ? "Reports agent failed" : "Reports agent stopped"}</Status>
      {stage.error && <p>{stage.error}</p>}
    </div>
  );
}

export function ReportWork({ report, field, text, error, stage, onSelect, onBack }: ReportWorkProps) {
  if (error)
    return (
      <p className="work-failure error" role="alert">
        {error}
      </p>
    );
  if (!report) return null;
  if (text && field?.kind === "html") return <ReportText field={field} onBack={onBack} />;
  return (
    <>
      <StageLine stage={stage} />
      <ReportFields report={report} selected={field?.field_id ?? null} onSelect={onSelect} />
    </>
  );
}
