"""The server log: one UTF-8 file a day under the output folder's `logs/`,
kept 30 days, as well as the console.

Each line carries `run=<id>` when it concerns a run, else `run=-`, so a run's
traces can pick its lines out. The run comes from `RUN_ID`, set by the job
worker around a job and by `run_context` around a request to
`/api/runs/<id>/...`. Lines are written straight to the day's file (no
renaming at midnight, which Windows refuses while the file is open).

Document text, keys and passwords never belong in the log; the code that
logs is written that way. As a second guard, every line goes through
`app/utils/masking.mask` before it is written.

A successful poll for news (`GET .../read`, `.../events` and
`.../rounds/<id>`, about once a second while a page is open) is not written
to the file; a failed one is.
"""
from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, Optional, TextIO

from app.utils.masking import mask
from app.utils.paths import output_dir, safe_entry_path, safe_path

RUN_ID: ContextVar[Optional[int]] = ContextVar("run_id", default=None)
KEEP_DAYS = 30
FORMAT = "%(asctime)s %(levelname)s %(name)s run=%(run_id)s %(message)s"
_FILE = re.compile(r"^server-(\d{4}-\d{2}-\d{2})\.log$")
_LINE_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_POLL_PATH = re.compile(r"^/api/runs/\d+/(?:read|events|rounds/\d+)(?:\?|$)")
_RUN_PATH = re.compile(r"^/api/runs/(\d+)(?:/|$)")


def logs_dir() -> Path:
    return safe_path(output_dir() / "logs")


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "run_id", None) is None:
            run_id = RUN_ID.get()
            record.run_id = run_id if run_id is not None else "-"
        return True


class _QuietPolls(logging.Filter):
    """Leaves out uvicorn's access line for a successful poll."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple) or len(record.args) < 5:
            return True
        _, method, path, _, status = record.args[:5]
        return not (method == "GET" and isinstance(path, str) and _POLL_PATH.match(path)
                    and isinstance(status, int) and status < 400)


class _MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


class DailyFileHandler(logging.Handler):
    """Appends to `server-YYYY-MM-DD.log` for the local day, opening the next
    day's file when the date changes and removing files past `KEEP_DAYS`."""

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder
        self._day: Optional[date] = None
        self._stream: Optional[TextIO] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            today = date.today()
            if today != self._day or self._stream is None:
                self._open(today)
            self._stream.write(text + "\n")
            self._stream.flush()
        except Exception:  # noqa: BLE001 - logging must never end the work
            self.handleError(record)

    def _open(self, today: date) -> None:
        self._close_stream()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = safe_path(self.folder / f"server-{today.isoformat()}.log")
        self._stream = open(path, "a", encoding="utf-8")
        self._day = today
        prune(self.folder, today)

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def close(self) -> None:
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()


def _file_day(path: Path) -> Optional[date]:
    found = _FILE.match(path.name)
    if not found:
        return None
    try:
        return date.fromisoformat(found.group(1))
    except ValueError:
        return None


def prune(folder: Path, today: date) -> None:
    """Remove log files older than `KEEP_DAYS` days."""
    oldest = today - timedelta(days=KEEP_DAYS - 1)
    for path in folder.glob("server-*.log"):
        day = _file_day(path)
        if day is not None and day < oldest and not path.is_symlink():
            try:
                safe_entry_path(path).unlink()
            except OSError:
                pass   # in use or already gone; the next day tries again


def log_files() -> list[Path]:
    """The kept log files, oldest first. Only regular files named by date."""
    folder = logs_dir()
    if not folder.is_dir():
        return []
    oldest = date.today() - timedelta(days=KEEP_DAYS - 1)
    files = [p for p in folder.iterdir() if _file_day(p) is not None and _file_day(p) >= oldest
             and p.is_file() and not p.is_symlink()]
    return sorted(files, key=lambda p: p.name)


def lines_for_run(run_id: int) -> Iterator[str]:
    """Every log line carrying `run=<run_id>`, with the traceback lines that follow it."""
    marker = f" run={int(run_id)} "
    for path in log_files():
        keep = False
        with open(safe_path(path), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if _LINE_START.match(line):
                    keep = marker in line
                if keep:
                    yield line if line.endswith("\n") else line + "\n"


def setup_logging() -> None:
    """Send the app's log to the console and to the day's file under the
    current output folder. Safe to call again (each app start does)."""
    root = logging.getLogger()
    formatter = _MaskingFormatter(FORMAT)
    targets = [root, logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")]
    for logger in targets:
        for old in [h for h in logger.handlers if isinstance(h, DailyFileHandler)]:
            logger.removeHandler(old)
            old.close()
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    file_handler = DailyFileHandler(logs_dir())
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RunIdFilter())
    file_handler.addFilter(_QuietPolls())
    for logger in targets:
        # uvicorn's own loggers do not pass lines up to the root, so the file
        # handler is added to them too. Without uvicorn they have no handlers
        # and pass lines up, so the root's copy is enough.
        if logger is root or not logger.propagate:
            logger.addHandler(file_handler)
    if not any(getattr(h, "_xbrl_console", False) for h in root.handlers) and not _has_console(root):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.addFilter(_RunIdFilter())
        console._xbrl_console = True  # type: ignore[attr-defined]
        root.addHandler(console)


def _has_console(root: logging.Logger) -> bool:
    return any(type(h) is logging.StreamHandler or type(h).__name__ == "LogCaptureHandler" for h in root.handlers)


async def run_context(request, call_next):
    """Middleware: lines logged while serving `/api/runs/<id>/...` carry that run."""
    found = _RUN_PATH.match(request.url.path)
    if found is None:
        return await call_next(request)
    token = RUN_ID.set(int(found.group(1)))
    try:
        return await call_next(request)
    finally:
        RUN_ID.reset(token)
