"""The job queue: run, fail, retry, maximum attempts and start-up recovery."""
from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.jobs import queue, worker


async def test_a_job_runs_to_done():
    job_id = queue.enqueue("test.echo")
    assert await worker.run_once(retry_delay=0) is True
    job = queue.get(job_id)
    assert job.status == "done" and job.attempts == 1 and job.last_error is None
    assert await worker.run_once(retry_delay=0) is False


async def test_a_failed_job_retries_then_succeeds():
    job_id = queue.enqueue("test.echo", {"fail_attempts": 1}, max_attempts=3)
    await worker.run_once(retry_delay=0)
    job = queue.get(job_id)
    assert job.status == "retry" and job.attempts == 1
    assert "Planned failure" in job.last_error
    await worker.run_once(retry_delay=0)
    job = queue.get(job_id)
    assert job.status == "done" and job.attempts == 2


async def test_a_job_stops_at_its_maximum_attempts():
    job_id = queue.enqueue("test.echo", {"fail_attempts": 99}, max_attempts=2)
    await worker.run_once(retry_delay=0)
    await worker.run_once(retry_delay=0)
    job = queue.get(job_id)
    assert job.status == "failed" and job.attempts == 2
    assert await worker.run_once(retry_delay=0) is False


async def test_a_retry_waits_for_its_delay():
    job_id = queue.enqueue("test.echo", {"fail_attempts": 1})
    await worker.run_once(retry_delay=60)
    assert await worker.run_once() is False
    assert queue.get(job_id).status == "retry"


async def test_a_job_with_no_handler_fails_with_a_reason():
    job_id = queue.enqueue("no.such.handler", max_attempts=1)
    await worker.run_once(retry_delay=0)
    job = queue.get(job_id)
    assert job.status == "failed" and "No handler" in job.last_error


def test_restart_recovery_leaves_nothing_working():
    retryable = queue.enqueue("test.echo", max_attempts=2)
    last_try = queue.enqueue("test.echo", max_attempts=1)
    assert queue.claim().id == retryable
    assert queue.claim().id == last_try
    assert queue.recover_after_restart() == 2
    for job_id in (retryable, last_try):
        job = queue.get(job_id)
        assert job.status == "retry" and job.attempts == 0
        assert job.last_error == queue.RESTART_ERROR


async def test_a_job_interrupted_on_its_last_attempt_can_still_run():
    job_id = queue.enqueue("test.echo", max_attempts=1)
    queue.claim()
    queue.recover_after_restart()
    assert await worker.run_once(retry_delay=0) is True
    job = queue.get(job_id)
    assert job.status == "done" and job.attempts == 1


_CALLS: list[int] = []


@worker.handler("test.counted")
def _counted(job) -> None:
    _CALLS.append(job.id)
    if job.payload.get("fail"):
        raise RuntimeError("Planned failure.")


@pytest.mark.parametrize("save, payload, status", [
    ("complete", {}, "done"),
    ("fail", {"fail": True}, "retry"),
])
async def test_a_database_error_while_saving_the_outcome_is_retried(monkeypatch, save, payload, status):
    _CALLS.clear()
    monkeypatch.setattr(worker, "SAVE_RETRY_SECONDS", 0)
    real = getattr(queue, save)
    errors = [sqlite3.OperationalError("database is locked")]

    def flaky(*args, **kwargs):
        if errors:
            raise errors.pop()
        return real(*args, **kwargs)

    monkeypatch.setattr(queue, save, flaky)
    job_id = queue.enqueue("test.counted", payload, max_attempts=3)
    await worker.run_once(retry_delay=0)
    assert queue.get(job_id).status == status
    assert _CALLS == [job_id]  # the handler ran once


def test_the_app_recovers_on_start_and_its_worker_runs_the_job():
    from app.main import create_app

    job_id = queue.enqueue("test.echo")
    queue.claim()  # left "working", as if the server had crashed mid-job
    with TestClient(create_app()):
        deadline = time.monotonic() + 5
        while queue.get(job_id).status != "done" and time.monotonic() < deadline:
            time.sleep(0.05)
    job = queue.get(job_id)
    assert job.status == "done" and job.attempts == 1  # the interrupted attempt is not counted
