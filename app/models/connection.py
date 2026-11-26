"""The Settings page's "Test connection": one tiny call to each model the app
is set to use, sent the way the app sends its own calls.

This is what `scripts/check_gateway.py` does in its steps 1, 1b and 2 (a GPT
call, the same with the app's extra settings, a Claude call), but through
`factory`, so it tests the very connection the agents use. The input is a
made-up word; no document data is sent. Each call is recorded in
`model_calls`, failed ones included.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic_ai.exceptions import ModelQuotaExceededError

from app.models import factory, usage

logger = logging.getLogger(__name__)

SOURCE = "connection_test"
TIMEOUT_SECONDS = 60
PROMPT = "Reply with the single word: ready"


async def ask(model_id: str) -> Any:
    """One call to `model_id` on the current set-up. Returns the model's response. Tests replace this."""
    from pydantic_ai.direct import model_request
    from pydantic_ai.messages import ModelRequest

    return await model_request(factory.build_model(model_id), [ModelRequest.user_text_prompt(PROMPT)],
                               model_settings=factory.model_settings(model_id))


class EmptyAnswer(Exception):
    """The call went through but the model said nothing."""


def failure_sentence(exc: BaseException) -> str:
    """One plain sentence for a failed call. Never the provider's own text, which can carry the gateway address."""
    if isinstance(exc, EmptyAnswer):
        return "The model answered with nothing."
    if isinstance(exc, ValueError):
        return str(exc)   # the factory's own sentence, such as a missing key
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"The model service did not answer within {TIMEOUT_SECONDS} seconds."
    if isinstance(exc, ModelQuotaExceededError):
        return "The model account has no credit left, so an admin needs to add credit before trying again."
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "The model service says this key may not use this model."
    if status == 404:
        return "The model service does not know this model."
    if status == 429:
        return "The model service is busy or over its limit."
    name = type(exc).__name__
    if "Connect" in name or "Timeout" in name:
        return "The model service could not be reached."
    if status is not None:
        return f"The model service refused the request (error {status})."
    return "The call stopped on an unexpected error. The server log has the detail."


async def _check_one(model_id: str) -> dict:
    started = time.monotonic()
    logger.info("Connection test of %s started.", model_id)
    try:
        response = await asyncio.wait_for(ask(model_id), TIMEOUT_SECONDS)
        seconds = time.monotonic() - started
        if not any(getattr(part, "content", "") for part in getattr(response, "parts", [])):
            raise EmptyAnswer()
    except Exception as exc:  # noqa: BLE001 - every model reports its own failure
        seconds = time.monotonic() - started
        logger.warning("Connection test of %s failed.", model_id, exc_info=True)
        usage.record_call(None, SOURCE, model_id, duration_ms=int(seconds * 1000),
                          error=f"{type(exc).__name__}: {exc}")
        return {"model": model_id, "ok": False, "seconds": round(seconds, 1), "sentence": failure_sentence(exc)}
    usage.record_call(None, SOURCE, model_id, getattr(response, "usage", None), duration_ms=int(seconds * 1000))
    logger.info("Connection test of %s finished in %.1f seconds.", model_id, seconds)
    return {"model": model_id, "ok": True, "seconds": round(seconds, 1),
            "sentence": f"Answered in {seconds:.1f} seconds"}


async def check_models(model_ids: list[str]) -> list[dict]:
    """One result per distinct model, in the order given, all asked at the same time."""
    distinct = list(dict.fromkeys(model_ids))
    return list(await asyncio.gather(*(_check_one(model_id) for model_id in distinct)))
