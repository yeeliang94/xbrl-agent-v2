import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import "./QuestionCard.css";

export interface Evidence {
  text: string;
  /** The pages it is on, each a link. */
  pages: number[];
}

export interface Choice {
  label: string;
  /** One line on what follows. */
  effect: string;
  suggested?: boolean;
}

export interface QuestionCardProps {
  question: string;
  evidence: Evidence[];
  /** Up to four. */
  choices: Choice[];
  onChoose: (index: number) => void;
  onOther: (text: string) => void;
  onPage: (page: number) => void;
  /** Tinted, when it sits inside a panel. */
  inset?: boolean;
  disabled?: boolean;
}

const typing = (target: EventTarget | null) => target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);

/** A scope question: evidence with page links, choices with key numbers, and "Something else". */
export function QuestionCard({ question, evidence, choices, onChoose, onOther, onPage, inset = false, disabled = false }: QuestionCardProps) {
  const shown = choices.slice(0, 4);
  const last = shown.length + 1;
  const [own, setOwn] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const pick = useRef(onChoose);
  pick.current = onChoose;

  // Keys 1 to n choose; the last number moves to "Something else".
  useEffect(() => {
    if (disabled) return;
    function onKey(event: KeyboardEvent) {
      if (typing(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector('[role="dialog"]')) return;
      const n = Number(event.key);
      if (!Number.isInteger(n) || n < 1 || n > last) return;
      event.preventDefault();
      if (n === last) box.current?.focus();
      else pick.current(n - 1);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [last, disabled]);

  return (
    <div className={inset ? "qc inset" : "qc"} role="group" aria-label={question}>
      <h2>{question}</h2>
      {evidence.length > 0 && (
        <div className="ev">
          {evidence.map((e) => (
            <div key={`${e.pages.join(",")}|${e.text}`}>
              <span>{e.text}</span>
              {e.pages.map((page) => (
                <button key={page} type="button" className="lk" onClick={() => onPage(page)}>
                  Page {page}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
      <div className="opts">
        {shown.map((c, i) => (
          <button key={c.label} type="button" className="opt" disabled={disabled} onClick={() => onChoose(i)}>
            <kbd>{i + 1}</kbd>
            <span>
              {c.label}
              <span className="sub">{c.effect}</span>
            </span>
            <span className="meta">{c.suggested ? "Suggested" : ""}</span>
          </button>
        ))}
        <div className="own">
          <kbd>{last}</kbd>
          <textarea ref={box} rows={1} aria-label="Something else" placeholder="Something else" value={own} disabled={disabled} onChange={(e) => setOwn(e.target.value)} />
          <Button size="small" disabled={disabled || !own.trim()} onClick={() => onOther(own.trim())}>
            Send
          </Button>
        </div>
      </div>
      <p className="qfoot">{`Press 1 to ${last} to choose`}</p>
    </div>
  );
}
