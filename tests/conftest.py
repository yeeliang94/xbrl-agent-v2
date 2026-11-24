"""Shared test set-up. Every test gets its own output folder and database, and
none of the developer's `.env` values."""
from __future__ import annotations

import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.db import location
from app.auth import lockout, passwords, store
from app.models import catalog

_ENV_NAMES = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROXY_URL", "LLM_PROXY_API_KEY",
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "SESSION_SECRET", "AUTH_MODE", "WEBSITE_SITE_NAME",
    "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD", "BOOTSTRAP_ADMIN_NAME",
)

PASSWORD = "correct-horse-1"


@pytest.fixture(scope="session")
def catalogue_db(tmp_path_factory):
    """One database with the template catalogue built, made once per test run."""
    from app.catalog import loader

    folder = tmp_path_factory.mktemp("catalogue")
    patch = pytest.MonkeyPatch()
    patch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    loader.load_catalogue()
    path = db.db_path()
    patch.undo()
    snapshot = folder / "catalogue.db"
    with sqlite3.connect(path) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
    return snapshot


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, catalogue_db):
    """Each test starts from a copy of the catalogue database, so start-up skips the rebuild."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(tmp_path / "output"))
    # A test that sets WEBSITE_SITE_NAME opens the same database, never the machine's /tmp one.
    monkeypatch.setattr(location, "AZURE_LIVE_DIR", tmp_path / "output")
    lockout.reset_all()
    catalog.clear_cache()
    (tmp_path / "output").mkdir()
    shutil.copyfile(catalogue_db, db.db_path())
    db.init_db()
    yield


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app(start_worker=False)) as test_client:
        yield test_client


def make_user(email: str, *, is_admin: bool = False, password: str = PASSWORD,
              must_change_password: bool = False, name: str = "") -> None:
    with db.connect() as conn:
        store.create_user(conn, email, name or email.split("@")[0], passwords.hash_password(password),
                          is_admin=is_admin, must_change_password=must_change_password)


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login/password", json={"email": email, "password": password})


# Runs and figures ---------------------------------------------------------

OWNER = "ana@firm.com"


def make_run(statements=(("SOFP", "CuNonCu"),), *, standard="MFRS", level="Company",
             first_statements=False, owner=OWNER) -> int:
    """A run with these confirmed layouts. Creates the owner account if needed."""
    from app.runs import store as runs

    with db.connect() as conn:
        if store.fetch_user(conn, owner) is None:
            store.create_user(conn, owner, owner.split("@")[0], passwords.hash_password(PASSWORD))
        return runs.create_run(conn, company="Test Sdn. Bhd.", year=2025, standard=standard, level=level,
                               owner_email=owner, statements=statements, first_statements=first_statements)


def field(template_id: str, sheet: str, row: int) -> str:
    """The concept at one template row (face rows give the sub-sheet total they show)."""
    with db.connect() as conn:
        found = conn.execute("SELECT canonical_target_id FROM template_slots WHERE template_id = ? "
                             "AND sheet = ? AND row = ?", (template_id, sheet, row)).fetchone()
    assert found, (template_id, sheet, row)
    return found[0]


def field_by_label(template_id: str, label: str, nth: int = 0, *, matrix_col=None) -> str:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT concept_uuid FROM concept_nodes WHERE template_id = ? AND is_current = 1 "
            "AND LOWER(LTRIM(canonical_label, '*')) = LOWER(?) AND COALESCE(matrix_col, '') = ? "
            "ORDER BY render_sheet, render_row", (template_id, label, matrix_col or "")).fetchall()
    assert len(rows) > nth, (template_id, label)
    return rows[nth][0]
