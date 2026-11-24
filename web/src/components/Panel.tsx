import type { HTMLAttributes, ReactNode } from "react";
import "./Panel.css";

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  title?: string;
  padded?: boolean;
  children: ReactNode;
}

export function Panel({ title, padded = true, className, children, ...rest }: PanelProps) {
  const classes = ["panel", padded ? "pad" : "", title ? "sec" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <section className={classes} {...rest}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}
