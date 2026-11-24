"""Safe paths, atomic writes, and serving the built browser app."""
from __future__ import annotations

import errno
import os

import pytest

from app import main
from app.utils import atomic_io
from app.utils.paths import UnsafePathError, output_dir, safe_entry_path, safe_path, safe_segment


def test_safe_path_refuses_paths_outside_the_approved_folders():
    with pytest.raises(UnsafePathError):
        safe_path("/etc/passwd")
    with pytest.raises(UnsafePathError):
        safe_path(output_dir() / ".." / ".." / ".." / ".." / ".." / ".." / ".." / "etc" / "hosts")
    with pytest.raises(UnsafePathError):
        safe_path("output/a\x00b")
    assert safe_path(output_dir() / "x.json") == (output_dir() / "x.json").resolve()


def test_a_symbolic_link_cannot_step_outside(tmp_path):
    output_dir().mkdir(parents=True, exist_ok=True)
    link = output_dir() / "escape"
    os.symlink("/etc", link)
    with pytest.raises(UnsafePathError):
        safe_path(link / "hosts")
    # Deleting the link itself is allowed and leaves its target alone.
    assert safe_entry_path(link) == link


def test_safe_segment_refuses_traversal():
    assert safe_segment("run-1") == "run-1"
    for bad in ("", ".", "..", "a/b", "a\\b", "../x"):
        with pytest.raises(ValueError):
            safe_segment(bad)


def test_atomic_write_replaces_the_whole_file():
    target = output_dir() / "data" / "file.json"
    atomic_io.write_json_atomic(target, {"a": 1})
    atomic_io.write_json_atomic(target, {"a": 2})
    assert target.read_text(encoding="utf-8").replace(" ", "").replace("\n", "") == '{"a":2}'
    assert [p.name for p in target.parent.iterdir()] == ["file.json"]


def test_atomic_write_refuses_an_unsafe_target():
    with pytest.raises(UnsafePathError):
        atomic_io.write_text_atomic("/etc/xbrl-test.txt", "x")


def test_replace_retries_a_transient_windows_lock(monkeypatch):
    source = output_dir() / "pending.txt"
    destination = output_dir() / "current.txt"
    output_dir().mkdir(parents=True, exist_ok=True)
    source.write_text("new", encoding="utf-8")
    real_replace = atomic_io.os.replace
    attempts = []

    def flaky(src, dst):
        attempts.append(1)
        if len(attempts) == 1:
            error = PermissionError(errno.EACCES, "Access is denied")
            error.winerror = 32
            raise error
        real_replace(src, dst)

    monkeypatch.setattr(atomic_io.os, "replace", flaky)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _: None)
    atomic_io.replace_with_retry(source, destination)
    assert len(attempts) == 2 and destination.read_text(encoding="utf-8") == "new"


def test_built_browser_app_is_served_with_single_page_fallback(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(main, "WEB_DIST", dist)
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/runs/12").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/../../etc/passwd").text == "<html>app</html>"
    assert client.get("/api/nothing-here").status_code == 401


def test_a_plain_message_when_the_browser_app_is_not_built(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "WEB_DIST", tmp_path / "missing")
    response = client.get("/")
    assert response.status_code == 200 and "not been built" in response.text
