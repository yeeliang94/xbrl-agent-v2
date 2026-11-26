import { useEffect, useState } from "react";
import { api, type SourceKind } from "../api";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import "./PagePicture.css";

/** The line above a reading-copy page: its numbers are its own (go-live plan C6). */
export function copyLine(kind: SourceKind | undefined): string {
  if (kind === "word") return "Reading copy made from the Word file. Page numbers differ from the printed report.";
  if (kind === "excel") return "Reading copy made from the Excel workbook. Page numbers are its own.";
  return "";
}

/** A page of the run's document, drawn upright by the server. In the side panel the page shows only once
 * its picture has loaded, so a run with no pictures leaves no empty frame; a page opened on its own (the
 * dialog) says quietly that there is none. A page of a reading copy (`kind` word or excel) says so. */
export function PagePicture({ runId, page, titled = true, kind }: { runId: number; page: number | null; titled?: boolean; kind?: SourceKind }) {
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
      {copyLine(kind) && <p className="copy">{copyLine(kind)}</p>}
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
