import { useEffect } from "react";
import "./Toast.css";

/** A short confirmation that fades by itself, e.g. "Run deleted". Empty text shows nothing. */
export function Toast({ text, onDone, after = 2400 }: { text: string; onDone: () => void; after?: number }) {
  useEffect(() => {
    if (!text) return;
    const timer = window.setTimeout(onDone, after);
    return () => window.clearTimeout(timer);
  }, [text, onDone, after]);

  return (
    <div className={text ? "toast on" : "toast"} role="status">
      {text}
    </div>
  );
}
