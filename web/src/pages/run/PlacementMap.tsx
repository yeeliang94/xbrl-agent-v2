import { useState } from "react";
import type { NoteSummary } from "../../api";
import { Button } from "../../components/Button";
import { Segmented } from "../../components/Segmented";
import { Switch } from "../../components/Switch";
import { type Flag, type PlaceField } from "./placementModel";
import {
  MtoolOrder,
  ReportOrder,
  type MapFilter,
  type MapOrder,
  type RowsProps,
} from "./PlacementRows";
import { canUndo, type Placement } from "./usePlacement";
import "./PlacementMap.css";

export interface PlacementMapProps {
  notes: NoteSummary[];
  fields: PlaceField[];
  /** Each note's flag, by note id. */
  flags: Map<number, Flag>;
  /** Mandatory fields no note fills and no person left empty. */
  missing: PlaceField[];
  /** How many notes and fields need a look. */
  look: number;
  selected: number | null;
  onSelect: (noteId: number) => void;
  placement: Placement;
  /** An agent works on the run: nothing can move. */
  busy: boolean;
  /** The notes agent is placing notes. */
  working: boolean;
}

export function PlacementMap({
  notes,
  fields,
  flags,
  missing,
  look,
  selected,
  onSelect,
  placement,
  busy,
  working,
}: PlacementMapProps) {
  const [order, setOrder] = useState<MapOrder>("report");
  const [filter, setFilter] = useState<MapFilter>("all");
  const [showEmpty, setShowEmpty] = useState(false);
  const byId = new Map(fields.map((f) => [f.id, f]));
  const can = !busy && !working && !placement.saving;
  const onMove = (noteId: number, field: PlaceField | null) => {
    const n = notes.find((x) => x.id === noteId);
    if (n) void placement.move(n, field);
  };
  const empty =
    working && !notes.length
      ? "Notes appear here as the agent places them"
      : !notes.length
        ? "No notes in this run"
        : "Nothing needs a look";
  const props: RowsProps = {
    notes,
    fields,
    byId,
    flags,
    missing,
    filter,
    selected,
    onSelect,
    can,
    empty,
  };

  return (
    <>
      <div className="wh note-head">
        <h2>Placement map</h2>
        <div className="wh-tools">
          <Segmented
            label="Order"
            options={[
              { value: "report", label: "Report order" },
              { value: "mtool", label: "mTool order" },
            ]}
            value={order}
            onChange={setOrder}
          />
          <Segmented
            label="Show"
            options={[
              { value: "all", label: `All ${notes.length}` },
              { value: "look", label: `Needs a look ${look}` },
            ]}
            value={filter}
            onChange={setFilter}
          />
        </div>
      </div>
      {(placement.done || placement.error) && (
        <div className="pdone" role={placement.error ? "alert" : "status"}>
          <span className={placement.error ? "error" : undefined}>
            {placement.error || placement.done?.text}
          </span>
          {!placement.error && canUndo(placement.done, notes) && (
            <Button
              size="small"
              variant="quiet"
              disabled={!can}
              onClick={() => void placement.undo()}
            >
              Undo
            </Button>
          )}
          <Button size="small" variant="quiet" onClick={placement.dismiss}>
            Dismiss
          </Button>
        </div>
      )}
      {order === "mtool" && filter === "all" && (
        <div className="pbar">
          <label htmlFor="pmap-empty">Empty fields</label>
          <Switch
            id="pmap-empty"
            label="Empty fields"
            checked={showEmpty}
            onChange={setShowEmpty}
          />
        </div>
      )}
      <div className={`wb pmap ${order}`}>
        {order === "report" && notes.length > 0 && (
          <div className="prow pth">
            <span />
            <span />
            <span>Note in the report</span>
            <span>mTool field</span>
            <span />
          </div>
        )}
        {order === "report" ? (
          <ReportOrder {...props} />
        ) : (
          <MtoolOrder {...props} showEmpty={showEmpty} onMove={onMove} />
        )}
      </div>
    </>
  );
}
