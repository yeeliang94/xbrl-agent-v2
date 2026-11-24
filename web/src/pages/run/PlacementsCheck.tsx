import { useEffect, useState } from "react";
import { api, errorMessage, type Fill, type Placement } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Segmented } from "../../components/Segmented";
import { Status } from "../../components/Status";
import { Table } from "../../components/Table";

type Choice = "use" | "skip";
const CHOICES: { value: Choice; label: string }[] = [
  { value: "use", label: "Use" },
  { value: "skip", label: "Skip" },
];

/**
 * "Check placements" (prototypes/fill-placements-prototype.html): each figure the fill could not place,
 * the cell proposed for it in words with its evidence, and Use or Skip. Save keeps the used places for this
 * template and fills it again; nothing is saved until then.
 */
export function PlacementsCheck({
  runId,
  fill,
  open,
  onCancel,
  onFilled,
}: {
  runId: number;
  fill: Fill;
  open: boolean;
  onCancel: () => void;
  onFilled: (next: Fill) => void;
}) {
  const [places, setPlaces] = useState<Placement[] | null>(null);
  const [choice, setChoice] = useState<Record<number, Choice>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let gone = false;
    api.placements(runId, fill.id).then(
      (found) => !gone && setPlaces(found.filter((p) => p.status === "open")),
      (failure) => !gone && setError(errorMessage(failure)),
    );
    return () => {
      gone = true;
    };
  }, [runId, fill.id]);

  async function save() {
    if (!places) return;
    setSaving(true);
    setError("");
    try {
      const use = places
        .filter((p) => (choice[p.id] ?? "use") === "use")
        .map((p) => p.id);
      const next = await api.usePlacements(runId, fill.id, use);
      // With nothing used the fill stands as it was: read it again, with its receipt.
      onFilled(next.id === fill.id ? await api.fill(runId, fill.id) : next);
    } catch (failure) {
      setError(errorMessage(failure));
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      wide
      title="Check placements"
      onClose={onCancel}
      actions={
        <>
          <Button variant="quiet" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={saving || !places?.length}
            onClick={save}
          >
            Save and fill again
          </Button>
        </>
      }
    >
      {places === null ? (
        error ? null : (
          <Status kind="working">Loading</Status>
        )
      ) : places.length === 0 ? (
        <div className="empty">No places to check</div>
      ) : (
        <Table
          columns={[
            {
              key: "figure",
              header: "Figure",
              render: (p: Placement) => p.figure,
            },
            {
              key: "place",
              header: "Place in template",
              render: (p: Placement) => (
                <div className="place">
                  <div>{p.place}</div>
                  <div className="meta">{p.evidence}</div>
                </div>
              ),
            },
            {
              key: "choice",
              header: "",
              align: "right",
              render: (p: Placement) => (
                <Segmented
                  label={`Use or skip ${p.figure}`}
                  options={CHOICES}
                  value={choice[p.id] ?? "use"}
                  onChange={(v) => setChoice((c) => ({ ...c, [p.id]: v }))}
                />
              ),
            },
          ]}
          rows={places}
          rowKey={(p) => String(p.id)}
        />
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
