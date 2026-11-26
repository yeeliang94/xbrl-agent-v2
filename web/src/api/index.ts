import { adminApi } from "./admin";
import { downloadFile, request, uploadFile } from "./client";
import { notesApi } from "./notes";
import { reportsApi } from "./reports";
import type {
  AcceptAll,
  Check,
  Comment,
  Comparison,
  Fill,
  Placement,
  FilledWorkbook,
  ConfirmedSetup,
  DocumentMap,
  EventPage,
  Figure,
  FigureEdit,
  GuidanceLineKept,
  GuidancePage,
  RunDetail,
  RunGuidance,
  ScopeQuestion,
  Model,
  NeedsYou,
  NewComment,
  ReadProgress,
  RedoPreview,
  Run,
  RunDeletion,
  RunList,
  RunQuery,
  RunCost,
  Round,
  RoundReport,
  RunDocument,
  SheetGrid,
  Settings,
  Statement,
  StatementCode,
  SettingsChange,
  SuggestedSetup,
  User,
} from "./types";

export { ApiError, errorMessage, setUnauthorizedHandler } from "./client";
export type * from "./types";
export type * from "./noteTypes";
export type * from "./reportTypes";
export type * from "./admin";

const runPath = (id: number) => `/api/runs/${id}`;
/** The run list's filters as a query string, leaving out what is not set. */
function runQuery(query: RunQuery): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== "" && value !== false && value !== 0) params.set(name, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}
/** "Seri Maju.xlsx" becomes "Seri Maju filled.xlsx", as the server names it. */
const filledName = (name: string) => name.replace(/(\.[^.]+)?$/, (ext) => ` filled${ext || ".xlsx"}`);

export const api = {
  login: (email: string, password: string) =>
    request<{ user: User }>("POST", "/api/auth/login/password", { email, password }).then((r) => r.user),
  me: () => request<{ user: User }>("GET", "/api/auth/me").then((r) => r.user),
  logout: () => request<void>("POST", "/api/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("POST", "/api/auth/change-password", { current_password, new_password }),
  /** One page of the run list, after the search and the filters. */
  runs: (query: RunQuery = {}) => request<RunList>("GET", `/api/runs${runQuery(query)}`),
  runDeletion: (id: number) => request<RunDeletion>("GET", `${runPath(id)}/deletion`),
  abandonedDrafts: (days: number) => request<{ count: number }>("GET", `/api/admin/drafts?older_than_days=${days}`).then((r) => r.count),
  clearDrafts: (days: number) => request<{ cleared: number }>("POST", "/api/admin/drafts/clear", { older_than_days: days }).then((r) => r.cleared),
  upload: (file: File) => uploadFile<{ run: Run; document: RunDocument }>("/api/runs", file),
  deleteRun: (id: number) => request<void>("DELETE", runPath(id)),
  document: (id: number) => request<{ document: RunDocument }>("GET", `${runPath(id)}/document`).then((r) => r.document),
  /** One sheet of an Excel run's workbook. */
  sheet: (id: number, name: string) => request<{ sheet: SheetGrid }>("GET", `${runPath(id)}/sheets/${encodeURIComponent(name)}`).then((r) => r.sheet),
  /** Brings a hidden sheet into a run waiting at setup; the run then reads the new pages. */
  bringInSheet: (id: number, sheet: string) => request<{ run: Run; document: RunDocument }>("POST", `${runPath(id)}/sheets/bring-in`, { sheet }),
  readProgress: (id: number) => request<{ read: ReadProgress }>("GET", `${runPath(id)}/read`).then((r) => r.read),
  retryReading: (id: number) => request<{ read: ReadProgress }>("POST", `${runPath(id)}/read/retry`).then((r) => r.read),
  stopReading: (id: number) => request<{ read: ReadProgress }>("POST", `${runPath(id)}/read/stop`).then((r) => r.read),
  /** `hideInternal` leaves out the agent loop's own rows (`step`, `tool`). */
  events: (id: number, afterId: number, limit = 100, hideInternal = false) =>
    request<EventPage>("GET", `${runPath(id)}/events?after_id=${afterId}&limit=${limit}${hideInternal ? "&hide_internal=true" : ""}`),
  documentMap: (id: number) => request<{ map: DocumentMap }>("GET", `${runPath(id)}/map`).then((r) => r.map),
  suggestedSetup: (id: number) => request<{ setup: SuggestedSetup }>("GET", `${runPath(id)}/setup`).then((r) => r.setup),
  confirmSetup: (id: number, setup: ConfirmedSetup) => request<{ run: Run }>("POST", `${runPath(id)}/setup`, setup),
  pageImage: (id: number, page: number) => `${runPath(id)}/pages/${page}/image`,
  run: (id: number) => request<{ run: RunDetail }>("GET", runPath(id)).then((r) => r.run),
  stopExtraction: (id: number) => request<{ run: Run }>("POST", `${runPath(id)}/extract/stop`).then((r) => r.run),
  retryExtraction: (id: number) => request<{ run: Run }>("POST", `${runPath(id)}/extract/retry`).then((r) => r.run),
  /** Whether a statement can be redone now, and the lines a person edited or confirmed. */
  redoPreview: (id: number, statement: StatementCode) =>
    request<{ redo: RedoPreview }>("GET", `${runPath(id)}/statements/${statement}/redo`).then((r) => r.redo),
  /** Clears the statement and lets the figures agent fill it again; the other statements stay as they are. */
  redoStatement: (id: number, statement: StatementCode, keepMine: boolean) =>
    request<{ run: Run; cleared: number; kept: number }>("POST", `${runPath(id)}/statements/${statement}/redo`, { keep_mine: keepMine }),
  runCost: (id: number) => request<{ cost: RunCost }>("GET", `${runPath(id)}/cost`).then((r) => r.cost),
  statement: (id: number, statement: StatementCode, order: "report" | "template") =>
    request<Statement>("GET", `${runPath(id)}/statements/${statement}?order=${order}`),
  checks: (id: number) => request<{ checks: Check[] }>("GET", `${runPath(id)}/checks`).then((r) => r.checks),
  editFigure: (id: number, edit: FigureEdit) => request<{ figure: Figure }>("POST", `${runPath(id)}/figures`, edit),
  moveFigure: (id: number, figureId: number, to: string, wholeRow: boolean) =>
    request<{ figures: Figure[] }>("POST", `${runPath(id)}/figures/${figureId}/move`, { to_concept_uuid: to, whole_row: wholeRow }),
  confirmFigure: (id: number, figureId: number) => request<{ figure: Figure }>("POST", `${runPath(id)}/figures/${figureId}/confirm`),
  comments: (id: number) => request<{ comments: Comment[] }>("GET", `${runPath(id)}/comments`).then((r) => r.comments),
  addComment: (id: number, comment: NewComment) => request<{ comment: Comment }>("POST", `${runPath(id)}/comments`, comment),
  removeComment: (id: number, commentId: number) => request<void>("DELETE", `${runPath(id)}/comments/${commentId}`),
  replyComment: (id: number, commentId: number, text: string) =>
    request<{ comment: Comment }>("POST", `${runPath(id)}/comments/${commentId}/reply`, { text }),
  acceptComment: (id: number, commentId: number) => request<{ comment: Comment }>("POST", `${runPath(id)}/comments/${commentId}/accept`),
  undoComment: (id: number, commentId: number) =>
    request<{ comments: Comment[]; guidance_line_kept?: GuidanceLineKept[] }>("POST", `${runPath(id)}/comments/${commentId}/undo`),
  commentDone: (id: number, commentId: number) => request<{ comment: Comment }>("POST", `${runPath(id)}/comments/${commentId}/done`),
  acceptAll: (id: number) => request<{ comments: Comment[] }>("POST", `${runPath(id)}/comments/accept-all`),
  sendRound: (id: number, clientId: string) => request<{ round: Round }>("POST", `${runPath(id)}/rounds`, { client_id: clientId }).then((r) => r.round),
  rounds: (id: number) => request<{ rounds: Round[]; accept_all?: AcceptAll }>("GET", `${runPath(id)}/rounds`),
  round: (id: number, roundId: number) => request<{ round: Round; report: RoundReport }>("GET", `${runPath(id)}/rounds/${roundId}`),
  stopRound: (id: number, roundId: number) => request<{ round: Round }>("POST", `${runPath(id)}/rounds/${roundId}/stop`).then((r) => r.round),
  needsYou: (id: number) => request<NeedsYou>("GET", `${runPath(id)}/needs-you`),
  acceptAlike: (id: number) => request<NeedsYou>("POST", `${runPath(id)}/needs-you/alike/accept`),
  question: (id: number) => request<{ question: ScopeQuestion | null }>("GET", `${runPath(id)}/question`).then((r) => r.question),
  questions: (id: number) => request<{ questions: ScopeQuestion[] }>("GET", `${runPath(id)}/questions`).then((r) => r.questions),
  answerQuestion: (id: number, questionId: number, answer: { choice: number } | { text: string }) =>
    request<{ question: ScopeQuestion; run: Run }>("POST", `${runPath(id)}/question/answer`, { ...answer, question_id: questionId }),
  runGuidance: (id: number) => request<RunGuidance>("GET", `${runPath(id)}/guidance`),
  companyGuidance: (companyId: number) => request<GuidancePage>("GET", `/api/companies/${companyId}/guidance`),
  saveCompanyGuidance: (companyId: number, basedOn: number, lines: string[]) =>
    request<GuidancePage>("PUT", `/api/companies/${companyId}/guidance`, { based_on: basedOn, lines }),
  restoreCompanyGuidance: (companyId: number, version: number, basedOn: number) =>
    request<GuidancePage>("POST", `/api/companies/${companyId}/guidance/restore`, { version, based_on: basedOn }),
  firmGuidance: () => request<GuidancePage>("GET", "/api/guidance/firm"),
  saveFirmGuidance: (basedOn: number, lines: string[]) => request<GuidancePage>("PUT", "/api/guidance/firm", { based_on: basedOn, lines }),
  addProposedGuidance: (id: number, commentId: number, basedOn?: number) =>
    request<GuidancePage & { comment: Comment }>("POST", `${runPath(id)}/comments/${commentId}/guidance`, basedOn === undefined ? {} : { based_on: basedOn }),
  dismissProposedGuidance: (id: number, commentId: number) =>
    request<{ comment: Comment }>("POST", `${runPath(id)}/comments/${commentId}/guidance/dismiss`),
  filledWorkbook: (id: number) => request<{ workbook: FilledWorkbook | null }>("GET", `${runPath(id)}/filled-workbook`).then((r) => r.workbook),
  attachWorkbook: (id: number, file: File) => uploadFile<{ workbook: FilledWorkbook }>(`${runPath(id)}/filled-workbook`, file).then((r) => r.workbook),
  removeWorkbook: (id: number) => request<void>("DELETE", `${runPath(id)}/filled-workbook`),
  comparison: (id: number) => request<{ comparison: Comparison }>("GET", `${runPath(id)}/comparison`).then((r) => r.comparison),
  /** Without a file, fills the run's starting workbook (step 10g). */
  startFill: (id: number, file: File | null) =>
    (file ? uploadFile<{ fill: Fill }>(`${runPath(id)}/fills`, file) : request<{ fill: Fill }>("POST", `${runPath(id)}/fills`)).then((r) => r.fill),
  fills: (id: number) => request<{ fills: Fill[] }>("GET", `${runPath(id)}/fills`).then((r) => r.fills),
  fill: (id: number, fillId: number) => request<{ fill: Fill }>("GET", `${runPath(id)}/fills/${fillId}`).then((r) => r.fill),
  /** The places proposed for the figures a fill could not place (step 12). */
  placements: (id: number, fillId: number) => request<{ placements: Placement[] }>("GET", `${runPath(id)}/fills/${fillId}/placements`).then((r) => r.placements),
  /** Saves the places chosen to use for the template, skips the rest, and fills it again. */
  usePlacements: (id: number, fillId: number, use: number[]) =>
    request<{ fill: Fill }>("POST", `${runPath(id)}/fills/${fillId}/placements`, { use }).then((r) => r.fill),
  downloadFill: (id: number, fill: Fill) => downloadFile(`${runPath(id)}/fills/${fill.id}/file`, filledName(fill.template_filename)),
  downloadTraces: (id: number, includePdf: boolean) =>
    downloadFile(`${runPath(id)}/traces${includePdf ? "?include_pdf=1" : ""}`, `run-${id}-traces.zip`),
  settings: () => request<Settings>("GET", "/api/settings"),
  saveSettings: (change: SettingsChange) => request<Settings>("PUT", "/api/settings", change),
  models: () => request<{ models: Model[] }>("GET", "/api/models").then((r) => r.models),
  downloadLogs: () => downloadFile("/api/settings/records/logs", "server-logs.zip"),
  downloadUsage: () => downloadFile("/api/settings/records/usage", "usage.csv"),
  ...notesApi,
  ...reportsApi,
  ...adminApi,
};
