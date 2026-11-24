import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { GuidanceEditor } from "./GuidanceEditor";

/** The run's company guidance, once the run has a company: confirmed, or at setup the suggested name of an existing company. */
export function useRunCompany(runId: number, atSetup: boolean): number | null | undefined {
  const [companyId, setCompanyId] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    api.runGuidance(runId).then(
      (g) => live && setCompanyId(g.company_id !== null && (!atSetup || g.company_from_suggestion) ? g.company_id : null),
      () => live && setCompanyId(null),
    );
    return () => {
      live = false;
    };
  }, [runId, atSetup]);
  return companyId;
}

export function CompanyGuidance({ companyId, plain = false }: { companyId: number; plain?: boolean }) {
  const load = useCallback(() => api.companyGuidance(companyId).then((r) => r.guidance), [companyId]);
  const save = useCallback((basedOn: number, lines: string[]) => api.saveCompanyGuidance(companyId, basedOn, lines).then((r) => r.guidance), [companyId]);
  return <GuidanceEditor plain={plain} title="Guidance for this company" load={load} save={save} />;
}

/** The setup screen's panel: shown only when the suggested company already exists. */
export function SetupGuidance({ runId }: { runId: number }) {
  const companyId = useRunCompany(runId, true);
  return typeof companyId === "number" ? <CompanyGuidance companyId={companyId} /> : null;
}
