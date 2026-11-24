"""Check what the enterprise gateway supports, step by step. For the Windows
enterprise machine. Adapted from the Document Agent's `proxy_check.py`.

It sends only a tiny made-up input (the numbers 41 and 1) and prints PASS or
FAIL per step, then a short summary. No document data is used or printed.

  Windows:      venv\\Scripts\\python.exe scripts\\check_gateway.py
  macOS/Linux:  venv/bin/python scripts/check_gateway.py

The gateway address and key come from LLM_PROXY_URL and LLM_PROXY_API_KEY in
the project's `.env`, as for the app (a real environment variable wins).

Steps:
  1  one GPT call (Responses interface)
  1b one GPT call with the extra settings the app sends for Luna and Terra
     (reasoning summary and prompt cache options)
  2  one Claude call (OpenAI-style chat)
  A  a sandbox the app creates: create, upload, run code, list, download, delete
  B  an automatic sandbox: upload through the Files interface, run code with
     the file attached, download the result

Standard library and the `openai` package only. `truststore` is used when
installed (it is in the app's environment) so the Windows certificate store,
which holds the company's certificates, is trusted.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[str, bool | None, str]] = []  # ok is None: not tried
SAMPLE = b"label,value\nsample,41\n"  # made up; no document data
EXPECTED = "42"
# Copied on purpose from app/models/factory.py (Luna and Terra settings): this script travels alone.
APP_GPT_EXTRAS = {
    # "context": what PydanticAI adds by itself for these models.
    "reasoning": {"summary": "auto", "context": "all_turns"},
    "extra_body": {"prompt_cache_options": {"ttl": "30m"}},
}


def record(step: str, ok: bool | None, detail: str = "") -> None:
    RESULTS.append((step, ok, detail))
    label = "SKIP" if ok is None else "PASS" if ok else "FAIL"
    print(f"{label}  {step}" + (f"  ({detail})" if detail else ""), flush=True)


def failed(step: str, error: Exception) -> None:
    # The error type and message only: never a request or response body.
    record(step, False, f"{type(error).__name__}: {str(error)[:300]}")


def load_env_file() -> None:
    """Read `.env` without overriding variables already set."""
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and value and not os.environ.get(name):
            os.environ[name] = value


def prepare_console_and_network() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        import truststore
    except ImportError:
        print("NOTE  truststore is not installed; using Python's own certificate list.")
        return
    truststore.inject_into_ssl()


def gateway_key() -> str:
    # Copied on purpose from app/models/factory.py (key order): this script travels alone.
    for name in ("LLM_PROXY_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return ""


def code_calls(response) -> list:
    return [item for item in response.output if getattr(item, "type", "") == "code_interpreter_call"]


def printed(calls) -> str:
    return "\n".join(
        getattr(o, "logs", "") or ""
        for call in calls for o in (call.outputs or []) if getattr(o, "type", "") == "logs"
    )


def run_code(client: OpenAI, model: str, container, task: str):
    return client.responses.create(
        model=model,
        instructions="Use the code tool to do exactly what is asked, then reply in one short sentence.",
        input=task,
        tools=[{"type": "code_interpreter", "container": container}],
        include=["code_interpreter_call.outputs"],
        store=False,
    )


TASK = (
    "Read the CSV file {where}. Add 1 to the number in the value column, write the new number "
    "alone to /mnt/data/result.txt, and print it."
)


def check_gpt(client: OpenAI, model: str) -> None:
    step = f"1  GPT call through the Responses interface ({model})"
    try:
        response = client.responses.create(model=model, input="Reply with the single word: ready", store=False)
        text = (response.output_text or "").strip()
        record(step, bool(text), "answered" if text else "empty answer")
    except Exception as error:  # noqa: BLE001 - every step reports its own failure
        failed(step, error)


def check_gpt_app_settings(client: OpenAI, model: str) -> None:
    step = f"1b GPT call with the app's extra settings: reasoning summary, prompt cache options ({model})"
    try:
        response = client.responses.create(
            model=model, input="Reply with the single word: ready", store=False, **APP_GPT_EXTRAS,
        )
        text = (response.output_text or "").strip()
        record(step, bool(text), "answered" if text else "empty answer")
    except Exception as error:  # noqa: BLE001
        failed(step, error)


def check_claude(client: OpenAI, model: str) -> None:
    step = f"2  Claude call as an OpenAI-style chat model ({model})"
    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=20,
        )
        text = (response.choices[0].message.content or "").strip()
        record(step, bool(text), "answered" if text else "empty answer")
    except Exception as error:  # noqa: BLE001
        failed(step, error)


def download_result(client: OpenAI, container_id: str) -> str | None:
    listing = list(client.containers.files.list(container_id, limit=100))
    match = [f for f in listing if f.path.endswith("/result.txt")]
    if not match:
        return None
    return client.containers.files.content.retrieve(match[0].id, container_id=container_id).read().decode().strip()


def part_a(client: OpenAI, model: str, model_on_create: bool) -> None:
    rest = ["A2", "A3", "A4", "A5"]
    step = "A1 create a sandbox (POST /containers)"
    try:
        extra = {"model": model} if model_on_create else None
        container = client.containers.create(
            name="xbrl-gateway-check", memory_limit="1g",
            expires_after={"anchor": "last_active_at", "minutes": 20}, extra_body=extra,
        )
        record(step, True)
    except Exception as error:  # noqa: BLE001
        failed(step, error)
        for name in rest:
            record(name, None, "not tried: needs A1")
        return
    try:
        step = "A2 upload a file into it"
        try:
            uploaded = client.containers.files.create(container.id, file=("sample.csv", SAMPLE))
            record(step, True)
        except Exception as error:  # noqa: BLE001
            failed(step, error)
            record("A3", None, "not tried: needs A2")
            record("A4", None, "not tried: needs A2")
            return
        step = "A3 run code in that sandbox"
        try:
            response = run_code(client, model, container.id, TASK.format(where=uploaded.path))
            calls = code_calls(response)
            ok = bool(calls) and EXPECTED in printed(calls)
            record(step, ok, f"{len(calls)} code call(s)" if ok else
                   "the model answered without the expected code result")
        except Exception as error:  # noqa: BLE001
            failed(step, error)
        step = "A4 download a file the code wrote"
        try:
            value = download_result(client, container.id)
            record(step, value == EXPECTED, "result matches" if value == EXPECTED else
                   "no result file" if value is None else "result does not match")
        except Exception as error:  # noqa: BLE001
            failed(step, error)
    finally:
        try:
            client.containers.delete(container.id)
            record("A5 delete the sandbox", True)
        except Exception as error:  # noqa: BLE001
            failed("A5 delete the sandbox", error)


def part_b(client: OpenAI, model: str) -> None:
    step = "B1 upload a file through the Files interface (POST /files)"
    try:
        uploaded = client.files.create(file=("sample.csv", SAMPLE), purpose="user_data")
        record(step, True)
    except Exception as error:  # noqa: BLE001
        failed(step, error)
        record("B2", None, "not tried: needs B1")
        record("B3", None, "not tried: needs B1")
        return
    try:
        step = "B2 run code in an automatic sandbox that holds the file"
        container_id = None
        try:
            auto = {"type": "auto", "memory_limit": "1g", "file_ids": [uploaded.id]}
            response = run_code(client, model, auto,
                                TASK.format(where="under /mnt/data (its name may carry a prefix)"))
            calls = code_calls(response)
            container_id = next((c.container_id for c in calls if getattr(c, "container_id", None)), None)
            ok = bool(calls) and EXPECTED in printed(calls)
            record(step, ok, f"{len(calls)} code call(s)" if ok else
                   "the model answered without the expected code result")
        except Exception as error:  # noqa: BLE001
            failed(step, error)
        step = "B3 download a file the code wrote"
        if container_id is None:
            record(step, None, "not tried: no sandbox id came back from B2")
        else:
            try:
                value = download_result(client, container_id)
                record(step, value == EXPECTED, "result matches" if value == EXPECTED else
                       "no result file" if value is None else "result does not match")
            except Exception as error:  # noqa: BLE001
                failed(step, error)
    finally:
        try:
            client.files.delete(uploaded.id)
        except Exception:  # noqa: BLE001 - clean-up only
            pass


def summary() -> int:
    passed = {step.split()[0] for step, ok, _ in RESULTS if ok}
    print("\nSummary")
    print(f"  GPT call:                      {'works' if '1' in passed else 'does not work'}")
    print(f"  GPT call with app settings:    {'works' if '1b' in passed else 'does not work'}")
    print(f"  Claude call:                   {'works' if '2' in passed else 'does not work'}")
    app_creates = {"A1", "A2", "A3", "A4", "A5"} <= passed
    print(f"  Sandbox, the app creates it:   {'works' if app_creates else 'does not work'}")
    automatic = {"B1", "B2"} <= passed
    files_out = "files come back" if "B3" in passed else "files do not come back"
    print(f"  Sandbox, automatic:            {('works, ' + files_out) if automatic else 'does not work'}")
    print("Send these lines back. FAIL lines carry the reason. They hold no document data.")
    return 0 if {"1", "1b"} <= passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Default prefixes copied on purpose from app/models/factory.py: this script travels alone.
    parser.add_argument("--gpt-model", default="openai.global.gpt-6-luna",
                        help="the gateway's name for the GPT model (region must match the address)")
    parser.add_argument("--claude-model", default="bedrock.anthropic.claude-sonnet-4-6",
                        help="the gateway's name for the Claude model")
    parser.add_argument("--provider", help="LiteLLM custom-llm-provider header, e.g. openai or azure")
    parser.add_argument("--model-on-create", action="store_true",
                        help="name the model when creating a sandbox (some LiteLLM set-ups need it)")
    args = parser.parse_args()

    prepare_console_and_network()
    load_env_file()
    url = os.environ.get("LLM_PROXY_URL", "").strip()
    key = gateway_key()
    if not url or not key:
        print("Set LLM_PROXY_URL and LLM_PROXY_API_KEY in the project's .env first.")
        return 2
    headers = {"custom-llm-provider": args.provider} if args.provider else None
    client = OpenAI(base_url=url, api_key=key, default_headers=headers, timeout=180, max_retries=1)
    print(f"Gateway: {url}")
    print(f"Models:  {args.gpt_model}, {args.claude_model}\n")

    check_gpt(client, args.gpt_model)
    check_gpt_app_settings(client, args.gpt_model)
    check_claude(client, args.claude_model)
    print("\nSandbox, the app creates it")
    part_a(client, args.gpt_model, args.model_on_create)
    print("\nSandbox, automatic")
    part_b(client, args.gpt_model)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
