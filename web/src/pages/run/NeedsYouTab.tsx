import { useState, type KeyboardEvent } from "react";
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

/** How an item opens. A failed check's explanation (`failure`) goes with it to the Source tab; other
 * figures say theirs there already (an unsure figure's reason, an agent's comment on it). `stay` keeps this
 * list in view, for the arrow keys. `comments` shows the Comments tab, for an agent's comment on the notes as
 * a whole, which no note's panel shows. */
export interface OpenOptions {
  failure?: string;
  stay?: boolean;
  comments?: boolean;
}

/** What to carry when an item opens. */
function openOptions(item: NeedsYouItem, stay = false): OpenOptions {
  return {
    failure: item.kind === "failed_check" ? item.message : undefined,
    comments: item.kind === "agent_comment" && item.statement === "NOTES" && !item.note_id && !item.report_id,
    stay,
  };
}

export interface NeedsYouTabProps {
  needs: NeedsYou | null;
  extracting: boolean;
  busy: boolean;
  /** Opens the item's figure. */
  onOpen: (place: FigurePlace, options?: OpenOptions) => void;
  onAcceptAlike: () => Promise<void>;
  /** Escape: nothing selected. */
  onClear?: () => void;
  /** Some items are shown elsewhere on screen (the failed checks, on the Checks page). */
  others?: boolean;
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
      {open && (
        <div className="alike">
          {item.lines?.map((line) => (
            <button key={line.figure_id} type="button" className="alike-line" onClick={() => onOpen(line)}>
              <span>{line.printed_label}</span>
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

/** Keys that follow each item, not its position, so focus stays on it when the list around it changes.
 * Two items alike in every field are told apart by how many came before. */
function itemKeys(items: NeedsYouItem[]): string[] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const key = [item.kind, item.title, item.check, item.comment_id, item.concept_uuid, item.period, item.entity_scope, item.note_id, item.report_id].map((v) => v ?? "").join("|");
    const n = seen.get(key) ?? 0;
    seen.set(key, n + 1);
    return n ? `${key}#${n}` : key;
  });
}

/** Everything that waits for a person, in the server's order: one line each. */
export function NeedsYouTab({ needs, extracting, busy, onOpen, onAcceptAlike, onClear, others = false }: NeedsYouTabProps) {
  if (extracting) return <div className="empty">Shown when the agent finishes</div>;
  if (!needs) return <div className="empty">Loading what needs you</div>;
  const keys = itemKeys(needs.items);
  // From an item, the arrow keys move to the next or previous one and open its figure, keeping this list
  // in view; Escape clears the selection. Keys pressed inside an alike group stay with that group.
  function step(event: KeyboardEvent<HTMLDivElement>) {
    if (!needs) return;
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button.nyi")];
    const at = buttons.indexOf(event.target as HTMLButtonElement);
    if (at < 0) return;
    if (event.key === "Escape" && onClear) {
      event.preventDefault();
      onClear();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const next = buttons[event.key === "ArrowDown" ? Math.min(buttons.length - 1, at + 1) : Math.max(0, at - 1)];
    const item = next && needs.items[Number(next.dataset.i)];
    if (!next || !item) return;
    event.preventDefault();
    next.focus();
    onOpen(item, openOptions(item, true));
  }
  return (
    <div className="nyl" onKeyDown={step}>
      {needs.items.length === 0 && <div className="empty">{others ? "Nothing else needs you" : "Nothing needs you"}</div>}
      {needs.items.map((item, index) =>
        item.kind === "alike" ? (
          <Alike key={`alike-${index}`} item={item} busy={busy} onOpen={onOpen} onAccept={onAcceptAlike} />
        ) : (
          <button key={keys[index]} type="button" className="nyi" data-i={index} title={item.message} onClick={() => onOpen(item, openOptions(item))}>
            <span className="dh">
              <span className="nyi-title">{item.title}</span>
              <Status kind={item.kind === "note_too_long" || item.kind === "failed_check" ? "failure" : "attention"}>{reason(item)}</Status>
            </span>
          </button>
        ),
      )}
    </div>
  );
}

export const needsCount = (needs: NeedsYou | null) => needs?.items.length ?? 0;
