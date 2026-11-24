import { useEffect, useState } from "react";
import { api } from "../api";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import "./PagePicture.css";

/** A page of the run's document, drawn upright by the server. A run with no document says so quietly. */
export function PagePicture({ runId, page, titled = true }: { runId: number; page: number | null; titled?: boolean }) {
  const [missing, setMissing] = useState(false);
  useEffect(() => setMissing(false), [runId, page]);
  if (page === null) return null;
  return (
    <div className="pgwrap">
      {titled && (
        <div className="pgh">
          <span>Page {page}</span>
        </div>
      )}
      {missing ? (
        <p className="meta">No page picture for this run</p>
      ) : (
        <img className="page-picture" src={api.pageImage(runId, page)} alt={`Page ${page}`} onError={() => setMissing(true)} />
      )}
    </div>
  );
}

/** A page opened from a link: an evidence line or an activity step. */
export function PageDialog({ runId, page, onClose }: { runId: number; page: number | null; onClose: () => void }) {
  return (
    <Dialog open={page !== null} title={`Page ${page ?? ""}`} wide onClose={onClose} actions={<Button onClick={onClose}>Close</Button>}>
      <PagePicture runId={runId} page={page} titled={false} />
    </Dialog>
  );
}
