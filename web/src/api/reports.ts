// The reports and starting workbook routes (docs/api-contract.md, Step 10a-c and Step 10d).
import { request, uploadFile } from "./client";
import type { ReportCode, ReportField, ReportFieldEdit, Reports, StartingWorkbook } from "./reportTypes";

const runPath = (runId: number) => `/api/runs/${runId}`;
const fieldPath = (runId: number, report: ReportCode, field: string) => `${runPath(runId)}/reports/${report}/${encodeURIComponent(field)}`;

export const reportsApi = {
  reports: (runId: number) => request<Reports>("GET", `${runPath(runId)}/reports`),
  editReportField: (runId: number, report: ReportCode, field: string, edit: ReportFieldEdit) =>
    request<{ field: ReportField }>("PATCH", fieldPath(runId, report, field), edit).then((r) => r.field),
  clearReportField: (runId: number, report: ReportCode, field: string, revision: number) =>
    request<{ field: ReportField }>("POST", `${fieldPath(runId, report, field)}/clear`, { revision }).then((r) => r.field),
  startingWorkbook: (runId: number) =>
    request<{ starting_workbook: StartingWorkbook | null }>("GET", `${runPath(runId)}/starting-workbook`).then((r) => r.starting_workbook),
  attachStartingWorkbook: (runId: number, file: File) =>
    uploadFile<{ starting_workbook: StartingWorkbook }>(`${runPath(runId)}/starting-workbook`, file).then((r) => r.starting_workbook),
  removeStartingWorkbook: (runId: number) => request<void>("DELETE", `${runPath(runId)}/starting-workbook`),
};
