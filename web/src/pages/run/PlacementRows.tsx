// The placement map's rows: report order, mTool order, and what a note row, a chip and a field row do.
import {
  useState,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { NoteSummary } from "../../api";
import { Status } from "../../components/Status";
import {
  needsLook,
  noteTitle,
  POLICIES,
  reportRows,
  templateSections,
  type Flag,
  type PlaceField,
} from "./placementModel";

export type MapOrder = "report" | "mtool";
export type MapFilter = "all" | "look";

/** The drag carries the note's id under this type, so only a note can be dropped on a field. */
export const NOTE_DRAG = "application/x-xbrl-note";

export function FlagStatus({ flag }: { flag: Flag }) {
  if (flag.kind === "not_placed")
    return <Status kind="failure">Not placed</Status>;
  if (flag.kind === "check") return <Status kind="check">Check</Status>;
  if (flag.kind === "confirmed")
    return <Status kind="finished">Confirmed</Status>;
  return null;
}

export const CHEVRON = (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M6 3.5 10.5 8 6 12.5" />
  </svg>
);

/** Drop handlers for a field: a note dragged over it marks it, and dropping moves the note there. */
export function useDrop(onDrop: (noteId: number) => void, enabled: boolean) {
  const [over, setOver] = useState(false);
  if (!enabled) return { over: false, props: {} };
  const carries = (e: DragEvent) =>
    Array.from(e.dataTransfer.types).includes(NOTE_DRAG);
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (!carries(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: DragEvent) => {
        setOver(false);
        const id = Number(e.dataTransfer.getData(NOTE_DRAG));
        if (!id) return;
        e.preventDefault();
        onDrop(id);
      },
    },
  };
}

export function dragProps(
  n: NoteSummary,
  can: boolean,
  onSelect: (id: number) => void,
) {
  if (!can) return {};
  return {
    draggable: true,
    onDragStart: (e: DragEvent) => {
      e.dataTransfer.setData(NOTE_DRAG, String(n.id));
      e.dataTransfer.effectAllowed = "move";
      onSelect(n.id);
    },
  };
}

/** A row a person picks with a click, or with Enter or Space once it has focus. */
export function pickKeys(pick: () => void) {
  return {
    role: "button",
    tabIndex: 0,
    onClick: pick,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      pick();
    },
  };
}

export function FieldName({
  n,
  byId,
}: {
  n: NoteSummary;
  byId: Map<string, PlaceField>;
}) {
  if (!n.field) return <span className="pf none">–</span>;
  const f = byId.get(n.field.node_uuid);
  const extra =
    f &&
    f.template !== "LIST_OF_NOTES" &&
    f.template !== POLICIES &&
    f.templateName !== f.short
      ? f.templateName
      : "";
  return (
    <span className="pf" title={f?.label ?? n.field.label}>
      {f?.short ?? n.field.label}
      {extra && <span className="meta">{` · ${extra}`}</span>}
    </span>
  );
}

export interface RowsProps {
  notes: NoteSummary[];
  fields: PlaceField[];
  byId: Map<string, PlaceField>;
  /** Each note's flag, by note id. */
  flags: Map<number, Flag>;
  /** Mandatory fields no note fills and no person left empty. */
  missing: PlaceField[];
  filter: MapFilter;
  selected: number | null;
  onSelect: (id: number) => void;
  can: boolean;
  /** Shown when no row is. */
  empty: string;
}

function MissingRows({ missing }: { missing: PlaceField[] }) {
  if (!missing.length) return null;
  return (
    <>
      <div className="prow phd">
        <span>Mandatory fields with no note</span>
        <span />
      </div>
      {missing.map((f) => (
        <div key={f.id} className="prow pmiss">
          <span />
          <span />
          <span className="pt meta">No note</span>
          <span className="pf" title={f.label}>
            {f.short}
            <span className="meta">{` · ${f.templateName}`}</span>
          </span>
          <span className="pst">
            <Status kind="check">Empty</Status>
          </span>
        </div>
      ))}
    </>
  );
}

export function ReportOrder({
  notes,
  flags,
  missing,
  byId,
  filter,
  selected,
  onSelect,
  can,
  empty,
}: RowsProps) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const flag = (n: NoteSummary) => flags.get(n.id)!;
  const noteRow = (n: NoteSummary, part = false) => (
    <div
      key={n.id}
      className={[
        "prow",
        "pnote",
        part ? "part" : "",
        selected === n.id ? "sel" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-current={selected === n.id ? "true" : undefined}
      {...pickKeys(() => onSelect(n.id))}
      {...dragProps(n, can, onSelect)}
    >
      <span />
      <span className="pno">{part ? "" : n.number}</span>
      <span className="pt" title={noteTitle(n)}>
        {noteTitle(n)}
      </span>
      <FieldName n={n} byId={byId} />
      <span className="pst">
        <FlagStatus flag={flag(n)} />
      </span>
    </div>
  );
  const out: ReactNode[] = [];
  for (const row of reportRows(notes)) {
    if (row.kind === "note") {
      if (filter === "all" || needsLook(flag(row.note)))
        out.push(noteRow(row.note));
      continue;
    }
    const looking = row.parts.filter((n) => needsLook(flag(n)));
    if (filter === "look" && !looking.length) continue;
    const loose = row.parts.some((n) => !n.field);
    const shown = filter === "look" || open.has(row.key);
    const templates = [
      ...new Set(
        row.parts
          .map((n) =>
            n.field ? byId.get(n.field.node_uuid)?.templateName : null,
          )
          .filter(Boolean),
      ),
    ];
    out.push(
      <div
        key={row.key}
        className={[
          "prow",
          "psplit",
          !shown && row.parts.some((n) => n.id === selected) ? "sel" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <button
          type="button"
          className={shown ? "pchev open" : "pchev"}
          aria-expanded={shown}
          aria-label={
            shown
              ? `Hide the parts of note ${row.number}`
              : `Show the parts of note ${row.number}`
          }
          onClick={() =>
            setOpen(
              (s) =>
                new Set(
                  s.has(row.key)
                    ? [...s].filter((k) => k !== row.key)
                    : [...s, row.key],
                ),
            )
          }
        >
          {CHEVRON}
        </button>
        <span className="pno">{row.number}</span>
        <span className="pt">{row.title}</span>
        <span className="pf meta">{`${row.parts.length} parts${templates.length === 1 && templates[0] ? ` · ${templates[0]}` : ""}`}</span>
        <span className="pst">
          {loose ? (
            <Status kind="failure">Not placed</Status>
          ) : looking.length ? (
            <Status kind="check">{`${looking.length} to check`}</Status>
          ) : null}
        </span>
      </div>,
    );
    if (shown)
      for (const n of filter === "look" ? looking : row.parts)
        out.push(noteRow(n, true));
  }
  return out.length || missing.length ? (
    <>
      {out}
      <MissingRows missing={missing} />
    </>
  ) : (
    <div className="empty">{empty}</div>
  );
}

export function Chip({
  n,
  flag,
  selected,
  onSelect,
  can,
}: {
  n: NoteSummary;
  flag: Flag;
  selected: boolean;
  onSelect: (id: number) => void;
  can: boolean;
}) {
  return (
    <span
      className={selected ? "pchip sel" : "pchip"}
      aria-current={selected ? "true" : undefined}
      {...pickKeys(() => onSelect(n.id))}
      {...dragProps(n, can, onSelect)}
    >
      <span className="pno">{n.number}</span>
      <span className="pt">{noteTitle(n)}</span>
      {flag.kind === "check" && <Status kind="check">Check</Status>}
    </span>
  );
}

export function FieldRow({
  field,
  children,
  onDrop,
  can,
}: {
  field: PlaceField;
  children: ReactNode;
  onDrop: (noteId: number) => void;
  can: boolean;
}) {
  const drop = useDrop(onDrop, can);
  return (
    <div
      className={drop.over ? "prow pfield over" : "prow pfield"}
      {...drop.props}
    >
      <span className="pl" title={field.label}>
        {field.short}
        {field.mandatory && <span className="meta">Mandatory</span>}
        {field.catchAll && !field.mandatory && (
          <span className="meta">Catch-all</span>
        )}
      </span>
      {children}
    </div>
  );
}

/** The notes in no field. A note dropped here is taken out of its field. */
function Loose({
  children,
  can,
  onDrop,
}: {
  children: ReactNode;
  can: boolean;
  onDrop: (noteId: number) => void;
}) {
  const drop = useDrop(onDrop, can);
  return (
    <div className={drop.over ? "ploose over" : "ploose"} {...drop.props}>
      <Status kind="failure">Not placed</Status>
      {children}
    </div>
  );
}

export function MtoolOrder({
  notes,
  fields,
  flags,
  missing,
  filter,
  selected,
  onSelect,
  can,
  empty,
  showEmpty,
  onMove,
}: RowsProps & {
  showEmpty: boolean;
  onMove: (noteId: number, field: PlaceField | null) => void;
}) {
  const unfilled = new Set(missing.map((f) => f.id));
  const chip = (n: NoteSummary) => (
    <Chip
      key={n.id}
      n={n}
      flag={flags.get(n.id)!}
      selected={selected === n.id}
      onSelect={onSelect}
      can={can}
    />
  );
  const loose = notes.filter((n) => !n.field);
  const out: ReactNode[] = [];
  if (loose.length) {
    out.push(
      <Loose key="loose" can={can} onDrop={(id) => onMove(id, null)}>
        <div className="pchips">{loose.map(chip)}</div>
      </Loose>,
    );
  }
  for (const s of templateSections(fields, notes, showEmpty)) {
    const rows =
      filter === "all"
        ? s.rows
        : s.rows.filter((r) =>
            r.notes.length
              ? r.notes.some((n) => needsLook(flags.get(n.id)!))
              : unfilled.has(r.field.id),
          );
    if (!rows.length) continue;
    out.push(
      <div key={`t-${s.templateId}`} className="prow phd">
        <span>{s.name}</span>
        <span className="meta">{`${s.used} of ${s.total} used`}</span>
      </div>,
    );
    for (const r of rows) {
      out.push(
        <FieldRow
          key={r.field.id}
          field={r.field}
          can={can}
          onDrop={(id) => onMove(id, r.field)}
        >
          {r.notes.length ? (
            <div className="pchips">
              {(filter === "all"
                ? r.notes
                : r.notes.filter((n) => needsLook(flags.get(n.id)!))
              ).map(chip)}
            </div>
          ) : unfilled.has(r.field.id) ? (
            <Status kind="check">Empty</Status>
          ) : (
            <span className="pf none">–</span>
          )}
        </FieldRow>,
      );
    }
  }
  return out.length ? <>{out}</> : <div className="empty">{empty}</div>;
}

/** Every note beside its mTool field, in report order or in mTool's order, with what needs a look. */
