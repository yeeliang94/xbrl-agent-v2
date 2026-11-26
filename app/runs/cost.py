"""What a run cost and how long its agents worked, from the `model_calls` table (app/models/usage.py).

One row per agent, in the order the agents work. An agent run that names
itself (`model_calls.agent`: one statement's figures agent, one notes
session, a redone statement) has a row of its own, in the order it started;
the other calls are grouped by the agent that made them. An agent's time is the time
it spent waiting on the model: its calls laid end to end, with calls made
side by side (pages are transcribed several at once) counted once. The cost
is the estimate recorded with each call; a call whose model has no known
price adds nothing and is counted in `unpriced`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# model_calls.source -> the agent as a person names it, in working order.
AGENTS = (
    ("Reading the document", ("transcription", "reader")),
    ("Figures", ("figures",)),
    ("Notes", ("notes",)),
    ("Reports", ("reports",)),
    ("Corrections", ("review",)),
    ("Finding places in the template", ("investigate",)),
)
OTHER = "Other"


def _seconds(calls: list[tuple[datetime, int]]) -> int:
    """The length of the calls' time spans joined together. Each call is (when it ended, its length in ms)."""
    spans = sorted((end - timedelta(milliseconds=ms), end) for end, ms in calls)
    total, open_from, open_to = timedelta(), None, None
    for start, end in spans:
        if open_to is None or start > open_to:
            if open_to is not None:
                total += open_to - open_from
            open_from, open_to = start, end
        else:
            open_to = max(open_to, end)
    if open_to is not None:
        total += open_to - open_from
    return round(total.total_seconds())


def run_cost(conn: sqlite3.Connection, run_id: int) -> dict:
    """`RunCost`: `{"agents": [{"agent", "seconds", "cost_usd", "calls", "unpriced"}], "total": {...}}`.
    `cost_usd` is null when none of the calls has a known price."""
    name_of = {source: name for name, sources in AGENTS for source in sources}
    rank = {name: i for i, (name, _) in enumerate(AGENTS)}
    groups: dict[tuple[int, str], dict] = {}
    for row in conn.execute("SELECT id, source, agent, cost_usd, duration_ms, created_at FROM model_calls "
                            "WHERE run_id = ? ORDER BY id", (run_id,)):
        kind = name_of.get(row["source"], OTHER)
        name = row["agent"] or kind
        group = groups.setdefault((rank.get(kind, len(AGENTS)), name), {
            "first": row["id"], "spans": [], "cost": 0.0, "calls": 0, "unpriced": 0})
        group["calls"] += 1
        if row["cost_usd"] is None:
            group["unpriced"] += 1
        else:
            group["cost"] += row["cost_usd"]
        if row["duration_ms"]:
            group["spans"].append((datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
                                   int(row["duration_ms"])))
    agents = [{"agent": name, "seconds": _seconds(group["spans"]), "calls": group["calls"],
               "cost_usd": round(group["cost"], 4) if group["unpriced"] < group["calls"] else None,
               "unpriced": group["unpriced"]}
              for (_, name), group in sorted(groups.items(), key=lambda item: (item[0][0], item[1]["first"]))]
    priced = [a["cost_usd"] for a in agents if a["cost_usd"] is not None]
    return {"agents": agents,
            "total": {"seconds": sum(a["seconds"] for a in agents), "calls": sum(a["calls"] for a in agents),
                      "cost_usd": round(sum(priced), 4) if priced else None,
                      "unpriced": sum(a["unpriced"] for a in agents)}}
