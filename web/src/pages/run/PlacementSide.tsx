import { useState } from "react";
import type { NoteSummary } from "../../api";
import { Button } from "../../components/Button";
import { TextInput } from "../../components/TextInput";
import { CHEVRON, FlagStatus, useDrop } from "./PlacementRows";
import {
  flagOf,
  noteTitle,
  searchFields,
  suggest,
  type PlaceField,
} from "./placementModel";
import type { Placement } from "./usePlacement";

export interface PlacementSideProps {
  note: NoteSummary | null;
  notes: NoteSummary[];
  fields: PlaceField[];
  placement: Placement;
  busy: boolean;
  working: boolean;
  onOpenNote: (noteId: number) => void;
}

const pageList = (pages: number[]) => {
  if (!pages.length) return "";
  const lo = Math.min(...pages);
  const hi = Math.max(...pages);
  return lo === hi ? String(lo) : `${lo} to ${hi}`;
};

/** A field to move the note to: a click moves it, and a note dragged onto it lands there. */
function Target({
  field,
  count,
  here,
  browsing,
  can,
  onMove,
}: {
  field: PlaceField;
  count: number;
  here: boolean;
  /** Listed under its own template's name, so that name is not repeated. */
  browsing: boolean;
  can: boolean;
  onMove: (field: PlaceField, noteId?: number) => void;
}) {
  const drop = useDrop((id) => onMove(field, id), can && !here);
  return (
    <button
      type="button"
      className={drop.over ? "ptarget over" : "ptarget"}
      disabled={!can || here}
      title={field.label}
      onClick={() => onMove(field)}
      {...drop.props}
    >
      <span className="pt">{field.short}</span>
      <span className="meta">
        {here
          ? "Here now"
          : count
            ? `${count} ${count === 1 ? "note" : "notes"}`
            : browsing
              ? ""
              : field.templateName}
      </span>
    </button>
  );
}

/** The chosen note on the placement map: where it sits, why it needs a look, and the fields it could move to. */
export function PlacementSide({
  note,
  notes,
  fields,
  placement,
  busy,
  working,
  onOpenNote,
}: PlacementSideProps) {
  const [query, setQuery] = useState("");
  const [browse, setBrowse] = useState<string | null>(null);
  if (!note) return null;

  const can = !busy && !working && !placement.saving;
  const flag = flagOf(note, fields);
  const here = note.field
    ? fields.find((f) => f.id === note.field!.node_uuid)
    : undefined;
  const count = (f: PlaceField) =>
    notes.filter((n) => n.field?.node_uuid === f.id).length;
  const name = `${note.number} ${noteTitle(note)}`.trim();
  const moveTo = (field: PlaceField, noteId = note.id) =>
    void placement.move(notes.find((x) => x.id === noteId) ?? note, field);
  const close = suggest(note, fields);
  const target = (f: PlaceField, browsing = false) => (
    <Target
      key={f.id}
      field={f}
      count={count(f)}
      here={f.id === here?.id}
      browsing={browsing}
      can={can}
      onMove={moveTo}
    />
  );
  const found = searchFields(query, fields);
  const templates = [
    ...new Map(fields.map((f) => [f.templateId, f.templateName])).entries(),
  ];

  return (
    <div className="det pside">
      <div className="dh">
        <h3>{name}</h3>
        <FlagStatus flag={flag} />
      </div>
      {(flag.kind === "check" || flag.kind === "not_placed") && (
        <p className="why">{flag.why}</p>
      )}
      <div className="pacts">
        {flag.kind === "check" && flag.better && (
          <Button
            size="small"
            disabled={!can}
            onClick={() => moveTo(flag.better!)}
          >
            {`Move to ${flag.better.short}`}
          </Button>
        )}
        {(flag.kind === "check" || flag.kind === "placed") && (
          <Button
            size="small"
            disabled={!can}
            onClick={() =>
              void placement.fieldIsRight(
                note,
                here?.short ?? note.field?.label ?? "its field",
              )
            }
          >
            Field is right
          </Button>
        )}
        <Button
          size="small"
          variant="quiet"
          onClick={() => onOpenNote(note.id)}
        >
          Open note
        </Button>
      </div>
      <div>
        <div className="frow">
          <span>Field</span>
          <span>{note.field?.label.replace(/^\*/, "") ?? "None"}</span>
        </div>
        {here && (
          <div className="frow">
            <span>Template</span>
            <span>{here.templateName}</span>
          </div>
        )}
        <div className="frow">
          <span>Pages</span>
          <span>{pageList(note.pages)}</span>
        </div>
      </div>
      <TextInput
        aria-label="Find a field"
        placeholder="Find a field"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {query.trim() ? (
        <div className="plist">
          {found.length ? (
            found.map((f) => target(f))
          ) : (
            <p className="why">No field matches</p>
          )}
        </div>
      ) : (
        <>
          {close.length > 0 && (
            <div className="plist">
              <h4>Closest by name</h4>
              {close.map((f) => target(f))}
            </div>
          )}
          <div className="plist">
            <h4>{`All ${fields.filter((f) => !f.heading).length} fields`}</h4>
            {templates.map(([id, title]) => (
              <div key={id} className="plist">
                <button
                  type="button"
                  className={browse === id ? "fold open" : "fold"}
                  aria-expanded={browse === id}
                  onClick={() => setBrowse(browse === id ? null : id)}
                >
                  {CHEVRON}
                  <span>{title}</span>
                </button>
                {browse === id &&
                  fields
                    .filter((f) => f.templateId === id && !f.heading)
                    .map((f) => target(f, true))}
              </div>
            ))}
          </div>
        </>
      )}
      {note.field && (
        <div>
          <Button
            size="small"
            variant="quiet"
            disabled={!can}
            onClick={() => void placement.move(note, null)}
          >
            Take out of its field
          </Button>
        </div>
      )}
    </div>
  );
}
