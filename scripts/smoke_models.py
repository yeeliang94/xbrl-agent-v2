"""Live check for the Mac: one small GPT call and one small Claude call, each
through the app's own agent loop with the provider's code tool. Costs a few
cents. Prints PASS, FAIL or SKIPPED per provider.

  venv/bin/python scripts/smoke_models.py [--gpt-model gpt-6-luna] [--claude-model claude-sonnet-4-6]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from app import db  # noqa: E402
from app.agents.loop import COMPLETED, AgentSpec, run_agent  # noqa: E402
from app.models import factory  # noqa: E402

PROMPT = "Use the code tool to calculate 1234 * 5678. Reply with the number only."
EXPECTED = "7006652"


async def check(provider: str, model_id: str) -> str:
    if not factory.has_key(provider):
        print(f"SKIPPED  {provider} ({model_id}): no key for this provider in .env")
        return "skipped"
    spec = AgentSpec(
        name=f"smoke-{provider}", model_id=model_id,
        instructions="You are a careful calculator. Always run code to calculate.",
        max_steps=6, code_tool=True,
    )
    outcome = await run_agent(spec, PROMPT)
    answer = str(outcome.output or "").replace(",", "")
    ok = outcome.status == COMPLETED and outcome.code_tool_used and EXPECTED in answer
    detail = (
        f"status {outcome.status}, code step {'yes' if outcome.code_tool_used else 'no'}, "
        f"answer {'right' if EXPECTED in answer else 'wrong'}, "
        f"{outcome.requests} request(s), {outcome.input_tokens} in / {outcome.output_tokens} out tokens"
    )
    if outcome.status != COMPLETED:
        detail += f", {outcome.message}" + (f" ({outcome.error})" if outcome.error else "")
    print(f"{'PASS' if ok else 'FAIL'}  {provider} ({model_id}): {detail}")
    print(f"         transcript: {outcome.transcript_path}")
    return "pass" if ok else "fail"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpt-model", default="gpt-6-luna")
    parser.add_argument("--claude-model", default="claude-sonnet-4-6")
    args = parser.parse_args()
    db.init_db()
    print(f"Set-up: {factory.current_setup()}")
    results = [await check("openai", args.gpt_model), await check("anthropic", args.claude_model)]
    return 1 if "fail" in results else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(asyncio.run(main()))
