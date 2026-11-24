import { api } from "../../api";
import { CompanyGuidance, useRunCompany } from "../guidance/CompanyGuidance";
import { GuidanceEditor } from "../guidance/GuidanceEditor";

const loadFirm = () => api.firmGuidance().then((r) => r.guidance);
const saveFirm = (basedOn: number, lines: string[]) => api.saveFirmGuidance(basedOn, lines).then((r) => r.guidance);

/** The run's guidance: the company's, which anyone may change, and the firm's, changed on Settings. */
export function GuidanceView({ runId }: { runId: number }) {
  const companyId = useRunCompany(runId, false);
  return (
    <>
      <div className="wh">
        <h2>Guidance</h2>
      </div>
      <div className="wb guidance-body">
        {companyId === null && <p className="meta">This run has no company yet.</p>}
        {typeof companyId === "number" && <CompanyGuidance plain companyId={companyId} />}
        <GuidanceEditor plain readOnly title="Firm guidance" load={loadFirm} save={saveFirm} />
      </div>
    </>
  );
}
