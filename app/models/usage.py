"""Tokens and an estimated cost for every model call, in the `model_calls` table.

Input tokens are counted the way the providers report them: all input,
cached input included. Cached input is priced at its own lower rate. The
cost is an estimate from list prices (`catalog.PRICES_PER_MILLION`); it is
null when the model's price is not known.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app import db
from app.models import catalog
from app.utils.masking import mask

logger = logging.getLogger(__name__)


def cost_usd(model_id: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> Optional[float]:
    rates = catalog.price(model_id)
    if rates is None:
        return None
    fresh = max(input_tokens - cached_tokens, 0)
    return (fresh * rates[0] + cached_tokens * rates[1] + output_tokens * rates[2]) / 1_000_000


def tokens(usage: Any) -> tuple[int, int, int]:
    """(input, cached, output) from a PydanticAI usage object."""
    return (int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "cache_read_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0))


def record_call(run_id: Optional[int], source: str, model_id: str, usage: Any = None, *,
                page: Optional[int] = None, duration_ms: Optional[int] = None,
                error: Optional[str] = None, agent: Optional[str] = None) -> Optional[float]:
    """Store one model call: its tokens, estimated cost, duration and, for a
    failed call, the full error with any secret masked. `agent` names the agent
    run as a person says it, for the run's cost. Returns the cost. A failure to
    record is logged and never ends the work."""
    inp, cached, out = tokens(usage) if usage is not None else (0, 0, 0)
    cost = cost_usd(model_id, inp, cached, out)
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO model_calls(run_id, source, page, model, input_tokens, cached_tokens, output_tokens, "
                "cost_usd, duration_ms, error, created_at, agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, source, page, model_id, inp, cached, out, cost, duration_ms,
                 mask(error) if error else error, db.now(), agent))
    except Exception:  # noqa: BLE001 - recording usage must not end a run
        logger.warning("Could not record a model call's usage", exc_info=True)
    return cost


def run_totals(run_id: int, source: Optional[str] = None) -> dict:
    """Calls, tokens and estimated cost for one run, optionally for one source."""
    sql = ("SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
           "COALESCE(SUM(cached_tokens), 0) AS cached_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
           "COALESCE(SUM(cost_usd), 0) AS cost_usd, SUM(cost_usd IS NULL) AS unpriced "
           "FROM model_calls WHERE run_id = ?")
    params: list = [run_id]
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    with db.connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return {k: row[k] for k in row.keys()}
