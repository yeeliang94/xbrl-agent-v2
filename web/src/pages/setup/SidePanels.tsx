import { useState } from "react";
import { api, type MapNote } from "../../api";
import { Button } from "../../components/Button";
import { Icon, IconButton } from "../../components/IconButton";
import { Panel } from "../../components/Panel";
import { Segmented } from "../../components/Segmented";
import { Table, type Column } from "../../components/Table";
import { TextInput } from "../../components/TextInput";
import { Unsure } from "./Unsure";
import "../../components/PagePicture.css";
import { addNote, pagesText, parsePages, parseStatementPages, statementName, type StatementRow } from "./setupModel";

export function SourcePanel() {
  return (
    <Panel title="Source">
      <p className="meta">Choose a statement to see the page it was found on and why.</p>
    </Panel>
  );
}

/** A statement's page picture, drawn upright by the server, and the Reader's reason.
 * "Other page" lets the person set the statement's pages by number. */
export function StatementPanel({ runId, row, pageCount, onPages }: { runId: number; row: StatementRow; pageCount: number; onPages: (pages: number[]) => void }) {
  const [shown, setShown] = useState(row.pages[0] ?? null);
  const [editing, setEditing] = useState(false);
  const [typed, setTyped] = useState("");
  const page = shown !== null && row.pages.includes(shown) ? shown : row.pages[0] ?? null;
  const name = statementName(row.statement, row.layout);
  const pages = parseStatementPages(typed, pageCount);

  function setPages() {
    if (!pages) return;
    onPages(pages);
    setShown(pages[0]);
    setEditing(false);
    setTyped("");
  }

  return (
    <Panel className="sec">
      <div className="line">
        <h2>{name}</h2>
        <span className="meta mono">{page === null ? "Not printed" : `Page ${page} of ${pageCount}`}</span>
      </div>
      <p>{row.reason}</p>
      {row.pages.length > 1 && (
        <div>
          <Segmented
            label={`${name} pages`}
            options={row.pages.map((p) => ({ value: String(p), label: `Page ${p}` }))}
            value={String(page)}
            onChange={(v) => setShown(Number(v))}
          />
        </div>
      )}
      {page !== null && (
        <div className="pgwrap">
          <img className="page-picture" src={api.pageImage(runId, page)} alt={`${name}, page ${page}`} />
        </div>
      )}
      {editing ? (
        <div className="note-add">
          <TextInput
            aria-label={`${name} pages`}
            placeholder={`Pages, 1 to ${pageCount}`}
            value={typed}
            autoFocus
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setPages()}
          />
          <Button variant="quiet" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          <Button disabled={!pages} onClick={setPages}>
            Set
          </Button>
        </div>
      ) : (
        <div className="bar">
          <Button size="small" onClick={() => setEditing(true)}>
            Other page
          </Button>
        </div>
      )}
    </Panel>
  );
}

/** The notes list the person may edit: remove a note, or add one (a number already listed is replaced). */
export function NotesPanel({ notes, points, pageCount, onChange }: { notes: MapNote[]; points: string[]; pageCount: number; onChange: (notes: MapNote[]) => void }) {
  const [number, setNumber] = useState("");
  const [title, setTitle] = useState("");
  const [pages, setPages] = useState("");
  const range = parsePages(pages, pageCount);
  const canAdd = number.trim() !== "" && title.trim() !== "" && range !== null;

  function add() {
    if (!range) return;
    onChange(addNote(notes, { number: number.trim(), title: title.trim(), first_page: range[0], last_page: range[1] }));
    setNumber("");
    setTitle("");
    setPages("");
  }

  const columns: Column<MapNote>[] = [
    { key: "number", header: "No.", render: (n) => <span className="mono">{n.number}</span> },
    {
      key: "title",
      header: "Title",
      render: (n) =>
        n.title ? (
          n.title
        ) : (
          <>
            <span className="meta">Not found</span>
            <Unsure />
          </>
        ),
    },
    { key: "pages", header: "Pages", align: "right", muted: true, nowrap: true, render: (n) => <span className="mono">{pagesText(n)}</span> },
    {
      key: "remove",
      header: "",
      render: (n) => (
        <IconButton label={`Remove note ${n.number || n.title}`} onClick={() => onChange(notes.filter((x) => x !== n))}>
          <Icon name="close" />
        </IconButton>
      ),
    },
  ];

  return (
    <Panel className="sec">
      <div className="line">
        <h2>Notes</h2>
        <span className="meta">{notes.length} notes</span>
      </div>
      {points.map((point) => (
        <p key={point}>{point}</p>
      ))}
      <Table columns={columns} rows={notes} header={false} rowKey={(n) => `${n.number}|${n.title}|${n.first_page}`} />
      <div className="note-add">
        <TextInput className="note-no" aria-label="Note number" placeholder="No." value={number} onChange={(e) => setNumber(e.target.value)} />
        <TextInput aria-label="Note title" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextInput className="note-page" aria-label="Note pages" placeholder="Page" value={pages} onChange={(e) => setPages(e.target.value)} />
        <Button disabled={!canAdd} onClick={add}>
          Add
        </Button>
      </div>
    </Panel>
  );
}
