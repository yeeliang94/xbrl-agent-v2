import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Comment, type Guidance, type GuidanceLineKept } from "../../api";
import { Button } from "../../components/Button";

/**
 * A line of company guidance the Reviewer proposed from a Company-scoped
 * correction. Only a person adds it: "Add to guidance" or "This run only".
 * Once added, Undo puts back the version before it.
 */
export function ProposalCard({ runId, comment, kept, onChanged }: { runId: number; comment: Comment; kept?: GuidanceLineKept; onChanged: () => Promise<void> }) {
  const [company, setCompany] = useState<{ id: number; guidance: Guidance } | null>(null);
  const [error, setError] = useState("");
  // The company guidance could not be read: the card still shows, with the sentence.
  const [unread, setUnread] = useState(false);
  const [busy, setBusy] = useState(false);
  const line = comment.proposed_guidance ?? "";

  const load = useCallback(async () => {
    const g = await api.runGuidance(runId);
    setCompany(g.company_id !== null && g.company ? { id: g.company_id, guidance: g.company } : null);
  }, [runId]);

  useEffect(() => {
    load().then(
      () => setUnread(false),
      (failure) => {
        setUnread(true);
        setError(errorMessage(failure));
      },
    );
  }, [load]);

  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await load();
      setUnread(false);
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  if (!line || comment.guidance_status === "dismissed" || (!company && !unread)) return null;
  const added = company ? company.guidance.lines.includes(line) : comment.guidance_status === "added";
  // The change was undone after its line was added: the line stays until a person takes it out.
  const undone = comment.status === "undone";
  if (undone && !added) return null;
  const addedIn = kept?.version ?? comment.guidance_version;
  // Undo only while the version that added it is still the latest.
  const canUndo = company !== null && added && addedIn != null && company.guidance.version === addedIn;
  const failure = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );

  if (added) {
    return (
      <div className="cm">
        <div className="dh">
          <span>{undone ? "This change was undone, but its line is still in the company's guidance" : "Added to guidance for this company"}</span>
          {canUndo && (
            <Button
              variant="quiet"
              size="small"
              disabled={busy}
              onClick={() => company && act(() => api.restoreCompanyGuidance(company.id, addedIn! - 1, company.guidance.version))}
            >
              {undone ? "Undo guidance line" : "Undo"}
            </Button>
          )}
        </div>
        {failure}
      </div>
    );
  }
  return (
    <div className="cm">
      <h3>Add to guidance for this company?</h3>
      <p>{line}</p>
      <div className="bar">
        {failure}
        <span className="spacer" />
        <Button variant="quiet" size="small" disabled={busy} onClick={() => act(() => api.dismissProposedGuidance(runId, comment.id))}>
          This run only
        </Button>
        <Button size="small" disabled={busy} onClick={() => act(() => api.addProposedGuidance(runId, comment.id, company?.guidance.version))}>
          Add to guidance
        </Button>
      </div>
    </div>
  );
}
