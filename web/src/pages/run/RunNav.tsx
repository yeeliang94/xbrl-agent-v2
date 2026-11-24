import { useContext } from "react";
import { createPortal } from "react-dom";
import type { ReportCode, StatementCode } from "../../api";
import { NavSlot } from "../../components/AppShell";
import { Count } from "../../components/Count";
import { Spinner } from "../../components/Spinner";
import { statementName, type Layouts } from "../setup/setupModel";
import type { NoteGroup, NoteItem } from "./noteList";

export type Section = StatementCode | "checks" | "guidance" | "compare" | "notes" | "placement" | ReportCode;

export interface ReportLink {
  report: ReportCode;
  name: string;
}

export interface NotesNav {
  groups: NoteGroup[];
  /** The open template, and the note or missing field open in it. */
  template: string | null;
  open: { kind: NoteItem["kind"]; id: number } | null;
  /** The notes agent is placing notes: each template shows a spinner. */
  working: boolean;
  onTemplate: (group: NoteGroup) => void;
  onItem: (item: NoteItem) => void;
  /** The placement map: open, and how many notes need a look there. */
  map: { on: boolean; count: number; onOpen: () => void };
}

export interface RunNavProps {
  statements: StatementCode[];
  /** Each statement's layout, so a retained earnings statement is named as one. */
  layouts?: Layouts;
  section: Section | null;
  counts: Partial<Record<Section, number>>;
  /** The statement the agent is working on, marked with a spinner. */
  working: Section | null;
  onSection: (section: Section) => void;
  notes?: NotesNav;
  /** The three reports, once the run has them; `reportsWorking` while the reports agent fills them. */
  reports?: ReportLink[];
  reportsWorking?: boolean;
}

/** Notes by template. An open template with more than one note lists its notes, split parts and missing fields under it. */
function NotesLinks({ notes }: { notes: NotesNav }) {
  return (
    <>
      <div className="nav-group">Notes</div>
      <button type="button" className={notes.map.on ? "nav-link on" : "nav-link"} aria-current={notes.map.on ? "page" : undefined} onClick={notes.map.onOpen}>
        <span>Placement map</span>
        {notes.working ? <Spinner /> : <Count value={notes.map.count} />}
      </button>
      {notes.groups.map((g) => {
        const open = notes.template === g.templateId;
        const multi = g.items.length > 1;
        const on = open && !multi;
        return (
          <div key={g.templateId || "not-placed"} className="nav-tree">
            <button type="button" className={on ? "nav-link on" : "nav-link"} title={g.name} aria-current={on ? "page" : undefined} aria-expanded={multi ? open : undefined} onClick={() => notes.onTemplate(g)}>
              <span>{g.name}</span>
              {notes.working ? <Spinner /> : open && multi ? null : <Count value={g.count} />}
            </button>
            {open &&
              multi &&
              g.items.map((item) => {
                const here = notes.open?.kind === item.kind && notes.open.id === item.id;
                return (
                  <button key={`${item.kind}-${item.id}`} type="button" className={here ? "nav-link sub on" : "nav-link sub"} title={item.name} aria-current={here ? "page" : undefined} onClick={() => notes.onItem(item)}>
                    {item.kind === "note" && item.split ? (
                      <>
                        <span className="visually-hidden">{item.name}</span>
                        <span className="nav-split" aria-hidden="true">
                          <span>{item.split.title}</span>
                          <span>{`, part ${item.split.part}`}</span>
                        </span>
                      </>
                    ) : (
                      <span>{item.name}</span>
                    )}
                    {!notes.working && <Count value={item.count} />}
                  </button>
                );
              })}
          </div>
        );
      })}
    </>
  );
}

/** The run's statements, Checks and Guidance, in the black sidebar under Runs and Settings. */
export function RunNav({ statements, layouts, section, counts, working, onSection, notes, reports = [], reportsWorking = false }: RunNavProps) {
  const slot = useContext(NavSlot);
  if (!slot) return null;
  const link = (key: Section, label: string, spin = working === key) => (
    <button key={key} type="button" className={section === key ? "nav-link on" : "nav-link"} title={label} aria-current={section === key ? "page" : undefined} onClick={() => onSection(key)}>
      <span>{label}</span>
      {spin ? <Spinner /> : <Count value={counts[key] ?? 0} />}
    </button>
  );
  return createPortal(
    <>
      <div className="nav-group">Statements</div>
      {statements.map((code) => link(code, statementName(code, layouts?.[code])))}
      {link("checks", "Checks")}
      {link("guidance", "Guidance")}
      {link("compare", "Compare")}
      {reports.length > 0 && <div className="nav-group">Reports</div>}
      {reports.map((r) => link(r.report, r.name, reportsWorking))}
      {notes && notes.groups.length > 0 && <NotesLinks notes={notes} />}
    </>,
    slot,
  );
}
