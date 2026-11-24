"""Build the two zip files the app is shipped as. Standard library only.

    venv/bin/python scripts/package.py azure [--out PATH]
    venv/bin/python scripts/package.py veracode [--include-tests] [--out PATH]

Both start from the files git tracks, so nothing in `.gitignore` (`.env`, the
database, `output/`, client documents in `test-data/`) can enter a package.
Files git does not track yet are refused rather than silently left out or
added: commit, delete or ignore them first.

`azure` is what App Service runs (`scripts/deploy_azure.bat` sends it). It keeps
only what the running app reads: `app/`, `templates/`, `server.py`, the two
requirement files and the built browser app in `web/dist`, plus `version.txt`
naming the commit. v1 copied the whole checkout and excluded folders by name;
v2 lists what goes in instead, so a new private folder can never slip into the
upload. Entries are written with forward slashes: Windows PowerShell's
Compress-Archive writes backslashes, which Linux App Service unpacks as flat
files named `web\\dist\\index.html` (found in v1).

`veracode` is the source code for a Veracode static scan: code and the
dependency lists (requirements, constraints, the npm manifest and lock, which
Veracode's dependency scan reads), with no data, templates, documents, fonts or
images. Tests are left out unless asked for: they are not shipped and add false
findings.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = "web/dist/"

AZURE_FOLDERS = ("app/", "templates/")
AZURE_FILES = ("server.py", "requirements.txt", "constraints.txt")

# Only what git can track: ignored folders and files never reach these lists.
VERACODE_DROPPED_FOLDERS = ("templates", "docs", "prototypes", ".claude", ".github")
VERACODE_DROPPED_SUFFIXES = (
    ".xlsx", ".xlsm", ".xls", ".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".ttf", ".otf", ".woff", ".woff2",
)
VERACODE_DROPPED_NAMES = (".gitignore", ".gitattributes", "greptile.json", "LICENSE")


def git_files(*extra: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", *extra], cwd=ROOT, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _private(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith(".env") and name != ".env.example"


def _junk(rel: str) -> bool:
    parts = rel.split("/")
    return "__pycache__" in parts or parts[-1] == ".DS_Store" or rel.endswith(".pyc")


def azure_keeps(rel: str) -> bool:
    if _private(rel) or _junk(rel):
        return False
    return rel in AZURE_FILES or rel.startswith(AZURE_FOLDERS)


def veracode_keeps(rel: str, include_tests: bool) -> bool:
    parts = rel.split("/")
    if _private(rel) or _junk(rel) or parts[0] in VERACODE_DROPPED_FOLDERS:
        return False
    if not include_tests and (parts[0] == "tests" or ".test." in parts[-1] or parts[-1] == "test-setup.ts"):
        return False   # server tests, and the browser tests that sit beside the code
    if parts[-1] in VERACODE_DROPPED_NAMES or rel.endswith(VERACODE_DROPPED_SUFFIXES):
        return False
    return True


def built_app() -> list[str]:
    """The built browser app's files, or an empty list when it is missing or half built."""
    dist = ROOT / DIST
    if not (dist / "index.html").is_file():
        return []
    files = [p.relative_to(ROOT).as_posix() for p in dist.rglob("*") if p.is_file()]
    # The build writes no hidden files: one there is a stamp (scripts/startup_cache.py) or a
    # stray, and a stray .env must never ship.
    return sorted(f for f in files if not _junk(f) and not f.rsplit("/", 1)[-1].startswith("."))


def _refuse_untracked(keeps) -> bool:
    loose = sorted(f for f in git_files("--others", "--exclude-standard") if keeps(f))
    if loose:
        print("ERROR: these files are not in git, so the package would not match any commit. "
              "Commit, delete or ignore them first:", file=sys.stderr)
        for rel in loose:
            print(f"  {rel}", file=sys.stderr)
    return bool(loose)


def write_zip(out: Path, files: list[str], extra: dict[str, str] | None = None) -> None:
    """Write `files` (relative to the project) and `extra` (name -> text), then swap the
    finished zip into place, so a failure never leaves half a package."""
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, suffix=".zip.part")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in files:
                zf.write(ROOT / rel, rel)   # `rel` uses forward slashes on every system
            for name, text in (extra or {}).items():
                zf.writestr(name, text)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def azure(out: Path) -> int:
    if _refuse_untracked(azure_keeps):
        return 1
    site = built_app()
    if not site:
        print("ERROR: the browser app is not built. Run `npm ci` and `npm run build` in web/ first.",
              file=sys.stderr)
        return 1
    files = sorted(f for f in git_files("--cached") if azure_keeps(f) and (ROOT / f).is_file())
    stamp = commit()
    write_zip(out, files + site, {"version.txt": stamp + "\n"})
    print(f"Wrote {out}")
    print(f"  commit {stamp}: {len(files)} app files, {len(site)} browser app files, "
          f"{out.stat().st_size / 1_048_576:.1f} MB")
    return 0


def veracode(out: Path, include_tests: bool) -> int:
    keeps = lambda f: veracode_keeps(f, include_tests)  # noqa: E731
    if _refuse_untracked(keeps):
        return 1
    files = sorted(f for f in git_files("--cached") if keeps(f) and (ROOT / f).is_file())
    if not files:
        print("ERROR: no files selected; is this a git checkout?", file=sys.stderr)
        return 1
    write_zip(out, files)
    by_ext: dict[str, int] = {}
    for rel in files:
        ext = os.path.splitext(rel)[1] or "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    print(f"Wrote {out}")
    print(f"  {len(files)} files, {out.stat().st_size / 1_048_576:.1f} MB")
    for ext, n in sorted(by_ext.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {ext}")
    print("  tests included" if include_tests else "  tests left out (add --include-tests to include them)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Azure or the Veracode package.")
    ap.add_argument("kind", choices=("azure", "veracode"))
    ap.add_argument("--include-tests", action="store_true", help="veracode only")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.kind == "azure":
        out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "xbrl-v2-deploy.zip"
        return azure(out)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = Path(args.out) if args.out else ROOT / "veracode" / f"xbrl-agent-v2-veracode-{stamp}.zip"
    return veracode(out, args.include_tests)


if __name__ == "__main__":
    sys.exit(main())
