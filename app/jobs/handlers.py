"""Job handlers registered in code. Later steps add the run stages here."""
from __future__ import annotations

from app.jobs.queue import Job
from app.jobs.worker import handler


@handler("test.echo")
def test_echo(job: Job) -> None:
    """A trivial handler for tests: it fails while the attempt number is at or
    below `payload["fail_attempts"]`, then succeeds."""
    if job.attempts <= int(job.payload.get("fail_attempts", 0)):
        raise RuntimeError(f"Planned failure on attempt {job.attempts}.")


# The run stages.
from app.reading import job as _reading  # noqa: E402,F401
from app.extraction import job as _extraction  # noqa: E402,F401
from app.review import job as _review  # noqa: E402,F401
from app.notes import job as _notes  # noqa: E402,F401
from app.filing import job as _fill  # noqa: E402,F401
from app.reports import job as _reports  # noqa: E402,F401
from app.filing.investigate import job as _investigate  # noqa: E402,F401
