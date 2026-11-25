import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage, type Check, type FigurePlace, type RunStatus, type StatementCode, type User } from "../../api";
import { Button } from "../../components/Button";
import { QuestionCard } from "../../components/QuestionCard";
import { PageDialog } from "../../components/PagePicture";
import { Status } from "../../components/Status";
import { ActivityTab } from "./ActivityTab";
import { checkStatement, ChecksView } from "./ChecksView";
import { CompareView } from "./CompareView";
import { GuidanceView } from "./GuidanceView";
import { CommentsTab, liveComments } from "./CommentsTab";
import { NeedsYouTab, type OpenOptions } from "./NeedsYouTab";
import { noteGroups, NOT_PLACED } from "./noteList";
import type { NoteSelection } from "./noteModel";
import { NoteSide } from "./NoteSide";
import { NoteWork, type NoteView } from "./NoteWork";
import { PlacementMap } from "./PlacementMap";
import { emptyMandatory, flagsOf, needsLook, placeFields } from "./placementModel";
import { PlacementSide } from "./PlacementSide";
import { usePlacement } from "./usePlacement";
import { RunNav, type Section } from "./RunNav";
import { isReport, reportCount } from "./reportModel";
import { ReportSide } from "./ReportSide";
import { ReportWork } from "./ReportView";
import { useReports } from "./useReports";
import type { Layouts } from "../setup/setupModel";
import { changedCells, extractionFailed, isBusy, isExtracting, selectionFor, type Selection } from "./runModel";
import { SidePanel, type Tab } from "./SidePanel";
import { SourceTab } from "./SourceTab";
import { useSidePanel } from "../../components/Splitter";
import { StatementGrid, type Filter, type Order } from "./StatementGrid";
import { TracesDialog } from "./TracesDialog";
import { FillDialog } from "./FillDialog";
import { useNoteData } from "./useNoteData";
import { useRunData } from "./useRunData";
import "./RunPage.css";

const newClientId = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Sections that are not a statement. */
const OTHER_SECTIONS = new Set<Section>(["checks", "guidance", "compare", "notes", "placement"]);
const isStatement = (s: Section | null): s is StatementCode => s !== null && !isReport(s) && !OTHER_SECTIONS.has(s);

/** The run screen: the whole life of a run after setup, from extraction to review and correction. */
export function RunPage({ runId }: { runId: number; user: User }) {
  const split = useSidePanel("run-side", "--run-side-w", "--run-side-min-w");
  // Why the figure opened from Needs you or Checks waits for a person; shown in the Source tab.
  const [why, setWhy] = useState<string | null>(null);
  // The figure was opened from a list, not clicked: the grid marks it briefly so the eye finds it, and
  // gives it the keyboard once, unless the person is moving through Needs you. Each opening has its own id.
  const [arrival, setArrival] = useState<{ id: number; focus: boolean } | null>(null);
  // Counts every opening and is never reset, so no two openings share an id.
  const arrivals = useRef(0);
  const [section, setSection] = useState<Section | null>(null);
  const [order, setOrder] = useState<Order>("report");
  const [filter, setFilter] = useState<Filter>("all");
  const [selection, setSelection] = useState<Selection>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const [traces, setTraces] = useState(false);
  const [filling, setFilling] = useState(false);
  const [page, setPage] = useState<number | null>(null);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState("");
  const [askError, setAskError] = useState("");
  const [noteView, setNoteView] = useState<NoteView | null>(null);
  const [noteSel, setNoteSel] = useState<NoteSelection>(null);
  const [reportField, setReportField] = useState<string | null>(null);
  const [mapNote, setMapNote] = useState<number | null>(null);
  const [reportText, setReportText] = useState(false);
  const code = isStatement(section) ? section : null;
  const data = useRunData(runId, code, order);
  const { run, statements, statement, checks, needs, comments, rounds, report, events, question, questions } = data;
  const layouts = useMemo(
    () => Object.fromEntries((run?.statements ?? []).map((s) => [s.statement, s.layout])) as Layouts,
    [run?.statements],
  );
  const reports = useReports(runId, events);
  const notes = useNoteData(runId, noteView?.kind === "note" ? noteView.id : null, events, data.refresh, `${run?.standard ?? ""}|${run?.level ?? ""}`);
  const mapFields = useMemo(() => placeFields(notes.fields), [notes.fields]);
  // The map's flags are worked out once per notes list, not on every poll of the run.
  const mapFlags = useMemo(() => flagsOf(notes.notes, mapFields), [notes.notes, mapFields]);
  const mapMissing = useMemo(() => {
    const leftEmpty = new Set(notes.reports.filter((r) => r.kind === "missing_mandatory_field" && r.status === "settled" && r.node_uuid).map((r) => r.node_uuid!));
    return emptyMandatory(mapFields, notes.notes, leftEmpty);
  }, [mapFields, notes.notes, notes.reports]);
  const mapLook = [...mapFlags.values()].filter(needsLook).length + mapMissing.length;
  const placement = usePlacement(runId, notes, data.refresh);

  const busy = run !== null && isBusy(run);
  const extracting = run !== null && isExtracting(run);
  const lastRound = rounds[rounds.length - 1];
  const roundWorking = run?.status === "correcting" && lastRound !== undefined && (lastRound.status === "sent" || lastRound.status === "working");
  const changed = changedCells(report);

  // Open the first statement, and the tab that fits the run's state.
  useEffect(() => {
    if (section === null && statements.length) setSection(statements[0]);
  }, [section, statements]);
  // A stage or round that starts shows Activity; one that ends shows what it left.
  const before = useRef<RunStatus | null>(null);
  useEffect(() => {
    if (!run) return;
    const was = before.current;
    before.current = run.status;
    if (was === null) setTab((t) => t ?? (isBusy(run) ? "activity" : "needs"));
    else if (was === run.status) return;
    else if (isBusy(run)) setTab("activity");
    else if (was === "correcting") setTab("comments");
    else if (was === "ready" || was === "extracting") setTab("needs");
  }, [run]);

  function openSection(next: Section) {
    setSection(next);
    setSelection(null);
    setWhy(null);
    setArrival(null);
    setReportField(null);
    setReportText(false);
    if (!busy && next !== "guidance" && next !== "compare") setTab(next === "checks" ? "needs" : "source");
  }

  function showNote(view: NoteView) {
    setSection("notes");
    setNoteView(view);
    setNoteSel(null);
    if (!busy) setTab("source");
  }

  function openMap() {
    setSection("placement");
    if (!busy) setTab("source");
  }

  function pickOnMap(noteId: number) {
    setMapNote(noteId);
    if (!busy) setTab("source");
  }

  function selectNote(next: NoteSelection) {
    setNoteSel(next);
    if (!busy) setTab("source");
  }

  function select(next: Selection) {
    setWhy(null);
    setArrival(null);
    setSelection(next);
    if (!busy) setTab("source");
  }

  /** Opens a figure from a list. A failed check's line is a template total, which only the template order
   * shows, so it opens there with the check's explanation; everything else opens where the report prints it.
   * `stay` keeps the side panel on Needs you, for moving through that list with the keyboard. */
  function open(place: FigurePlace, { failure, stay = false, comments = false }: OpenOptions = {}) {
    setWhy(failure ?? null);
    reach(place, failure, stay);
    if (stay) setTab("needs");
    else if (comments) setTab("comments");
  }

  /** Escape in the grid: nothing selected, and the side panel back on what needs the person. */
  function clear() {
    setSelection(null);
    setWhy(null);
    setArrival(null);
    setTab("needs");
  }

  function reach(place: FigurePlace, failure?: string, stay = false) {
    if (place.note_id) return showNote({ kind: "note", id: place.note_id });
    if (place.report_id) return showNote({ kind: "missing", id: place.report_id });
    // A comment on the notes as a whole opens the notes list at its first entry.
    if (place.statement === "NOTES") return openNotes();
    const fallback = statements[0] ?? "SOFP";
    const target = selectionFor(place, fallback);
    const where = (place.statement ?? fallback) as StatementCode;
    const into = statements.includes(where) ? where : fallback;
    // Moving through Needs you keeps the order on screen while the line is in it, so the grid does not
    // flip between orders and reload at every step.
    const shown = stay && statement?.statement === into && statement.rows.some((r) => r.concept_uuid === place.concept_uuid);
    setSection(into);
    if (!shown) setOrder(failure !== undefined ? "template" : "report");
    setFilter("all");
    setSelection(target);
    arrivals.current += 1;
    setArrival({ id: arrivals.current, focus: !stay });
    setTab("source");
  }

  /** The notes list at its first entry, or the first template's overview when it has none. */
  function openNotes() {
    const first = groups[0];
    if (first) notesNav.onTemplate(first);
  }

  function openCheck(check: Check) {
    const fallback = statements[0] ?? "SOFP";
    open({ statement: checkStatement(check, fallback), concept_uuid: check.target_concept_uuid, period: check.period, entity_scope: check.entity_scope }, { failure: check.message });
  }

  async function act(work: () => Promise<unknown>) {
    setActing(true);
    setActionError("");
    try {
      await work();
      await data.refresh();
    } catch (failure) {
      setActionError(errorMessage(failure));
    } finally {
      setActing(false);
    }
  }

  if (!run) {
    return (
      <>
        <div className="page-header">
          <h1>{data.error ? "Run not opened" : "Loading run"}</h1>
        </div>
        {data.error && (
          <p className="error" role="alert">
            {data.error}
          </p>
        )}
      </>
    );
  }

  const live = liveComments(comments);
  const open_ = live.filter((c) => c.status === "open").length;
  // Accept all takes exactly what the server says it would accept now.
  const answered = data.acceptAll.comment_ids.length;
  const failed = extractionFailed(run);
  const extractStage = [...(run.stages ?? [])].reverse().find((stage) => stage.name === "extract");
  // A person stopped extraction: the run is "stopped" (no figures) or in review with its stage stopped.
  const stopped = run.status === "stopped" || (run.status === "in_review" && extractStage?.status === "stopped");
  const retry = () => act(() => api.retryExtraction(runId));
  // The figures finished but the notes or reports agent failed or was stopped: the server can start it again.
  const agentStopped = run.status === "in_review" && (run.stages ?? []).some((s) => (s.name === "notes" || s.name === "reports") && (s.status === "failed" || s.status === "stopped"));

  // Extraction stopped to ask a scope question: the card waits above the grid.
  const asking = question !== null && question.status === "open";
  async function answer(reply: { choice: number } | { text: string }) {
    if (!question) return;
    setActing(true);
    setAskError("");
    try {
      await api.answerQuestion(runId, question.id, reply);
      await data.refresh();
    } catch (failure) {
      setAskError(errorMessage(failure));
    } finally {
      setActing(false);
    }
  }

  let action = null;
  if (failed || run.status === "stopped") {
    action = (
      <Button variant="primary" disabled={acting} onClick={retry}>
        Try again
      </Button>
    );
  } else if (run.status === "ready" || run.status === "extracting") {
    action = (
      <Button disabled={acting} onClick={() => act(() => api.stopExtraction(runId))}>
        Stop
      </Button>
    );
  } else if (roundWorking) {
    action = (
      <Button disabled={acting || lastRound.stop_requested} onClick={() => act(() => api.stopRound(runId, lastRound.id))}>
        Stop
      </Button>
    );
  } else if (!busy && open_ > 0) {
    const id = newClientId();
    action = (
      <Button variant="primary" disabled={acting} onClick={() => act(() => api.sendRound(runId, id))}>
        {`Send ${open_} comment${open_ === 1 ? "" : "s"}`}
      </Button>
    );
  } else if (!busy && answered > 0) {
    action = (
      <Button variant="primary" disabled={acting} onClick={() => act(() => api.acceptAll(runId))}>
        Accept all
      </Button>
    );
  } else if (!busy && run.status !== "setup" && run.status !== "reading") {
    action = (
      <Button variant="primary" onClick={() => setFilling(true)}>
        Prepare mTool file
      </Button>
    );
  }

  const counts: Partial<Record<Section, number>> = {};
  if (!extracting) {
    for (const item of needs?.items ?? []) {
      if (item.kind !== "alike" && item.statement && item.statement !== "NOTES") counts[item.statement] = (counts[item.statement] ?? 0) + 1;
    }
    for (const c of live) if (c.target.statement && c.target.statement !== "NOTES") counts[c.target.statement] = (counts[c.target.statement] ?? 0) + 1;
    counts.checks = checks.filter((c) => c.status === "failed").length;
    for (const r of reports.data?.reports ?? []) counts[r.report] = reportCount(r);
  }
  // The notes list, by template; the open note's template is the one its field belongs to.
  const groups = noteGroups(notes.fields, notes.notes, notes.reports, comments);
  const notesStage = [...(run.stages ?? [])].reverse().find((stage) => stage.name === "notes");
  const notesWorking = notesStage !== undefined && !["done", "failed", "stopped"].includes(notesStage.status);
  const openSummary = noteView?.kind === "note" ? notes.notes.find((n) => n.id === noteView.id) : undefined;
  const openTemplate =
    section !== "notes" || !noteView
      ? null
      : noteView.kind === "template"
        ? noteView.templateId
        : noteView.kind === "missing"
          ? notes.reports.find((r) => r.id === noteView.id)?.template_id ?? null
          : openSummary
            ? (openSummary.field ? openSummary.template_id : NOT_PLACED)
            : null;
  const notesNav = {
    groups: extracting ? groups.map((g) => ({ ...g, count: 0, items: g.items.map((i) => ({ ...i, count: 0 })) })) : groups,
    template: openTemplate,
    open: section === "notes" && noteView && noteView.kind !== "template" ? noteView : null,
    working: notesWorking,
    onTemplate: (g: (typeof groups)[number]) => {
      const first = g.items[0];
      showNote(first ? { kind: first.kind, id: first.id } : { kind: "template", templateId: g.templateId, name: g.name });
    },
    onItem: (item: (typeof groups)[number]["items"][number]) => showNote({ kind: item.kind, id: item.id }),
    map: { on: section === "placement", count: extracting ? 0 : mapLook, onOpen: openMap },
  };

  const openReport = isReport(section) ? reports.data?.reports.find((r) => r.report === section) ?? null : null;
  const openField = openReport?.fields.find((f) => f.field_id === reportField) ?? null;
  const reportsStage = reports.data?.stage;
  const reportsWorking = reportsStage != null && !["done", "failed", "stopped"].includes(reportsStage.status);

  // This version extracts the balance sheet only, the first statement.
  const working: Section | null = run.working_on ?? null;
  const shownTab = tab ?? "needs";

  let body = null;
  // On the Checks page the failed checks are listed already, so Needs you keeps only the rest.
  const sideNeeds = section === "checks" && needs ? { ...needs, items: needs.items.filter((i) => i.kind !== "failed_check") } : needs;
  if (shownTab === "needs") {
    body = <NeedsYouTab needs={sideNeeds} extracting={extracting} busy={busy} onOpen={open} onAcceptAlike={() => act(() => api.acceptAlike(runId))} others={(sideNeeds?.items.length ?? 0) < (needs?.items.length ?? 0)} onClear={clear} />;
  } else if (shownTab === "comments") {
    body = <CommentsTab runId={runId} comments={comments} rounds={rounds} report={report} working={roundWorking} onOpen={open} onChanged={data.refresh} layouts={layouts} />;
  } else if (shownTab === "activity") {
    body = <ActivityTab events={events} busy={busy} waiting={asking} questions={questions} onPage={setPage} />;
  } else if (isReport(section)) {
    body = <ReportSide runId={runId} field={openField} busy={busy} onOpenText={() => setReportText(true)} onChanged={async () => void (await Promise.all([reports.reload(), data.refresh()]))} />;
  } else if (section === "placement") {
    body = <PlacementSide note={notes.notes.find((n) => n.id === mapNote) ?? null} notes={notes.notes} fields={mapFields} placement={placement} busy={busy} working={notesWorking} onOpenNote={(id) => showNote({ kind: "note", id })} />;
  } else if (section === "notes" && noteView) {
    body = <NoteSide runId={runId} data={notes} view={noteView} sel={noteSel} onSelect={selectNote} busy={busy} working={notesWorking} onChanged={data.refresh} onOpenNote={(id) => showNote({ kind: "note", id })} />;
  } else if (statement && code) {
    body = <SourceTab runId={runId} statement={statement} selection={selection} why={why} comments={comments} busy={busy} changed={changed} onSelect={select} onChanged={data.refresh} />;
  }

  return (
    <>
      <RunNav statements={statements} layouts={layouts} section={section} counts={counts} working={working} onSection={openSection} notes={notesNav} reports={reports.data?.reports ?? []} reportsWorking={reportsWorking} />
      <div className="page-header">
        <h1>{run.company ?? run.filename ?? ""}</h1>
        <span className="spacer" />
        {actionError && (
          <span className="error" role="alert">
            {actionError}
          </span>
        )}
        <Button variant="quiet" onClick={() => setTraces(true)}>
          Download traces
        </Button>
        {agentStopped && !busy && (
          <Button disabled={acting} onClick={retry}>
            Try again
          </Button>
        )}
        {action}
      </div>
      <div className="run-cols" ref={split.ref} style={split.style}>
        {split.splitter}
        <section className="panel work">
          {asking && question && (
            <div className="ask">
              <QuestionCard
                key={question.id}
                inset
                disabled={acting}
                question={question.question}
                evidence={question.evidence.map((e) => ({ text: e.text, pages: [e.page] }))}
                choices={question.choices}
                onChoose={(choice) => answer({ choice })}
                onOther={(text) => answer({ text })}
                onPage={setPage}
              />
              {askError && (
                <p className="error" role="alert">
                  {askError}
                </p>
              )}
            </div>
          )}
          {failed && (
            <div className="work-failure" role="alert">
              <Status kind="failure">Extraction failed</Status>
              <p>{run.failure?.sentence ?? extractStage?.error ?? "Extraction stopped."}</p>
            </div>
          )}
          {stopped && (
            <div className="work-failure">
              <div className="bar">
                <Status kind="neutral">Extraction stopped</Status>
                {run.status === "in_review" && (
                  <Button size="small" disabled={acting} onClick={retry}>
                    Try again
                  </Button>
                )}
              </div>
              {extractStage?.error && <p>{extractStage.error}</p>}
            </div>
          )}
          {data.error && (
            <p className="work-failure error" role="alert">
              {data.error}
            </p>
          )}
          {notes.error && !(section === "notes" && noteView?.kind === "note" && notes.note?.id === noteView.id) && (
            <p className="work-failure error" role="alert">
              {notes.error}
            </p>
          )}
          {isReport(section) ? (
            <ReportWork
              report={openReport}
              field={openField}
              text={reportText}
              error={reports.error}
              stage={reports.data?.stage ?? null}
              onBack={() => setReportText(false)}
              onSelect={(id) => {
                setReportField(id);
                if (!busy) setTab("source");
              }}
            />
          ) : section === "placement" ? (
            <PlacementMap notes={notes.notes} fields={mapFields} flags={mapFlags} missing={mapMissing} selected={mapNote} onSelect={pickOnMap} placement={placement} busy={busy} working={notesWorking} />
          ) : section === "notes" && noteView ? (
            <NoteWork
              runId={runId}
              data={notes}
              view={noteView}
              sel={noteSel}
              onSelect={selectNote}
              busy={busy}
              working={notesWorking}
              comments={comments}
              onOpenNote={(id) => showNote({ kind: "note", id })}
            />
          ) : section === "guidance" ? (
            <GuidanceView runId={runId} />
          ) : section === "compare" ? (
            <CompareView runId={runId} layouts={layouts} onOpen={open} />
          ) : section === "checks" ? (
            <ChecksView checks={checks} group={run.level === "Group"} busy={extracting} onOpen={openCheck} />
          ) : (
            <StatementGrid
              statement={statement}
              order={order}
              filter={filter}
              onOrder={setOrder}
              onFilter={setFilter}
              comments={comments}
              changed={changed}
              selection={selection}
              arrival={arrival}
              onSelect={select}
              onClear={clear}
              busy={busy}
            />
          )}
        </section>
        <SidePanel tab={shownTab} counts={{ needs: extracting ? 0 : sideNeeds?.items.length ?? 0, comments: live.length }} onTab={setTab}>
          {body}
        </SidePanel>
      </div>
      <TracesDialog runId={runId} open={traces} onClose={() => setTraces(false)} />
      <FillDialog runId={runId} open={filling} onClose={() => setFilling(false)} />
      <PageDialog runId={runId} page={page} onClose={() => setPage(null)} />
    </>
  );
}
