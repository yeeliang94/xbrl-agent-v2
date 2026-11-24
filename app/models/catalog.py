"""The list of models for `GET /api/models`.

Asks each provider (or the gateway) for its models when its key is present.
Always includes gpt-6-luna and gpt-6.1-terra. A model whose key is missing is
listed as unavailable. Answers are kept for five minutes.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.models import factory

logger = logging.getLogger(__name__)

ALWAYS_LISTED = ("gpt-6-luna", "gpt-6.1-terra")
CACHE_SECONDS = 300

# OpenAI lists every model the key can reach; keep the chat models.
_NOT_CHAT = ("audio", "realtime", "transcribe", "tts", "image", "embedding", "search")

_cache: dict[str, tuple[float, list[dict]]] = {}

# List prices in US dollars per million tokens: (input, cached input, output),
# keyed by the bare model name. Source: v1 `config/models.json`. The GPT-6
# Luna price is OpenAI's list price as v1 checked it on 25 September 2026;
# v1 marks it unconfirmed, and the enterprise gateway may bill at its own
# rate. The Claude prices are Anthropic's list prices from the same file.
# A model not listed here has no estimated cost (null), never zero.
PRICES_PER_MILLION: dict[str, tuple[float, float, float]] = {
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "claude-sonnet-4-6": (3.00, 0.30, 15.00),
    "claude-opus-4-7": (5.00, 0.50, 25.00),
    "claude-opus-4-6": (5.00, 0.50, 25.00),
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
}


def price(model_id: str) -> tuple[float, float, float] | None:
    """(input, cached input, output) dollars per million tokens, or None."""
    return PRICES_PER_MILLION.get(factory.bare_name(model_id).lower())


def label(model_id: str) -> str:
    """`gpt-6.1-terra` -> `GPT-6.1 Terra`; `claude-sonnet-4-6` -> `Claude Sonnet 4.6`."""
    bare = factory.bare_name(model_id)
    if bare.lower().startswith("gpt-"):
        version, _, rest = bare[4:].partition("-")
        words = " ".join(w.capitalize() for w in rest.split("-") if w)
        return f"GPT-{version} {words}".strip()
    words, numbers = [], []
    for part in bare.split("-"):
        (numbers if part.isdigit() else words).append(part)
    text = " ".join(w.capitalize() for w in words)
    return f"{text} {'.'.join(numbers)}".strip() if numbers else text


def _entry(model_id: str) -> dict:
    provider = factory.provider_of(model_id)
    return {
        "id": factory.short_id(model_id),
        "provider": provider,
        "family": factory.family_of(model_id),
        "label": label(model_id),
        "available": factory.has_key(provider),
    }


async def _ids_from(provider: str) -> list[str]:
    client = factory.provider_client(provider)
    ids: list[str] = []
    async for model in client.models.list():
        ids.append(model.id)
    return ids


def _keep(model_id: str, provider: str) -> bool:
    if factory.provider_of(model_id) != provider:
        return False
    return provider != "openai" or not any(w in model_id.lower() for w in _NOT_CHAT)


async def fetch_ids() -> list[str]:
    """Model ids the providers report. A provider that cannot be reached is
    skipped with a warning; the always-listed models still appear."""
    ids: list[str] = []
    if factory.current_setup() == "gateway":
        if factory.gateway_key():
            try:
                reported = await _ids_from("openai")
                ids += [m for m in reported if factory.provider_of(m) != "unknown"
                        and _keep(m, factory.provider_of(m))]
            except Exception as exc:  # noqa: BLE001 - listing must not break Settings
                logger.warning("Could not list the gateway's models: %s", exc)
        return ids
    for provider in ("openai", "anthropic"):
        if not factory.has_key(provider):
            continue
        try:
            ids += [m for m in await _ids_from(provider) if _keep(m, provider)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list %s models: %s", provider, exc)
    return ids


async def list_models() -> list[dict[str, Any]]:
    key = factory.current_setup()
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    entries: dict[str, dict] = {}
    for model_id in await fetch_ids():
        entry = _entry(model_id)
        entries.setdefault(entry["id"], entry)
    for model_id in ALWAYS_LISTED:
        if model_id not in entries:
            entries[model_id] = _entry(model_id)
    models = sorted(entries.values(), key=lambda m: (m["provider"], m["id"]))
    _cache[key] = (time.monotonic(), models)
    return models


def clear_cache() -> None:
    _cache.clear()
