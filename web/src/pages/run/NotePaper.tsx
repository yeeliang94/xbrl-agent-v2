import { useLayoutEffect, useMemo, useRef, type CSSProperties, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import type { Note, NoteBlock, NoteReport, NoteReview } from "../../api";
import { isSelected, selectCell, unsureAt, type NoteSelection } from "./noteModel";

// The note as review draws it is the server's prepared text for the field,
// the same text Copy and mTool get (docs/step-6-plan.md 6c): the Settings
// house style, column widths and the size tier are all in it. The review
// variant marks each block with data-note and data-block, and each table
// cell with data-row and data-col, so selection is laid over that text.

/** One block of the open note in the review text, with the blank line before it. */
export interface ReviewChunk {
  block: number;
  html: string;
}

const camel = (name: string) => name.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());

function styleOf(css: string): CSSProperties {
  const out: Record<string, string> = {};
  for (const decl of css.split(";")) {
    const at = decl.indexOf(":");
    if (at > 0) out[camel(decl.slice(0, at).trim())] = decl.slice(at + 1).trim();
  }
  return out as CSSProperties;
}

/**
 * The open note's part of the field's review text: its blocks in order, each
 * with the blank line mTool gets before it, and the style of the text's own
 * wrapper (font and body alignment) when it has one. Other notes placed in
 * the same field are left out.
 */
export function reviewChunks(html: string, noteId: number): { style: CSSProperties; chunks: ReviewChunk[] } {
  const body = new DOMParser().parseFromString(html, "text/html").body;
  let nodes = Array.from(body.children);
  let style: CSSProperties = {};
  const only = nodes.length === 1 ? nodes[0] : null;
  if (only && only.tagName === "DIV" && !only.hasAttribute("data-block")) {
    style = styleOf(only.getAttribute("style") ?? "");
    nodes = Array.from(only.children);
  }
  const chunks: ReviewChunk[] = [];
  let before = "";
  let mineBefore = false;
  for (const el of nodes) {
    const block = el.getAttribute("data-block");
    if (block === null) {
      before += el.outerHTML;
      continue;
    }
    const mine = el.getAttribute("data-note") === String(noteId);
    if (mine) {
      const at = Number(block);
      const last = chunks[chunks.length - 1];
      if (last && last.block === at) last.html += before + el.outerHTML;
      else chunks.push({ block: at, html: (mineBefore ? before : "") + el.outerHTML });
    }
    mineBefore = mine;
    before = "";
  }
  return { style, chunks };
}

export interface NotePaperProps {
  note: Note;
  /** The field's review text; null while it loads. */
  review: NoteReview | null;
  sel: NoteSelection;
  /** The open source gaps the notes agent reported in this note. */
  gaps: NoteReport[];
  /** Whether a live comment points at this block, or this cell of a table. */
  marked: (block: number, row?: number, column?: number) => boolean;
  onSelect: (sel: NoteSelection) => void;
}

const press = (go: () => void) => (e: KeyboardEvent) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    go();
  }
};

const cls = (...names: (string | false)[]) => names.filter(Boolean).join(" ") || undefined;

/** The table cell an event happened in, as its row and column in the block. */
function cellAt(target: EventTarget | null): [number, number] | null {
  const cell = target instanceof Element ? target.closest("[data-row]") : null;
  return cell ? [Number(cell.getAttribute("data-row")), Number(cell.getAttribute("data-col"))] : null;
}

/** The note on the A4 page, as the prepared text draws it. Each block, and each cell of a table, can be selected. */
export function NotePaper({ note, review, sel, gaps, marked, onSelect }: NotePaperProps) {
  const blocks = note.blocks;
  const paper = useRef<HTMLDivElement>(null);
  const html = review?.html ?? null;
  const { style, chunks } = useMemo(() => (html !== null ? reviewChunks(html, note.id) : { style: {}, chunks: [] as ReviewChunk[] }), [html, note.id]);

  // The cells are inside the server's text, so their selection, comment and
  // "not sure" marks are set on them after each draw.
  useLayoutEffect(() => {
    paper.current?.querySelectorAll<HTMLElement>("[data-chunk]").forEach((chunk) => {
      const i = Number(chunk.getAttribute("data-chunk"));
      const b = blocks[i];
      if (b?.kind !== "table") return;
      chunk.querySelectorAll<HTMLElement>("[data-row]").forEach((cell) => {
        const r = Number(cell.getAttribute("data-row"));
        const c = Number(cell.getAttribute("data-col"));
        if (!b.rows[r]?.cells[c]) return;
        cell.classList.toggle("hit", isSelected(blocks, sel, i, r, c));
        cell.classList.toggle("has", marked(i, r, c));
        cell.classList.toggle("ns", unsureAt(b, r, c));
        cell.tabIndex = 0;
        if (!cell.textContent?.trim()) cell.setAttribute("aria-label", `Empty cell, row ${r + 1}, column ${c + 1}`);
      });
    });
  });

  if (!review) return <NoteSkeleton label="Loading the note" />;

  const gapAfter = (b: NoteBlock | null): ReactNode[] =>
    gaps
      .filter((g) => (b ? g.after_block === b.id : !blocks.some((x) => x.id === g.after_block)))
      .map((g) => (
        <div
          key={`gap-${g.id}`}
          className={cls("gapb", sel?.kind === "gap" && sel.report === g.id && "hit")}
          role="button"
          tabIndex={0}
          onClick={() => onSelect({ kind: "gap", report: g.id })}
          onKeyDown={press(() => onSelect({ kind: "gap", report: g.id }))}
        >
          {`Page ${g.pages[g.pages.length - 1] ?? note.pages[note.pages.length - 1]} ends here`}
        </div>
      ));

  const drawn = chunks.map(({ block: i, html }) => {
    const b = blocks[i];
    if (!b) return null;
    const inner = { __html: html };
    if (b.kind === "table") {
      const pick = (target: EventTarget | null) => {
        const at = cellAt(target);
        if (at && b.rows[at[0]]?.cells[at[1]]) onSelect(selectCell(sel, i, at[0], at[1]));
      };
      return (
        <div
          key={b.id}
          data-chunk={i}
          className={cls("nb", "nbt", marked(i) && "has")}
          onClick={(e: MouseEvent) => pick(e.target)}
          onKeyDown={(e) => press(() => pick(e.target))(e)}
          dangerouslySetInnerHTML={inner}
        />
      );
    }
    const go = () => onSelect({ kind: "block", block: i });
    return (
      <div
        key={b.id}
        data-chunk={i}
        className={cls("nb", isSelected(blocks, sel, i) && "hit", marked(i) && "has", unsureAt(b) && "ns")}
        role="button"
        tabIndex={0}
        aria-pressed={isSelected(blocks, sel, i)}
        onClick={go}
        onKeyDown={press(go)}
        dangerouslySetInnerHTML={inner}
      />
    );
  });

  return (
    <div ref={paper} className="prep" style={style}>
      {chunks.map((ch, k) => [drawn[k], ...(blocks[ch.block] ? gapAfter(blocks[ch.block]) : [])])}
      {gapAfter(null)}
    </div>
  );
}

const SKELETON = [40, 100, 96, 100, 72, 0, 100, 88, 100, 60];

/** Grey lines where a note will be, while the notes agent places notes. */
export function NoteSkeleton({ lines = SKELETON, label = "Notes are being placed" }: { lines?: number[]; label?: string }) {
  return (
    <div className="skl-lines" aria-label={label} role="status">
      {lines.map((w, i) => (
        <div key={i} className="skl" style={{ width: `${w}%`, visibility: w ? undefined : "hidden" }} />
      ))}
    </div>
  );
}
