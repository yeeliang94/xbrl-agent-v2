import type { FormEvent, ReactNode } from "react";
import { Panel } from "../components/Panel";
import "./AuthLayout.css";

/** The centred card used by Login and Change password. */
export function AuthLayout({ title, onSubmit, children }: { title: string; onSubmit: (event: FormEvent) => void; children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-brand">
        <i aria-hidden="true" />
        XBRL Agent
      </div>
      <Panel className="auth-card">
        <form className="auth-form" onSubmit={onSubmit} noValidate>
          <h1>{title}</h1>
          {children}
        </form>
      </Panel>
    </div>
  );
}
