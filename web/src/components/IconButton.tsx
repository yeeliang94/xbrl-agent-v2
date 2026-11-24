import type { ButtonHTMLAttributes, ReactNode } from "react";
import "./IconButton.css";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Spoken name and tooltip. */
  label: string;
  pressed?: boolean;
  children: ReactNode;
}

export function IconButton({ label, pressed, className, children, type = "button", ...rest }: IconButtonProps) {
  return (
    <button
      type={type}
      className={["icon-btn", pressed ? "on" : "", className ?? ""].filter(Boolean).join(" ")}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Line icons drawn on a 16 by 16 grid, as in the prototype. */
const ICONS = {
  close: [{ d: "M4 4l8 8M12 4l-8 8" }],
  alignLeft: [{ d: "M2 4h12M2 8h8M2 12h10" }],
  alignCenter: [{ d: "M2 4h12M4 8h8M3 12h10" }],
  alignRight: [{ d: "M2 4h12M6 8h8M4 12h10" }],
  indentIn: [{ d: "M2 3h12M7 8h7M2 13h12M2 6l3 2-3 2" }],
  indentOut: [{ d: "M2 3h12M7 8h7M2 13h12M5 6L2 8l3 2" }],
  borderTop: [{ d: "M2 3h12", width: 2.4 }, { d: "M2 7v6h12V7", dash: true }],
  borderBottom: [{ d: "M2 13h12" }, { d: "M2 9V3h12v6", dash: true }],
  borderThick: [{ d: "M2 13h12", width: 3 }, { d: "M2 9V3h12v6", dash: true }],
  borderNone: [{ d: "M2 3h12v10H2z", dash: true }],
  undo: [{ d: "M5.5 3 2.5 6l3 3" }, { d: "M2.5 6h7a3.5 3.5 0 0 1 0 7H6" }],
  copy: [{ d: "M7 5.5h5a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 12V7A1.5 1.5 0 0 1 7 5.5z" }, { d: "M3 10.5v-7a1 1 0 0 1 1-1h7" }],
  done: [{ d: "M3 8.5 6.5 12 13 4.5" }],
} satisfies Record<string, { d: string; width?: number; dash?: boolean }[]>;

export type IconName = keyof typeof ICONS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      {ICONS[name].map((p, i) => (
        <path key={i} d={p.d} strokeWidth={"width" in p ? p.width : undefined} strokeDasharray={"dash" in p ? "1.5 2" : undefined} />
      ))}
    </svg>
  );
}
