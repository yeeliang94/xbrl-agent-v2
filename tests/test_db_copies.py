"""Saved database copies on Azure (app/db/copies.py, app/db/location.py). Ported from v1's tests.

On Azure the live SQLite file sits on the container's own disk, which is wiped
when the container is replaced. Runs, figures and accounts survive only
through the copies saved on /home, so these tests check what a restart brings back.
"""
from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import copies, location
from tests.conftest import PASSWORD


def _live(tmp_path: Path, name: str = "container") -> Path:
    """A small database with the table a real copy must hold."""
    path = tmp_path / name / "xbrl.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS runs (name TEXT)")
    return path


def _add_run(db: Path, name: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO runs (name) VALUES (?)", (name,))
    conn.close()


def _runs(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM runs ORDER BY rowid")]
    finally:
        conn.close()


def _saved(folder: Path) -> list[Path]:
    return sorted(folder.glob("xbrl-v2-*.db.gz"))


@pytest.fixture()
def folder(tmp_path):
    return tmp_path / "v2-db-copies"


@pytest.fixture(autouse=True)
def _no_saver_left():
    yield
    copies.stop()


def _saver(live: Path, folder: Path, me: str, **kw) -> copies.CopySaver:
    copies.claim(folder, me)
    return copies.CopySaver(live, folder, me, **kw)


def _refuse(*_a, **_k):
    raise OSError("network drive unavailable")


def test_a_copy_is_saved_only_after_the_database_changed(tmp_path, folder):
    live = _live(tmp_path)
    saver = _saver(live, folder, "a")

    assert saver.save_if_changed() is False
    _add_run(live, "first")
    assert saver.save_if_changed() is True
    assert saver.save_if_changed() is False
    assert len(_saved(folder)) == 1
    assert saver.status()["last_saved_at"] is not None


def test_a_restart_brings_back_the_newest_good_copy(tmp_path, folder):
    live = _live(tmp_path, "old")
    saver = _saver(live, folder, "a")
    _add_run(live, "finished")
    saver.save_if_changed()
    good = _saved(folder)[0]
    damaged = folder / "xbrl-v2-29991231T000000.000000Z-a.db.gz"   # newer, but half lost
    damaged.write_bytes(gzip.compress(gzip.decompress(good.read_bytes())[:2048]))

    fresh = tmp_path / "new" / "xbrl.db"
    assert copies.restore(fresh, folder) == "restored"
    assert _runs(fresh) == ["finished"]


def test_the_previous_owners_copy_wins_over_a_late_copy_from_an_older_container(tmp_path, folder):
    older, newer = _live(tmp_path, "older"), _live(tmp_path, "newer")
    _add_run(older, "older")
    _add_run(newer, "newer")
    _saver(newer, folder, "newer", dirty=True).save_if_changed()
    late = copies.CopySaver(older, folder, "older", dirty=True)   # lands one copy after the take-over
    copies.claim(folder, "older")
    late.save_if_changed()
    copies.claim(folder, "newer")

    restored = tmp_path / "next" / "xbrl.db"
    copies.restore(restored, folder)
    assert _runs(restored) == ["newer"]


def test_a_container_that_lost_ownership_saves_nothing(tmp_path, folder, caplog):
    live = _live(tmp_path)
    saver = _saver(live, folder, "old")
    copies.claim(folder, "new")
    _add_run(live, "late")

    with caplog.at_level(logging.WARNING, logger="app.db.copies"):
        assert saver.save_if_changed() is False
        assert saver.save_if_changed() is False
    assert _saved(folder) == []
    assert saver.status()["saving"] is False
    assert sum("stops saving" in r.message for r in caplog.records) == 1


def test_a_copy_is_abandoned_when_ownership_moves_while_it_is_written(tmp_path, folder, monkeypatch):
    live = _live(tmp_path)
    saver = _saver(live, folder, "old")
    _add_run(live, "x")
    answers = iter(["old", "new"])   # the owner before writing, then after
    monkeypatch.setattr(copies, "read_owner", lambda _folder: next(answers))

    assert saver.save_if_changed() is False
    assert list(folder.glob("xbrl-v2-*")) == []


def test_only_the_newest_copies_are_kept(tmp_path, folder):
    live = _live(tmp_path)
    saver = _saver(live, folder, "a")
    for i in range(copies.KEEP + 2):
        _add_run(live, str(i))
        assert saver.save_if_changed()
    assert len(_saved(folder)) == copies.KEEP
    fresh = tmp_path / "fresh" / "xbrl.db"
    copies.restore(fresh, folder)
    assert len(_runs(fresh)) == copies.KEEP + 2


def test_a_live_database_already_on_this_disk_is_kept(tmp_path, folder):
    live = _live(tmp_path)
    copies.restore(live, folder)
    copies.start_saving(live, folder).save_if_changed()
    copies.stop()
    _add_run(live, "after-last-copy")   # the app restarted before the next copy

    assert copies.restore(live, folder) == "kept"
    assert _runs(live) == ["after-last-copy"]


def test_a_database_left_by_a_start_that_failed_is_replaced_by_the_copies(tmp_path, folder):
    serving = _live(tmp_path, "serving")
    copies.claim(folder, "serving")
    _add_run(serving, "saved-by-the-serving-container")
    copies.CopySaver(serving, folder, "serving", dirty=True).save_if_changed()
    stale = _live(tmp_path, "retrying")   # restored an older state, then failed before claiming
    _add_run(stale, "older")

    assert copies.restore(stale, folder) == "restored"
    assert _runs(stale) == ["saved-by-the-serving-container"]


def test_an_empty_or_damaged_copy_is_skipped(tmp_path, folder):
    live = _live(tmp_path)
    saver = _saver(live, folder, "a")
    _add_run(live, "real")
    saver.save_if_changed()
    (folder / "xbrl-v2-29991231T000000.000000Z-a.db.gz").write_bytes(gzip.compress(b""))
    good = gzip.compress(b"x" * 1000)
    (folder / "xbrl-v2-29991231T000001.000000Z-a.db.gz").write_bytes(good[:10] + b"\xff" * 20 + good[30:])

    fresh = tmp_path / "fresh" / "xbrl.db"
    assert copies.restore(fresh, folder) == "restored"
    assert _runs(fresh) == ["real"]


def test_no_copies_starts_an_empty_database(tmp_path, folder):
    assert copies.restore(tmp_path / "x" / "xbrl.db", folder) == "new"


def test_copies_that_cannot_be_restored_stop_startup(tmp_path, folder):
    folder.mkdir()
    (folder / "xbrl-v2-20261123T000000.000000Z-a.db.gz").write_bytes(b"not a database")
    with pytest.raises(RuntimeError, match="could be restored"):
        copies.restore(tmp_path / "x" / "xbrl.db", folder)


def test_v1s_copies_are_never_read(tmp_path, folder):
    """v2 runs on v1's App Service: a v1 copy is a different database and must never be restored."""
    folder.mkdir()
    v1 = _live(tmp_path, "v1")
    with open(v1, "rb") as src:
        (folder / "xbrl_agent-20261123T000000.000000Z-v1box.db.gz").write_bytes(gzip.compress(src.read()))
    assert copies.restore(tmp_path / "x" / "xbrl.db", folder) == "new"
    assert location.COPIES_FOLDER != "db-copies"   # v1's folder, with v1's owner.json


def test_saving_that_falls_behind_is_reported(tmp_path, folder, monkeypatch, caplog):
    live = _live(tmp_path)
    saver = _saver(live, folder, "a")
    monkeypatch.setattr(copies, "STALE_S", 0.0)
    monkeypatch.setattr(copies.gzip, "open", _refuse)
    _add_run(live, "x")

    with caplog.at_level(logging.ERROR, logger="app.db.copies"):
        assert saver.save_if_changed() is False
    assert saver.status()["stale"] is True
    assert any("no copy saved" in r.message for r in caplog.records)


def test_an_unreadable_owner_file_skips_one_save_but_not_the_rest(tmp_path, folder):
    live = _live(tmp_path)
    saver = _saver(live, folder, "a")
    _add_run(live, "x")
    (folder / copies.OWNER_FILE).write_text("{half-writ", encoding="utf-8")
    assert saver.save_if_changed() is False
    assert saver.status()["saving"] is True

    copies.claim(folder, "a")   # the drive answers again
    assert saver.save_if_changed() is True


def test_stopping_saves_the_last_changes(tmp_path, folder):
    live = _live(tmp_path)
    copies.claim(folder, "a")
    saver = copies.CopySaver(live, folder, "a", interval_s=3600)
    saver.start()
    _add_run(live, "just-before-stop")
    saver.stop()
    restored = tmp_path / "after" / "xbrl.db"
    copies.restore(restored, folder)
    assert _runs(restored) == ["just-before-stop"]


def test_a_failure_before_the_claim_leaves_saving_with_the_old_owner(tmp_path, folder, monkeypatch):
    live = _live(tmp_path)
    copies.claim(folder, "serving")
    copies.restore(live, folder)
    monkeypatch.setattr(copies, "CopySaver", _refuse)
    with pytest.raises(OSError):
        copies.start_saving(live, folder)
    assert copies.read_owner(folder) == "serving"


def test_a_failure_after_the_claim_hands_saving_back(tmp_path, folder):
    live = _live(tmp_path)
    copies.claim(folder, "serving")
    copies.restore(live, folder)
    (live.parent / copies.SAVED_BY_FILE).mkdir()   # the local note cannot be written
    with pytest.raises(OSError):
        copies.start_saving(live, folder)
    assert copies.read_owner(folder) == "serving"


def test_a_claim_that_fails_does_not_make_the_next_start_discard_this_disk(tmp_path, folder, monkeypatch):
    live = _live(tmp_path)
    names = iter(["first-start", "retry"])
    monkeypatch.setattr(copies, "container_id", lambda: next(names))
    copies.restore(live, folder)
    copies.start_saving(live, folder).save_if_changed()
    copies.stop()
    _add_run(live, "after-last-copy")   # newer than every copy

    copies.restore(live, folder)
    monkeypatch.setattr(copies, "claim", _refuse)   # /home refuses the write
    with pytest.raises(OSError):
        copies.start_saving(live, folder)
    monkeypatch.undo()

    assert copies.restore(live, folder) == "kept"
    assert _runs(live) == ["after-last-copy"]


def test_a_finished_job_triggers_a_copy(tmp_path, folder):
    import asyncio

    from app.jobs import queue, worker

    live = _live(tmp_path)
    copies.claim(folder, "a")
    copies._saver = saver = copies.CopySaver(live, folder, "a", request_delay_s=0.0, interval_s=3600)
    saver.start()
    _add_run(live, "done")
    queue.enqueue("no-such-kind", max_attempts=1)
    asyncio.run(worker._run(queue.claim()))   # even a failed job asks for a copy
    deadline = time.monotonic() + 10
    while not _saved(folder) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _saved(folder), "no copy was saved after the job ended"


def test_on_azure_the_live_database_sits_on_the_containers_own_disk(monkeypatch, tmp_path):
    from app.utils.paths import output_dir

    monkeypatch.setattr(location, "AZURE_LIVE_DIR", Path("/tmp/xbrl-v2-live"))   # its real value; tests move it
    assert location.live_path() == output_dir() / "xbrl.db"
    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-prod")
    monkeypatch.setenv("XBRL_OUTPUT_DIR", "/home/data-v2")
    assert location.live_path() == Path("/tmp/xbrl-v2-live/xbrl.db")
    assert location.copies_dir().parts[-2:] == ("data-v2", "v2-db-copies")   # macOS resolves /home elsewhere


# The real start-up, on a pretend Azure container -----------------------------------------------

def _azure(tmp_path, monkeypatch, container: str) -> Path:
    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-test")
    monkeypatch.setenv("SESSION_SECRET", "s" * 64)
    monkeypatch.setattr(location, "AZURE_LIVE_DIR", tmp_path / container)
    return location.copies_dir()


def _seed(folder: Path, catalogue_db: Path, owner: str) -> None:
    """A copy holding the template catalogue, as v2's first start would have saved it."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(catalogue_db, "rb") as src, \
            gzip.open(folder / f"xbrl-v2-20261124T000000.000000Z-{owner}.db.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    copies.claim(folder, owner)


def test_azure_start_up_restores_first_claims_last_and_survives_a_new_container(
        tmp_path, monkeypatch, catalogue_db):
    from app.main import create_app

    folder = _azure(tmp_path, monkeypatch, "first-container")
    _seed(folder, catalogue_db, "previous")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "owner@firm.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)

    with TestClient(create_app(start_worker=False)) as client:
        health = client.get("/api/health").json()
        assert health["database_copy"]["saving"] is True
        assert copies.read_owner(folder) != "previous"
    assert copies.status() is None   # stopped at shut-down, after one last copy
    assert any(copies.read_owner(folder) in p.name for p in _saved(folder))

    # Azure replaces the container: a new, empty disk. The account comes back from the copies.
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL")
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD")
    _azure(tmp_path, monkeypatch, "second-container")
    with TestClient(create_app(start_worker=False)) as client:
        signed_in = client.post("/api/auth/login/password", json={"email": "owner@firm.com", "password": PASSWORD})
        assert signed_in.status_code == 200


def test_a_container_that_fails_to_start_leaves_saving_with_the_old_one(tmp_path, monkeypatch, catalogue_db):
    from app.main import create_app

    folder = _azure(tmp_path, monkeypatch, "failing-container")
    monkeypatch.delenv("SESSION_SECRET")   # this start-up stops
    _seed(folder, catalogue_db, "serving")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        with TestClient(create_app(start_worker=False)):
            pass
    assert copies.read_owner(folder) == "serving"


def test_saving_resumes_when_a_failed_start_up_hands_it_back(tmp_path, folder):
    live = _live(tmp_path)
    saver = _saver(live, folder, "serving")
    _add_run(live, "during-the-deploy")
    copies.claim(folder, "new")          # the new container claims saving...
    assert saver.save_if_changed() is False
    copies.claim(folder, "serving")      # ...then its start-up fails and hands it back
    assert saver.save_if_changed() is True
    assert saver.status()["saving"] is True
