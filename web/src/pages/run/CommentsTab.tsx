import { useState } from "react";
import { api, errorMessage, type Change, type GuidanceLineKept, type NoteChange, type Comment, type FigurePlace, type Outcome, type Round, type RoundReport } from "../../api";
import { Button } from "../../components/Button";
import { Icon, IconButton } from "../../components/IconButton";
import { Status, type StatusKind } from "../../components/Status";
import { TextArea } from "../../components/TextArea";
import { statementName, type Layouts } from "../setup/setupModel";
import { ProposalCard } from "./ProposalCard";
import { formatAmount, isLive, placeName } from "./runModel";

const OUTCOME: Record<Outcome, { kind: StatusKind; word: string }> = {
  changed: { kind: "finished", word: "Changed" },
  not_changed: { kind: "neutral", word: "Not changed" },
  question: { kind: "attention", word: "Question" },
};

const SCOPE_WORDS = { figure: "", run: "Applies to the run", company: "Applies to the company" };

/** "Other payables, last year", or the statement for a statement comment. */
export function commentPlace(c: Comment, layouts: Layouts = {}): string {
  if (c.target.kind === "statement" && c.target.statement) return c.target.statement === "NOTES" ? c.target.field_label ?? "The notes" : statementName(c.target.statement, layouts[c.target.statement]);
  if (c.target.kind === "line") return c.target.field_label ?? "";
  // A note comment: the server names the note and the part.
  if (c.target.kind === "note") return c.target.field_label ?? "Note";
  return placeName(c.target.field_label, c.target.period);
}

/** The person's comments still in play, in the order they were written. */
export const liveComments = (comments: Comment[]) => comments.filter((c) => c.author_kind === "person" && isLive(c));

export interface CommentsTabProps {
  runId: number;
  comments: Comment[];
  rounds: Round[];
  report: RoundReport | null;
  working: boolean;
  onOpen: (place: FigurePlace) => void;
  onChanged: () => Promise<void>;
  /** Each statement's layout, so a comment on a retained earnings statement names it as one. */
  layouts?: Layouts;
}

/** The latest round: the agent's sentence, then the server's own count of what changed. */
function RoundSummary({ round, report, onOpen }: { round: Round; report: RoundReport | null; onOpen: CommentsTabProps["onOpen"] }) {
  const other = (report?.other ?? []).filter((c) => c.changed);
  const otherNotes = (report?.notes_other ?? []).filter((n) => n.changed);
  const commented = report?.counts.comments ?? round.comment_ids.length;
  const changed = report?.comments.filter((c) => c.changed).length ?? 0;
  return (
    <div className="det">
      {round.status === "failed" && (
        <div>
          <Status kind="failure">Round failed</Status>
        </div>
      )}
      {round.status === "stopped" && (
        <div>
          <Status kind="neutral">Stopped</Status>
        </div>
      )}
      {round.error && <p>{round.error}</p>}
      {round.summary && <p>{round.summary}</p>}
      {report && (
        <p className="why">
          {`Changed ${changed} of ${commented} commented item${commented === 1 ? "" : "s"}.`}
          {other.length > 0 && ` ${other.length} other figure${other.length === 1 ? "" : "s"} changed: `}
          {other.map((c, i) => (
            <span key={`${c.concept_uuid}|${c.period}|${c.entity_scope}`}>
              <button type="button" className="lk" onClick={() => onOpen(c)}>
                {placeName(c.field_label, c.period)}
              </button>
              {i < other.length - 1 ? ", " : "."}
            </span>
          ))}
          {otherNotes.length > 0 && ` ${otherNotes.length} other note${otherNotes.length === 1 ? "" : "s"} changed: `}
          {otherNotes.map((n, i) => (
            <span key={n.note_id}>
              <button type="button" className="lk" onClick={() => onOpen({ note_id: n.note_id })}>
                {noteChangeName(n)}
              </button>
              {i < otherNotes.length - 1 ? ", " : "."}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

const noteChangeName = (n: NoteChange) => (n.number ? `Note ${n.number} ${n.title}` : n.title);

/** A note the round changed for a comment: what moved, in the server's words. */
function NoteBeforeAfter({ changes }: { changes: NoteChange[] }) {
  const shown = changes.filter((n) => n.changed);
  return (
    <>
      {shown.map((n) => (
        <p key={n.note_id} className="why">
          {shown.length > 1 && <span className="meta">{noteChangeName(n)} </span>}
          {n.differences.join(", ")}
        </p>
      ))}
    </>
  );
}

function BeforeAfter({ changes }: { changes: Change[] }) {
  const shown = changes.filter((c) => c.changed);
  return (
    <>
      {shown.map((c) => (
        <div key={`${c.concept_uuid}|${c.period}|${c.entity_scope}`}>
          <p className="mono">
            {shown.length > 1 && <span className="meta">{placeName(c.field_label, c.period)} </span>}
            <s>{formatAmount(c.was) || "blank"}</s> to {formatAmount(c.is_now) || "blank"}
          </p>
          {c.differences && c.differences.length > 0 && <p className="why">{c.differences.join(", ")}</p>}
        </div>
      ))}
    </>
  );
}

function CommentCard({ comment, report, working, onKept, ...props }: { comment: Comment; report: RoundReport | null; working: boolean; onKept: (kept: GuidanceLineKept[]) => void } & Pick<CommentsTabProps, "runId" | "onOpen" | "onChanged" | "layouts">) {
  const { runId, onOpen, onChanged } = props;
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");
  const outcome = comment.status === "answered" && comment.outcome ? OUTCOME[comment.outcome] : null;
  const counted = report?.comments.find((c) => c.comment_id === comment.id);
  const changes = counted?.figures ?? [];
  const noteChanges = counted?.notes ?? [];

  async function act(work: () => Promise<unknown>) {
    setError("");
    try {
      await work();
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  const t = comment.target;
  const where: FigurePlace = { statement: t.statement, concept_uuid: t.concept_uuid, period: t.period, entity_scope: t.entity_scope, figure_id: t.figure_id, note_id: t.note_id ?? null, report_id: t.report_id ?? null };
  return (
    <div className="cm">
      <div className="dh">
        <span>
          <button type="button" className="loc" onClick={() => onOpen(where)}>
            {commentPlace(comment, props.layouts)}
          </button>
          {SCOPE_WORDS[comment.scope] && <span className="meta"> · {SCOPE_WORDS[comment.scope]}</span>}
        </span>
        {comment.status === "open" && !working && (
          <IconButton label="Remove comment" onClick={() => act(() => api.removeComment(runId, comment.id))}>
            <Icon name="close" />
          </IconButton>
        )}
      </div>
      <p>{comment.text}</p>
      {comment.status === "sent" && working && (
        <div>
          <Status kind="working">Working</Status>
        </div>
      )}
      {outcome && (
        <>
          <div>
            <Status kind={outcome.kind}>{outcome.word}</Status>
          </div>
          {comment.answer && <p>{comment.answer}</p>}
          <BeforeAfter changes={changes} />
          <NoteBeforeAfter changes={noteChanges} />
          {comment.outcome === "question" ? (
            <>
              <TextArea aria-label="Reply" placeholder="Reply" value={reply} onChange={(e) => setReply(e.target.value)} />
              <div className="bar">
                <span className="spacer" />
                <Button size="small" disabled={!reply.trim()} onClick={() => act(() => api.replyComment(runId, comment.id, reply.trim()))}>
                  Reply
                </Button>
              </div>
            </>
          ) : (
            <div className="bar">
              <span className="spacer" />
              {comment.outcome === "changed" && (
                <Button variant="quiet" size="small" onClick={() => act(async () => onKept((await api.undoComment(runId, comment.id)).guidance_line_kept ?? []))}>
                  Undo
                </Button>
              )}
              <Button size="small" onClick={() => act(() => api.acceptComment(runId, comment.id))}>
                {comment.outcome === "changed" ? "Accept" : "Done"}
              </Button>
            </div>
          )}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function CommentsTab({ runId, comments, rounds, report, working, onOpen, onChanged, layouts }: CommentsTabProps) {
  const last = rounds[rounds.length - 1];
  const ended = last && !working && (last.status === "done" || last.status === "failed" || last.status === "stopped");
  const list = liveComments(comments);
  // Undone comments whose guidance line stays, from the undo response, by comment.
  const [kept, setKept] = useState<Record<number, GuidanceLineKept>>({});
  const onKept = (lines: GuidanceLineKept[]) => setKept((old) => ({ ...old, ...Object.fromEntries(lines.map((k) => [k.comment_id, k])) }));
  const proposals = ended ? comments.filter((c) => c.round_id === last.id && c.proposed_guidance && c.status !== "open") : [];
  return (
    <>
      {ended && <RoundSummary round={last} report={report?.round_id === last.id ? report : null} onOpen={onOpen} />}
      {proposals.map((c) => (
        <ProposalCard key={`proposal-${c.id}`} runId={runId} comment={c} kept={kept[c.id]} onChanged={onChanged} />
      ))}
      {list.length === 0 && !ended && <div className="empty">No comments</div>}
      {list.map((c) => (
        <CommentCard key={c.id} comment={c} report={report} working={working} onKept={onKept} runId={runId} onOpen={onOpen} onChanged={onChanged} layouts={layouts} />
      ))}
    </>
  );
}
