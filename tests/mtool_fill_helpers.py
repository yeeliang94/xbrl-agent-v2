"""Runs that match the genuine mTool templates under `templates/`, with saved
figures, for the mTool fill tests. No model is called."""
from __future__ import annotations

from pathlib import Path

from app import db
from app.catalog import lookup
from app.catalog.dimensions import CATEGORY_SHEETS
from app.catalog.fields import run_fields
from app.figures import store
from app.workbook.mtool_map import category_choices
from tests.conftest import make_run

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
GENUINE = sorted(TEMPLATES.glob("mTool_*.xlsx"))
AGENT = store.Actor("agent", "figures")


def setup_of(template: Path) -> dict:
    """The run setup a genuine template's file name describes."""
    parts = template.stem.split("_")
    layouts = {}
    for part in parts[3:]:
        if "-" in part:
            statement, variant = part.split("-", 1)
            layouts[statement] = variant
        elif part in ("SOCIE", "SORE"):
            layouts["SOCIE"] = "Default" if part == "SOCIE" else "SoRE"
    return {"standard": parts[1], "level": parts[2], "first_statements": "FirstTime" in parts,
            "statements": tuple(layouts.items())}


def matching_run(template: Path) -> int:
    setup = setup_of(template)
    return make_run(setup["statements"], standard=setup["standard"], level=setup["level"],
                    first_statements=setup["first_statements"])


def value_for(i: int) -> float:
    """Distinct values, some negative and some with cents, none zero."""
    return [1000.0 + i, -(250.0 + i), 12345.67 + i][i % 3]


def seed_input_figures(run_id: int, *, every: int = 1) -> list[store.FigureWrite]:
    """Save a figure on every `every`-th input line of the run's templates (not
    totals), for every entity, period and category the line takes."""
    with db.connect() as conn:
        family = lookup.run_family(conn, run_id)
        fields = run_fields(conn, family)
        writes = []
        for n, info in enumerate(fields.values()):
            concept = lookup.concept(conn, info.concept_uuid)
            if info.is_total or not concept.writable or n % every:
                continue
            choices = category_choices(info, family, True) if info.sheet in CATEGORY_SHEETS else [{}]
            for dims in choices:
                for entity in family.entity_scopes:
                    for period in family.periods:
                        value = value_for(len(writes))
                        writes.append(store.FigureWrite(info.concept_uuid, period, entity, value,
                                                        [store.Line(info.plain_label, 4, value)],
                                                        dimensions=(dims or None) if dims != info.dimensions
                                                        else None))
        results = store.save_figures(conn, run_id, writes, AGENT)
    refused = [r["refused"] for r in results if not r["ok"]]
    assert not refused, refused[:3]
    return writes
