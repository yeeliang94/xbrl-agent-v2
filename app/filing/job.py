"""The `fill` job: fill a copy of an uploaded mTool template from the run.
Queued by `receipts.start` when a person uploads a template. One attempt: a
failed fill waits for a person to fill again.

Recorded by run id: the `fills` row with the receipt or the failure's
sentence, events (source `fill`: started, done or failed), and the server
log's start and end lines and a full traceback for any failure.
"""
from __future__ import annotations

import logging

from app import db
from app.filing import receipts
from app.filing.fill import FillError, fill_workbook
from app.filing.investigate import job as investigate, store as placements
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.runs.events import add_event
from app.utils.paths import output_dir
from app.workbook.xlsx_cells import WorkbookUnreadable

logger = logging.getLogger(__name__)

UNEXPECTED = "The fill stopped on an unexpected error, so try again."


class FillFailed(RuntimeError):
    """The fill did not finish; `str()` is the plain sentence already recorded."""


def _done_message(counts: dict) -> str:
    return (f"The mTool file is ready: {counts['written']} figure(s) written, {counts['not_written']} not written, "
            f"{counts['notes']} note(s) and {counts.get('reports', 0)} report field(s) written.")


def run_fill(fill_id: int, job_id: int | None = None) -> None:
    """Fill one template to a final state. Raises FillFailed when it did not finish."""
    row = receipts.begin(fill_id)
    if row is None:
        logger.info("Fill id %s is not waiting (it ended already); nothing to do.", fill_id)
        return
    run_id = int(row["run_id"])
    # From here on every failure marks the fill failed: nothing leaves it "filling".
    try:
        logger.info("Run %s: mTool fill %s starts.", run_id, fill_id)
        add_event(receipts.SOURCE, "started", "Filling the mTool template.", run_id=run_id, job_id=job_id,
                  data={"fill_id": fill_id, "template_sha256": row["template_sha256"]})
        template = receipts.file_path(row["template_path"])
        if template is None or not template.is_file():
            raise FillError("The uploaded template is no longer on the server, so upload it again.")
        output = f"{receipts.folder(run_id)}/filled-{int(fill_id)}{template.suffix}"
        report = fill_workbook(run_id, template, output_dir() / output)
        counts = receipts.receipt(report)["counts"]
        receipts.finish(fill_id, report, output)
    except (WorkbookUnreadable, FillError) as exc:   # the only failures whose text is meant for a person
        sentence = str(exc)
        logger.exception("Run %s: mTool fill %s failed: %s", run_id, fill_id, sentence)
    except Exception:
        sentence = UNEXPECTED
        logger.exception("Run %s: mTool fill %s hit an unexpected error.", run_id, fill_id)
    else:
        logger.info("Run %s: mTool fill %s ended %s: %s written, %s not written, %s notes.", run_id, fill_id,
                    report["status"], counts["written"], counts["not_written"], counts["notes"])
        try:   # the fill is ready and stays ready even if its event cannot be written
            add_event(receipts.SOURCE, "done", _done_message(counts), run_id=run_id, job_id=job_id,
                      data={"fill_id": fill_id, "status": report["status"], **counts})
        except Exception:
            logger.exception("Run %s: mTool fill %s is ready but its done event was not written.", run_id, fill_id)
        _investigate_if_needed(fill_id, run_id, report)
        return
    receipts.failed(fill_id, sentence)
    add_event(receipts.SOURCE, "failed", f"The mTool fill failed: {sentence}", run_id=run_id, job_id=job_id,
              data={"fill_id": fill_id})
    raise FillFailed(sentence)


def _investigate_if_needed(fill_id: int, run_id: int, report: dict) -> None:
    """Figures the fill could not place go to the investigating agent (step 12). A figure a finished
    investigation of this template already looked at is not looked at again, so a person is not asked twice
    about a place they skipped and no model is paid for the same answer; a failed investigation blocks
    nothing. The fill stays ready whatever happens here."""
    if not placements.to_place(report):
        return
    try:
        with db.connect(immediate=True) as conn:
            if not placements.to_place(report, placements.looked_at(conn, report["template"]["fingerprint"])):
                logger.info("Run %s: every figure fill %s left was looked at before in this template.", run_id,
                            fill_id)
                return
            investigate.start(conn, fill_id, run_id)
    except Exception:
        logger.exception("Run %s: the investigation of fill %s could not be queued.", run_id, fill_id)


@handler(receipts.JOB)
def fill_job(job: Job) -> None:
    run_fill(int(job.payload["fill_id"]), job.id)
