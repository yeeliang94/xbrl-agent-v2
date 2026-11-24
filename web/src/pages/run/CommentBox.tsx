import { useEffect, useRef, useState } from "react";
import { errorMessage, type CommentScope } from "../../api";
import { Button } from "../../components/Button";
import { Segmented } from "../../components/Segmented";
import { TextArea } from "../../components/TextArea";

const CHIPS = ["Recheck", "Wrong field", "Wrong sign", "Should be split"];
const SCOPES = [
  { value: "figure" as const, label: "Figure" },
  { value: "run" as const, label: "Run" },
  { value: "company" as const, label: "Company" },
];

export interface CommentBoxProps {
  /** Quick chips that add a short phrase: the figure chips, or a list of its own. */
  chips?: boolean | string[];
  /** Offer "Apply to: Figure, Run, Company". Only a figure or a line may carry it. */
  scoped?: boolean;
  focus?: boolean;
  /** A note's "Redo from source", left of Add comment. */
  onRedo?: () => Promise<void>;
  onAdd: (text: string, scope: CommentScope) => Promise<void>;
}

/** The box a person writes a comment for the agent in. */
export function CommentBox({ chips = false, scoped = false, focus = false, onRedo, onAdd }: CommentBoxProps) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState<CommentScope>("figure");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (focus) box.current?.focus();
  }, [focus]);

  function chip(word: string) {
    setText((old) => (old.trim() ? `${old.trim()}. ${word}` : word));
    box.current?.focus();
  }

  async function run(work: () => Promise<void>) {
    setAdding(true);
    setError("");
    try {
      await work();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setAdding(false);
    }
  }

  function add() {
    if (!text.trim()) return;
    void run(async () => {
      await onAdd(text.trim(), scoped ? scope : "figure");
      setText("");
      setScope("figure");
    });
  }

  return (
    <>
      {chips && (
        <div className="chips">
          {(chips === true ? CHIPS : chips).map((word) => (
            <button key={word} type="button" className="chip" onClick={() => chip(word)}>
              {word}
            </button>
          ))}
        </div>
      )}
      <TextArea ref={box} aria-label="Comment for the agent" placeholder="Comment for the agent" value={text} onChange={(e) => setText(e.target.value)} />
      {scoped && (
        <div className="frow">
          <span>Apply to</span>
          <Segmented label="Apply to" options={SCOPES} value={scope} onChange={setScope} />
        </div>
      )}
      <div className="bar">
        {onRedo && (
          <Button disabled={adding} onClick={() => run(onRedo)}>
            Redo from source
          </Button>
        )}
        {error && (
          <span className="error" role="alert">
            {error}
          </span>
        )}
        <span className="spacer" />
        <Button disabled={!text.trim() || adding} onClick={add}>
          Add comment
        </Button>
      </div>
    </>
  );
}
