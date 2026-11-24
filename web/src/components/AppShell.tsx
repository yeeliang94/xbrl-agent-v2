import { createContext, useState, type ReactNode } from "react";
import type { User } from "../api";
import "./AppShell.css";

export interface NavItem {
  href: string;
  label: string;
  active: boolean;
}

export interface AppShellProps {
  user: User;
  nav: NavItem[];
  onLogout: () => void;
  children: ReactNode;
}

function initials(user: User): string {
  const source = user.name.trim() || user.email;
  const parts = source.split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : source.slice(0, 2);
  return letters.toUpperCase();
}

/** A place in the sidebar under the main links, where a screen may add its own
 * links (the run screen lists its statements there). Null outside the shell. */
export const NavSlot = createContext<HTMLElement | null>(null);

/** The black sidebar and the main column. */
export function AppShell({ user, nav, onLogout, children }: AppShellProps) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <div className="app">
      <nav className="nav" aria-label="Main">
        <div className="brand">
          <i aria-hidden="true" />
          XBRL Agent
        </div>
        {nav.map((item) => (
          <a key={item.href} href={item.href} className={item.active ? "on" : undefined} aria-current={item.active ? "page" : undefined}>
            <span>{item.label}</span>
          </a>
        ))}
        <div className="nav-slot" ref={setSlot} />
        <span className="nav-spacer" />
        <div className="who">
          <span className="avatar" aria-hidden="true">
            {initials(user)}
          </span>
          <span className="who-name">{user.name || user.email}</span>
          <button type="button" className="who-out" onClick={onLogout}>
            Log out
          </button>
        </div>
      </nav>
      <main className="main">
        <NavSlot.Provider value={slot}>{children}</NavSlot.Provider>
      </main>
    </div>
  );
}
