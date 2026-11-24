import type { ReactNode } from "react";
import { Count } from "../../components/Count";

export type Tab = "needs" | "source" | "comments" | "activity";

const TABS: { tab: Tab; label: string }[] = [
  { tab: "needs", label: "Needs you" },
  { tab: "source", label: "Source" },
  { tab: "comments", label: "Comments" },
  { tab: "activity", label: "Activity" },
];

/** The side panel: four tabs and the open one's body. */
export function SidePanel({ tab, counts, onTab, children }: { tab: Tab; counts: Partial<Record<Tab, number>>; onTab: (tab: Tab) => void; children: ReactNode }) {
  return (
    <aside className="panel side">
      <div className="tabs" role="tablist" aria-label="Side panel">
        {TABS.map((t) => (
          <button
            key={t.tab}
            type="button"
            role="tab"
            id={`tab-${t.tab}`}
            aria-selected={tab === t.tab}
            aria-controls="side-body"
            className={tab === t.tab ? "on" : undefined}
            onClick={() => onTab(t.tab)}
          >
            {t.label}
            <Count value={counts[t.tab] ?? 0} />
          </button>
        ))}
      </div>
      <div className="sb" id="side-body" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {children}
      </div>
    </aside>
  );
}
