"""Live: a real correction round on a seeded wrong figure. Costs money; left
out of the default run.

    LIVE_EXTRACTION=/folder/of/the/extraction/live/test LIVE_OUT=/some/temp/folder \\
        venv/bin/python -m pytest tests/test_review_live.py -m live -s
    LIVE_DOCS="Doc_2" ...     # only the documents whose names contain these (default Doc_1)

It starts from a run the extraction live test left (LIVE_EXTRACTION/<name>-extraction,
copied under LIVE_OUT, never into the repository). The largest figure the
figures agent saved is made wrong by RM 1,000, as a person's mistaken edit, and a
person's comment says the figure does not agree with its page. The real Reviewer
works the round through the job. It passes when the round is done, the
figure is back to its printed amount, and the comment is answered "changed"
with the server seeing the change. A summary is printed and written to
LIVE_OUT/review-<name>.json first.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import db
from app.catalog import loader
from app.figures import store
from app.jobs import worker
from app.models import usage as model_usage
from app.review import changes, comments, rounds
from app.utils.paths import PROJECT_ROOT

pytestmark = pytest.mark.live


def _chosen() -> list[str]:
    wanted = [w.strip() for w in os.environ.get("LIVE_DOCS", "").split(",") if w.strip()]
    return wanted or ["Doc_1"]


@pytest.mark.parametrize("name", _chosen())
async def test_a_real_round_corrects_a_seeded_wrong_figure(name, monkeypatch, tmp_path):
    openai_key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY is not in .env")
    source = Path(os.environ.get("LIVE_EXTRACTION", "")) / f"{name}-extraction"
    if not os.environ.get("LIVE_EXTRACTION") or not (source / "xbrl.db").is_file():
        pytest.skip("Set LIVE_EXTRACTION to the extraction live test's folder.")
    monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    out = Path(os.environ.get("LIVE_OUT") or tmp_path)
    folder = out / f"{name}-review"
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(source, folder)
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    loader.load_catalogue()

    with db.connect(immediate=True) as conn:
        run = conn.execute("SELECT * FROM runs WHERE status = 'in_review' ORDER BY id DESC LIMIT 1").fetchone()
        assert run is not None, "the extraction run is not in review"
        figure = conn.execute("SELECT * FROM figures WHERE run_id = ? AND origin = 'agent' AND value IS NOT NULL "
                              "AND period = 'CY' ORDER BY ABS(value) DESC LIMIT 1", (run["id"],)).fetchone()
        right = figure["value"]
        store.edit_by_person(conn, run["id"], store.Actor("person", run["owner_email"]),
                             concept_uuid=figure["concept_uuid"], period="CY", entity_scope="Company",
                             value=right + 1000)
        target = comments.resolve_target(conn, run["id"], {"kind": "figure", "figure_id": figure["id"]})
        comment_id = comments.add_person_comment(conn, run, {
            "target": target, "text": "This does not agree with the page it comes from; please check it."},
            run["owner_email"])["id"]
        round_row = rounds.send(conn, run, run["owner_email"])

    assert await worker.run_once()

    with db.connect() as conn:
        done = dict(conn.execute("SELECT * FROM rounds WHERE id = ?", (round_row["id"],)).fetchone())
        now = conn.execute("SELECT value FROM figures WHERE id = ?", (figure["id"],)).fetchone()[0]
        report = changes.report(conn, run["id"], round_row["id"])
        comment = comments.get(conn, run["id"], comment_id)
    summary = {"document": name, "run_id": run["id"], "round": {k: done[k] for k in ("status", "summary", "error")},
               "right": right, "seeded": right + 1000, "now": now, "answer": comment["answer"],
               "outcome": comment["outcome"], "counts": report["counts"],
               "other": [f"{o['field_label']} {o['period']} {o['was']} -> {o['is_now']}" for o in report["other"]],
               "cost": model_usage.run_totals(run["id"], "review")}
    (out / f"review-{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    assert done["status"] == "done", done["error"]
    assert abs(now - right) <= 1
    assert comment["outcome"] == "changed" and report["comments"][0]["verified"]
