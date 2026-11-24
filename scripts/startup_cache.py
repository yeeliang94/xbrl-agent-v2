"""Skip start-script steps whose inputs have not changed. Ported from v1. Standard library only.

    python scripts/startup_cache.py check|mark pip|npm|build

`check` exits 0 when the step is current, 1 when it must run again, 2 on an
error. `mark` records the step as done. Each stamp lives inside the output it
vouches for, so deleting the Python environment, `web/node_modules` or
`web/dist` also deletes its stamp and the step runs again.
"""
from __future__ import annotations

import hashlib
import os
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = WEB / "dist"


class _BuildAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        for name, value in attrs:
            if name in {"src", "href"} and value and value.startswith("/assets/"):
                self.paths.append(value.lstrip("/"))


def _build_output_exists() -> bool:
    """The built page and every file it loads are there: a half-deleted build runs again."""
    index = DIST / "index.html"
    if not index.is_file():
        return False
    assets = _BuildAssets()
    assets.feed(index.read_text(encoding="utf-8"))
    return all((DIST / path).is_file() for path in assets.paths)


def _inputs(stage: str) -> list[Path]:
    if stage == "pip":
        return [ROOT / "requirements.txt", ROOT / "constraints.txt"]
    if stage == "npm":
        return [WEB / "package.json", WEB / "package-lock.json"]
    if stage == "build":
        top = [p for p in WEB.iterdir() if p.is_file() and p.suffix in {".html", ".js", ".json", ".ts", ".css"}]
        source = [p for folder in (WEB / "src", WEB / "public") if folder.exists()
                  for p in folder.rglob("*") if p.is_file()]
        return top + source
    raise ValueError(f"unknown start-up step: {stage}")


def _stamp(stage: str) -> Path:
    places = {"pip": ROOT / "venv" / ".startup-pip", "npm": WEB / "node_modules" / ".startup-npm",
              "build": DIST / ".startup-build"}
    if stage not in places:
        raise ValueError(f"unknown start-up step: {stage}")
    return places[stage]


def _fingerprint(stage: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(_inputs(stage)):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in {"check", "mark"}:
        print("usage: startup_cache.py check|mark pip|npm|build", file=sys.stderr)
        return 2
    action, stage = argv
    try:
        fingerprint = _fingerprint(stage)
        stamp = _stamp(stage)
        if action == "check":
            if stage == "build" and not _build_output_exists():
                return 1
            return 0 if stamp.is_file() and stamp.read_text(encoding="utf-8") == fingerprint else 1
        stamp.parent.mkdir(parents=True, exist_ok=True)
        temporary = stamp.with_name(stamp.name + ".tmp")
        temporary.write_text(fingerprint, encoding="utf-8")
        os.replace(temporary, stamp)
        return 0
    except (OSError, ValueError) as exc:
        print(f"startup cache: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
