"""The Azure and Veracode packages (scripts/package.py) and the start scripts' step cache
(scripts/startup_cache.py). What goes into a package decides what runs on Azure and what
leaves the firm, so these check the zips themselves."""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = _load("package")
startup_cache = _load("startup_cache")


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A pretend checkout: what git tracks, what it does not, and a built browser app."""
    tracked = {
        "server.py": "from app.main import app\n",
        "requirements.txt": "-c constraints.txt\nfastapi\n",
        "constraints.txt": "fastapi==1\n",
        "app/main.py": "app = None\n",
        "app/notes/fonts/LiberationSans-Regular.ttf": "font",
        "templates/XBRL-template-MFRS/Company/01-SOFP-CuNonCu.xlsx": "xlsx",
        "tests/test_x.py": "def test(): pass\n",
        "docs/plan.md": "plan",
        "prototypes/p.html": "<p>",
        "scripts/package.py": "# packager\n",
        "web/package.json": "{}",
        "web/package-lock.json": "{}",
        "web/src/App.tsx": "export {}\n",
        "web/src/App.test.tsx": "test\n",
        ".env.example": "KEY=\n",
        "README.md": "readme",
    }
    built = {"web/dist/index.html": "<html>", "web/dist/assets/index-1.js": "js", "web/dist/.startup-build": "x"}
    for rel, text in {**tracked, **built, ".env": "SECRET=1", "test-data/key.json": "{}"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    untracked: list[str] = []
    monkeypatch.setattr(package, "ROOT", tmp_path)
    monkeypatch.setattr(package, "commit", lambda: "abc1234")
    monkeypatch.setattr(package, "git_files",
                        lambda *extra: list(untracked) if "--others" in extra else list(tracked))
    return tmp_path, untracked


def _names(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def test_the_azure_package_holds_only_what_the_running_app_reads(project):
    root, _ = project
    out = root / "out" / "deploy.zip"
    assert package.main(["azure", "--out", str(out)]) == 0

    assert _names(out) == {
        "server.py", "requirements.txt", "constraints.txt", "version.txt", "app/main.py",
        "app/notes/fonts/LiberationSans-Regular.ttf", "templates/XBRL-template-MFRS/Company/01-SOFP-CuNonCu.xlsx",
        "web/dist/index.html", "web/dist/assets/index-1.js",
    }
    with zipfile.ZipFile(out) as zf:
        assert zf.read("version.txt").decode().strip() == "abc1234"


def test_a_stray_hidden_file_in_the_built_app_never_ships(project):
    root, _ = project
    (root / "web/dist/.env").write_text("SECRET=1")
    out = root / "deploy.zip"
    assert package.main(["azure", "--out", str(out)]) == 0
    assert not {n for n in _names(out) if n.rsplit("/", 1)[-1].startswith(".")}


def test_the_azure_package_needs_the_built_browser_app(project, capsys):
    root, _ = project
    (root / "web/dist/index.html").unlink()
    assert package.main(["azure", "--out", str(root / "deploy.zip")]) == 1
    assert "not built" in capsys.readouterr().err
    assert not (root / "deploy.zip").exists()


def test_files_git_does_not_track_stop_the_azure_package(project, capsys):
    root, untracked = project
    untracked.append("app/new_module.py")
    assert package.main(["azure", "--out", str(root / "deploy.zip")]) == 1
    assert "app/new_module.py" in capsys.readouterr().err


def test_untracked_files_outside_the_package_do_not_stop_it(project):
    root, untracked = project
    untracked.extend([".claude/settings.json", "prototypes/draft.html"])
    assert package.main(["azure", "--out", str(root / "deploy.zip")]) == 0


def test_the_veracode_package_holds_source_and_dependency_lists_only(project):
    root, _ = project
    out = root / "scan.zip"
    assert package.main(["veracode", "--out", str(out)]) == 0
    assert _names(out) == {
        "server.py", "requirements.txt", "constraints.txt", "app/main.py", "scripts/package.py",
        "web/package.json", "web/package-lock.json", "web/src/App.tsx", ".env.example", "README.md",
    }


def test_the_veracode_package_can_include_the_tests(project):
    root, _ = project
    out = root / "scan.zip"
    assert package.main(["veracode", "--include-tests", "--out", str(out)]) == 0
    assert {"tests/test_x.py", "web/src/App.test.tsx"} <= _names(out)


def test_a_secrets_file_never_enters_either_package():
    for rel in (".env", "app/.env", ".env.production"):
        assert not package.azure_keeps(rel)
        assert not package.veracode_keeps(rel, include_tests=True)


# The start scripts' step cache ------------------------------------------------------------------

@pytest.fixture()
def web(tmp_path, monkeypatch):
    for rel in ("requirements.txt", "constraints.txt", "web/package.json", "web/package-lock.json",
                "web/index.html", "web/src/main.tsx"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(rel)
    monkeypatch.setattr(startup_cache, "ROOT", tmp_path)
    monkeypatch.setattr(startup_cache, "WEB", tmp_path / "web")
    monkeypatch.setattr(startup_cache, "DIST", tmp_path / "web" / "dist")
    return tmp_path


def test_a_step_runs_again_only_when_its_inputs_change(web):
    assert startup_cache.main(["check", "pip"]) == 1
    assert startup_cache.main(["mark", "pip"]) == 0
    assert startup_cache.main(["check", "pip"]) == 0
    (web / "requirements.txt").write_text("fastapi\nnew-package\n")
    assert startup_cache.main(["check", "pip"]) == 1


def test_a_build_with_a_missing_file_is_built_again(web):
    dist = web / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/assets/index-1.js"></script>')
    (dist / "assets" / "index-1.js").write_text("js")
    assert startup_cache.main(["mark", "build"]) == 0
    assert startup_cache.main(["check", "build"]) == 0
    (dist / "assets" / "index-1.js").unlink()
    assert startup_cache.main(["check", "build"]) == 1


def test_an_unknown_step_is_an_error(web):
    assert startup_cache.main(["check", "everything"]) == 2
