// The notes routes (docs/api-contract.md, Step 6b and Step 6e).
import { request } from "./client";
import type { FormatState, Note, NoteBlock, NoteField, NoteHistoryEntry, NoteReport, NoteReview, NoteSummary, PreparedNote } from "./noteTypes";

const notesPath = (runId: number) => `/api/runs/${runId}/notes`;

export const notesApi = {
  notes: (runId: number) => request<{ notes: NoteSummary[] }>("GET", notesPath(runId)).then((r) => r.notes),
  note: (runId: number, noteId: number) => request<{ note: Note }>("GET", `${notesPath(runId)}/${noteId}`).then((r) => r.note),
  noteHistory: (runId: number, noteId: number) =>
    request<{ history: NoteHistoryEntry[] }>("GET", `${notesPath(runId)}/${noteId}/history`).then((r) => r.history),
  setNoteLook: (runId: number, noteId: number, blocks: NoteBlock[], formatState?: FormatState) =>
    request<{ note: Note; history_id?: number | null }>("POST", `${notesPath(runId)}/${noteId}/look`, formatState ? { blocks, format_state: formatState } : { blocks }),
  /** `null` takes the note out of its field ("Not placed"). A person's move also confirms the field. `history_id` is what Undo takes. */
  setNoteField: (runId: number, noteId: number, nodeUuid: string | null) =>
    request<{ note: Note; history_id: number | null }>("POST", `${notesPath(runId)}/${noteId}/field`, { node_uuid: nodeUuid }),
  /** "Field is right": confirms the note's field only; its formatting and gaps stay. */
  confirmField: (runId: number, noteId: number) => request<{ note: Note; history_id: number }>("POST", `${notesPath(runId)}/${noteId}/field/confirm`),
  confirmNote: (runId: number, noteId: number) => request<{ note: Note }>("POST", `${notesPath(runId)}/${noteId}/confirm`).then((r) => r.note),
  undoNote: (runId: number, noteId: number, historyId: number) =>
    request<{ note: Note }>("POST", `${notesPath(runId)}/${noteId}/undo`, { history_id: historyId }).then((r) => r.note),
  /** the run's note fields, headings marked (app/catalog/note_fields.py). */
  noteFields: (runId: number) => request<{ fields: NoteField[] }>("GET", `${notesPath(runId)}/fields`).then((r) => r.fields),
  /** the notes agent's reports: source gaps and missing mandatory fields. */
  noteReports: (runId: number) => request<{ reports: NoteReport[] }>("GET", `${notesPath(runId)}/reports`).then((r) => r.reports),
  /** a person leaves a missing mandatory field empty, or takes that back. */
  leaveFieldEmpty: (runId: number, reportId: number) =>
    request<{ report: NoteReport }>("POST", `${notesPath(runId)}/reports/${reportId}/leave-empty`).then((r) => r.report),
  reopenField: (runId: number, reportId: number) =>
    request<{ report: NoteReport }>("POST", `${notesPath(runId)}/reports/${reportId}/reopen`).then((r) => r.report),
  /** the prepared text of the note's whole field, for Copy for mTool. */
  preparedNote: (runId: number, noteId: number) =>
    request<{ prepared: PreparedNote }>("GET", `${notesPath(runId)}/${noteId}/prepared`).then((r) => r.prepared),
  /** the text the review page draws: the field's prepared text with marks to select by. */
  noteReview: (runId: number, noteId: number) =>
    request<{ review: NoteReview }>("GET", `${notesPath(runId)}/${noteId}/review`).then((r) => r.review),
};
