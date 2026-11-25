import { useEffect, useState } from "react";
import { api } from "../api";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import "./PagePicture.css";

/** A page of the run's document, drawn upright by the server. In the side panel the page shows only once
 * its picture has loaded, so a run with no pictures leaves no empty frame; a page opened on its own (the
 * dialog) says quietly that there is none. */
export function PagePicture({ runId, page, titled = true }: { runId: number; page: number | null; titled?: boolean }) {
  const [state, setState] = useState<"loading" | "shown" | "missing">("loading");
  useEffect(() => setState("loading"), [runId, page]);
  if (page === null || (titled && state === "missing")) return null;
  return (
    <div className="pgwrap" hidden={titled && state === "loading" ? true : undefined}>
      {titled && (
        <div className="pgh">
          <span>Page {page}</span>
        </div>
      )}
      {state === "missing" ? (
        <p className="meta">No page picture for this run</p>
      ) : (
        <img className="page-picture" src={api.pageImage(runId, page)} alt={`Page ${page}`} onLoad={() => setState("shown")} onError={() => setState("missing")} />
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
