import type { ReactNode } from "react";
import { Icon, IconButton } from "../../components/IconButton";
import { Segmented } from "../../components/Segmented";
import type { LookAction, LookNow, Scope } from "./noteModel";

const SCOPES = [
  { value: "cell" as const, label: "Cell" },
  { value: "row" as const, label: "Row" },
  { value: "column" as const, label: "Column" },
  { value: "table" as const, label: "Table" },
];

export interface NoteToolbarProps {
  now: LookNow;
  tools: { text: boolean; bold: boolean; borders: boolean; top: boolean };
  /** The scope of a table selection; null when a text block or nothing is selected. */
  scope: Scope | null;
  canUndo: boolean;
  /** No change while an agent works. */
  disabled: boolean;
  onScope: (scope: Scope) => void;
  onLook: (action: LookAction) => void;
  onUndo: () => void;
}

/** Undo, then bold, italic, underline, three alignments, indent and borders; Cell, Row, Column or Table for a table. */
export function NoteToolbar({ now, tools, scope, canUndo, disabled, onScope, onLook, onUndo }: NoteToolbarProps) {
  const off = (allowed: boolean) => disabled || !allowed;
  const b = (label: string, action: LookAction, pressed: boolean, allowed: boolean, icon: ReactNode) => (
    <IconButton label={label} pressed={pressed} disabled={off(allowed)} onClick={() => onLook(action)}>
      {icon}
    </IconButton>
  );
  return (
    <div className="tb" role="toolbar" aria-label="Format">
      <IconButton label="Undo" disabled={disabled || !canUndo} onClick={onUndo}>
        <Icon name="undo" />
      </IconButton>
      <span className="tb-div" />
      {b("Bold", { k: "bold" }, now.bold, tools.bold, <b className="glyph">B</b>)}
      {b("Italic", { k: "italic" }, now.italic, tools.text, <i className="glyph">I</i>)}
      {b("Underline", { k: "underline" }, now.underline, tools.text, <u className="glyph">U</u>)}
      <span className="tb-div" />
      {b("Align left", { k: "align", v: "left" }, now.align === "left", tools.text, <Icon name="alignLeft" />)}
      {b("Align centre", { k: "align", v: "center" }, now.align === "center", tools.text, <Icon name="alignCenter" />)}
      {b("Align right", { k: "align", v: "right" }, now.align === "right", tools.text, <Icon name="alignRight" />)}
      <span className="tb-div" />
      {b("Decrease indent", { k: "indent", d: -1 }, false, tools.text, <Icon name="indentOut" />)}
      {b("Increase indent", { k: "indent", d: 1 }, false, tools.text, <Icon name="indentIn" />)}
      <span className="tb-div" />
      {b("Top border", { k: "border", v: "top" }, now.top, tools.top, <Icon name="borderTop" />)}
      {b("Bottom border", { k: "border", v: "bottom" }, now.bottom === "single", tools.borders, <Icon name="borderBottom" />)}
      {b("Thick bottom border", { k: "border", v: "thick" }, now.bottom === "double", tools.borders, <Icon name="borderThick" />)}
      {b("No borders", { k: "border", v: "none" }, false, tools.borders, <Icon name="borderNone" />)}
      <span className="spacer" />
      {scope && <Segmented label="Select" options={SCOPES} value={scope} onChange={onScope} />}
    </div>
  );
}
