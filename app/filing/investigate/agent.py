"""The investigating agent: one run on the shared agent loop over a copy of the template, with its own
transcript. It runs only when a fill left figures without a cell (`store.to_place`)."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from app import db
from app.agents import history, loop
from app.catalog.lookup import run_family
from app.extraction.state import budgeted
from app.filing import receipts
from app.filing.investigate import instructions, store, tools
from app.filing.investigate.tools import InvestigateDeps
from app.workbook.toolkit import identify as identify_script
from app.workbook.toolkit.book import Book

MAX_STEPS = 40
MAX_SECONDS = 15 * 60
THINKING = "medium"
TEXT_TOOLS = frozenset({"list_rows", "find_rows", "read_cells", "compare_with_filled", "show_figures"})


class CannotStart(ValueError):
    """There is nothing to investigate. `str()` is one plain sentence."""


def _context(conn, concept_uuid: str) -> dict:
    """The figure's SSM name and the headings above its line, so lines whose labels repeat can be told apart."""
    row = conn.execute("SELECT n.parent_uuid, a.primary_concept FROM concept_nodes n LEFT JOIN "
                       "concept_semantic_addresses a ON a.concept_uuid = n.concept_uuid WHERE n.concept_uuid = ?",
                       (concept_uuid,)).fetchone()
    if row is None:
        return {}
    path, parent = [], row["parent_uuid"]
    while parent and len(path) < 4:
        up = conn.execute("SELECT parent_uuid, COALESCE(display_label, canonical_label) AS label FROM concept_nodes "
                          "WHERE concept_uuid = ?", (parent,)).fetchone()
        if up is None:
            break
        path.append(" ".join((up["label"] or "").split()).lstrip("*").strip())
        parent = up["parent_uuid"]
    return {"ssm": row["primary_concept"] or "", "section": " > ".join(reversed([p for p in path if p]))}


def build_deps(fill_id: int, workdir: Path, *, job_id: Optional[int] = None,
               max_steps: Optional[int] = None) -> tuple[InvestigateDeps, str]:
    with db.connect() as conn:
        fill = conn.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone()
        if fill is None or fill["job_status"] != "ready" or not fill["report_json"]:
            raise CannotStart("The fill is not ready, so there is nothing to investigate.")
        report = json.loads(fill["report_json"])
        lines = store.to_place(report, store.looked_at(conn, fill["template_fingerprint"]))
        family = run_family(conn, int(fill["run_id"]))
        lines = [{**line, **_context(conn, line["concept_uuid"])} for line in lines]
    if not lines:
        raise CannotStart("The fill placed every figure it could, so there is nothing to investigate.")
    template = receipts.file_path(fill["template_path"])
    if template is None or not template.is_file():
        raise CannotStart("The template is no longer on the server, so it cannot be investigated.")
    copy = workdir / f"template{template.suffix}"
    shutil.copyfile(template, copy)
    output = receipts.file_path(fill["output_path"])
    figures = {f"F{i}": line for i, line in enumerate(lines, 1)}
    group = family is not None and family.level == "group"
    deps = InvestigateDeps(run_id=int(fill["run_id"]), fill_id=fill_id, book=Book(copy, group),
                           filled=Book(output, group) if output is not None and output.is_file() else None,
                           figures=figures, written={w["cell"] for w in report.get("written") or [] if w.get("cell")},
                           job_id=job_id, max_steps=max_steps or MAX_STEPS)
    message = instructions.first_message(template=fill["template_filename"], identity=identify_script.run(deps.book),
                                         figures=[tools.figure_line(fid, line) for fid, line in figures.items()])
    return deps, message


def spec(model_id: str, deps: InvestigateDeps) -> loop.AgentSpec:
    trimmer = history.Trimmer(text_tools=TEXT_TOOLS, saved=lambda _messages: deps.writes > 0)
    return loop.AgentSpec(name=tools.NAME, model_id=model_id, instructions=instructions.INSTRUCTIONS,
                          tools=[budgeted(t) for t in tools.TOOLS], output_type=tools.FinishInvestigation,
                          max_steps=deps.max_steps, max_seconds=MAX_SECONDS, retries=4, thinking=THINKING,
                          history_processor=trimmer, output_validator=tools.finish)


async def run(fill_id: int, model_id: str, *, job_id: Optional[int] = None, model: Any = None,
              should_stop: Callable[[], Any] = lambda: False, max_steps: Optional[int] = None
              ) -> tuple[loop.AgentOutcome, InvestigateDeps]:
    with tempfile.TemporaryDirectory(prefix="investigate-") as workdir:
        deps, message = build_deps(fill_id, Path(workdir), job_id=job_id, max_steps=max_steps)
        outcome = await loop.run_agent(spec(model_id, deps), message, deps=deps, run_id=deps.run_id, job_id=job_id,
                                       model=model, should_stop=should_stop)
    return outcome, deps


def record(outcome: loop.AgentOutcome, deps: InvestigateDeps) -> dict:
    return {"fill_id": deps.fill_id, "status": outcome.status, "message": outcome.message, "steps": outcome.steps,
            "figures": len(deps.figures), "proposed": len(deps.proposed), "finish": deps.finish}
