import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import "./Dialog.css";

export interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children?: ReactNode;
  /** Buttons, right-aligned at the bottom. */
  actions?: ReactNode;
  /** Wider, for a page picture. */
  wide?: boolean;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** One dialog for the whole app. Escape or a click outside closes it. */
export function Dialog({ open, title, onClose, children, actions, wide = false }: DialogProps) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? box.current)?.focus();
    return () => before?.focus?.();
  }, [open]);

  if (!open) return null;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !box.current) return;
    const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className="scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        className={wide ? "dlg wide" : "dlg"}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <h2 id="dialog-title">{title}</h2>
        {children}
        {actions && <div className="dlg-actions">{actions}</div>}
      </div>
    </div>
  );
}
