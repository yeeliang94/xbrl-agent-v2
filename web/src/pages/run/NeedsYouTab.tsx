import { useState } from "react";
import { errorMessage, type FigurePlace, type NeedsYou, type NeedsYouItem } from "../../api";
import { Button } from "../../components/Button";
import { Status } from "../../components/Status";

/** The reason each kind of item waits for a person. */
function reason(item: NeedsYouItem): string {
  switch (item.kind) {
    case "failed_check":
      return "Check failed";
    case "unsure":
      return "Unsure";
    case "agent_comment":
      return "Agent comment";
    case "alike":
      return `${item.count ?? item.lines?.length ?? 0} alike`;
    case "note_to_check":
      return "Check formatting";
    case "unplaced_note":
      return "Not placed";
    case "note_gap":
      return "Gap in source";
    case "missing_field":
      return "Missing field";
    case "note_too_long":
      return "Too long for mTool";
  }
}

export interface NeedsYouTabProps {
  needs: NeedsYou | null;
  extracting: boolean;
  busy: boolean;
  onOpen: (place: FigurePlace) => void;
  onAcceptAlike: () => Promise<void>;
}

function Alike({ item, busy, onOpen, onAccept }: { item: NeedsYouItem; busy: boolean; onOpen: NeedsYouTabProps["onOpen"]; onAccept: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  async function accept() {
    setError("");
    try {
      await onAccept();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }
  return (
    <div className="nyi">
      <div className="dh">
        <span className="nyi-title">{item.title}</span>
        <Status kind="attention">{reason(item)}</Status>
      </div>
      <p className="why">{item.message}</p>
      {open && (
        <div className="alike">
          {item.lines?.map((line) => (
            <button key={line.figure_id} type="button" className="alike-line" onClick={() => onOpen(line)}>
              <span>{line.printed_label}</span>
              <span className="meta">Filed as {line.field_label}</span>
            </button>
          ))}
        </div>
      )}
      <div className="bar">
        {error && (
          <span className="error" role="alert">
            {error}
          </span>
        )}
        <span className="spacer" />
        <Button variant="quiet" size="small" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show each"}
        </Button>
        {!busy && (
          <Button size="small" onClick={accept}>
            Accept all
          </Button>
        )}
      </div>
    </div>
  );
}

/** Everything that waits for a person, in the server's order, ending with the count that passed. */
export function NeedsYouTab({ needs, extracting, busy, onOpen, onAcceptAlike }: NeedsYouTabProps) {
  if (extracting) return <div className="empty">Shown when the agent finishes</div>;
  if (!needs) return <div className="empty">Loading what needs you</div>;
  return (
    <>
      {needs.items.length === 0 && <div className="empty">Nothing needs you</div>}
      {needs.items.map((item, index) =>
        item.kind === "alike" ? (
          <Alike key={`alike-${index}`} item={item} busy={busy} onOpen={onOpen} onAccept={onAcceptAlike} />
        ) : (
          <button key={`${item.kind}-${index}`} type="button" className="nyi" onClick={() => onOpen(item)}>
            <span className="dh">
              <span className="nyi-title">{item.title}</span>
              <Status kind={item.kind === "note_too_long" ? "failure" : "attention"}>{reason(item)}</Status>
            </span>
            <span className="why">{item.message}</span>
          </button>
        ),
      )}
      <p className="meta">{`${needs.passed} other figure${needs.passed === 1 ? "" : "s"} passed their checks`}</p>
    </>
  );
}

export const needsCount = (needs: NeedsYou | null) => needs?.items.length ?? 0;
