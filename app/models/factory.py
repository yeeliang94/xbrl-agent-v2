"""The only place that builds a model connection.

Ported from v1 `server.py::_create_proxy_model` and `model_settings.py`,
without any Gemini code.

Two set-ups, chosen by whether `LLM_PROXY_URL` is set:
- direct (the Mac): GPT on OpenAI's Responses interface with OPENAI_API_KEY,
  Claude on Anthropic's own interface with ANTHROPIC_API_KEY.
- gateway (the enterprise machine): everything through one OpenAI-compatible
  address. GPT on the Responses interface; Claude as an OpenAI-style chat model.

Provider and family come from the model's NAME, never from the connection
type: on the gateway Claude arrives as an OpenAI-style model, and must still
never receive an OpenAI-only setting.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Literal

logger = logging.getLogger(__name__)

Setup = Literal["direct", "gateway"]
Provider = Literal["openai", "anthropic", "unknown"]
Family = Literal["luna", "terra", "claude", "other"]

# Gateway model names carry a routing prefix, e.g. `openai.global.gpt-6-luna`
# or `bedrock.anthropic.claude-sonnet-4-6` (v1's naming). The region part may
# differ (`openai.eu.`); it must match the gateway address.
_GATEWAY_PREFIX = re.compile(r"^(?:openai\.(?:[a-z]+\.)?|bedrock\.anthropic\.|anthropic\.)")
GATEWAY_DEFAULT_PREFIX = {"openai": "openai.global.", "anthropic": "bedrock.anthropic."}

# Thinking levels each family accepts. Luna is v1's GPT-6 Luna list. Terra
# (gpt-6.1-terra) is new: it takes the same handling as v1's GPT-6 Luna, which
# v1 treats exactly like GPT-6 Sol. Claude uses PydanticAI's portable levels.
# An unknown family accepts none: nothing is sent and the provider default holds.
THINKING_LEVELS: dict[str, tuple[str, ...]] = {
    "luna": ("none", "low", "medium", "high", "xhigh", "max"),
    "terra": ("none", "low", "medium", "high", "xhigh", "max"),
    "claude": ("none", "minimal", "low", "medium", "high"),
    "other": (),
}
# v1's substitution for a level a model does not list. Keeps the intent:
# `minimal` means the least reasoning available, not none at all.
_LEVEL_FALLBACK = {"minimal": "low", "xhigh": "high", "max": "high"}

# GPT-6 models take the cache-options shape; "30m" is its only accepted ttl.
CACHE_OPTIONS_TTL = "30m"

# Settings only OpenAI's own interface understands. Claude never gets these.
OPENAI_ONLY_SETTINGS = frozenset({
    "openai_reasoning_summary",
    "openai_prompt_cache_key",
    "openai_prompt_cache_retention",
    "openai_include_code_execution_outputs",
    "openai_cache_instructions",
    "extra_body",
})

_trust_lock = threading.Lock()
_trust_done = False


def ensure_certificate_trust() -> None:
    """Trust the operating system's certificate store (the Windows store holds
    the company's certificates). Runs once, before any client is created.
    Certificate checking is never switched off."""
    global _trust_done
    with _trust_lock:
        if _trust_done:
            return
        import truststore

        truststore.inject_into_ssl()
        _trust_done = True


# Names -------------------------------------------------------------------

def current_setup() -> Setup:
    return "gateway" if os.environ.get("LLM_PROXY_URL", "").strip() else "direct"


def bare_name(model_id: str) -> str:
    """The model's name without any gateway prefix."""
    return _GATEWAY_PREFIX.sub("", (model_id or "").strip(), count=1)


def provider_of(model_id: str) -> Provider:
    name = bare_name(model_id).lower()
    if name.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai"
    if name.startswith("claude-"):
        return "anthropic"
    return "unknown"


def family_of(model_id: str) -> Family:
    provider = provider_of(model_id)
    if provider == "anthropic":
        return "claude"
    name = bare_name(model_id).lower()
    if provider == "openai" and "luna" in name:
        return "luna"
    if provider == "openai" and "terra" in name:
        return "terra"
    return "other"


def gateway_name(model_id: str) -> str:
    """The name the gateway expects. A name that already carries a prefix is
    kept as written; a bare name gets the default prefix."""
    if bare_name(model_id) != model_id.strip():
        return model_id.strip()
    return GATEWAY_DEFAULT_PREFIX.get(provider_of(model_id), "") + model_id.strip()


def short_id(model_id: str) -> str:
    """The id shown in Settings: a gateway name with the default prefix is
    shown bare, because `gateway_name` turns it back into the same name."""
    bare = bare_name(model_id)
    return bare if gateway_name(bare) == model_id.strip() else model_id.strip()


# Keys --------------------------------------------------------------------

def gateway_key() -> str:
    # v1's order: the dedicated gateway key, then the enterprise machine's
    # older names for the same key.
    for name in ("LLM_PROXY_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return ""


_DIRECT_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def has_key(provider: str) -> bool:
    if provider not in _DIRECT_KEYS:
        return False
    if current_setup() == "gateway":
        return bool(gateway_key())
    return bool(os.environ.get(_DIRECT_KEYS[provider], "").strip())


def _direct_key(provider: str, model_id: str) -> str:
    key = os.environ.get(_DIRECT_KEYS[provider], "").strip()
    if not key:
        raise ValueError(f"Model {model_id} needs {_DIRECT_KEYS[provider]} in .env, and it is not set.")
    return key


def _gateway() -> tuple[str, str]:
    url = os.environ.get("LLM_PROXY_URL", "").strip()
    key = gateway_key()
    if not key:
        raise ValueError("The gateway needs LLM_PROXY_API_KEY in .env, and it is not set.")
    return url, key


# What a model can do ---------------------------------------------------------

def thinking_levels(model_id: str) -> tuple[str, ...]:
    return THINKING_LEVELS[family_of(model_id)]


def code_tool_supported(model_id: str, setup: Setup | None = None) -> bool:
    """Whether the provider-side code tool (PydanticAI's CodeExecutionTool) can
    be used. On the gateway Claude arrives as an OpenAI-style chat model, which
    cannot carry a provider tool."""
    setup = setup or current_setup()
    provider = provider_of(model_id)
    if provider == "openai":
        return True
    if provider == "anthropic":
        return setup == "direct"
    return False


def _supported_level(model_id: str, level: str | None) -> str | None:
    if not level:
        return None
    level = level.strip().lower()
    allowed = thinking_levels(model_id)
    if not allowed:
        logger.warning("Model %s has no known thinking levels; %r is not sent.", model_id, level)
        return None
    if level in allowed:
        return level
    substitute = _LEVEL_FALLBACK.get(level, "low")
    logger.warning("Model %s does not accept thinking level %r; using %r.", model_id, level, substitute)
    return substitute


# Building ----------------------------------------------------------------

def build_model(model_id: str) -> Any:
    """A PydanticAI model for `model_id` on the current set-up."""
    ensure_certificate_trust()
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = provider_of(model_id)
    if provider == "unknown":
        raise ValueError(f"Model {model_id} is not a GPT or Claude model.")
    bare = bare_name(model_id)

    if current_setup() == "gateway":
        url, key = _gateway()
        gateway = OpenAIProvider(base_url=url, api_key=key)
        name = gateway_name(model_id)
        if provider == "openai":
            # The gateway needs its own name, but PydanticAI recognises reasoning
            # support only from the bare name, so pass that profile explicitly.
            return OpenAIResponsesModel(name, provider=gateway, profile=gateway.model_profile(bare))
        return OpenAIChatModel(name, provider=gateway)

    if provider == "openai":
        return OpenAIResponsesModel(bare, provider=OpenAIProvider(api_key=_direct_key("openai", model_id)))
    return AnthropicModel(bare, provider=AnthropicProvider(api_key=_direct_key("anthropic", model_id)))


def model_settings(model_id: str, *, thinking: str | None = None, code_tool: bool = False) -> dict:
    """The request settings for `model_id` on the current set-up. With no
    thinking level, none is sent and the provider's default holds."""
    from pydantic_ai.models.anthropic import AnthropicModelSettings
    from pydantic_ai.models.openai import OpenAIChatModelSettings, OpenAIResponsesModelSettings

    provider, family = provider_of(model_id), family_of(model_id)
    level = _supported_level(model_id, thinking)

    if provider == "openai":
        settings: dict[str, Any] = {}
        if family in ("luna", "terra"):
            settings["openai_reasoning_summary"] = "auto"
            settings["extra_body"] = {"prompt_cache_options": {"ttl": CACHE_OPTIONS_TTL}}
            if current_setup() == "direct":
                # GPT-6 caches at explicit breakpoints: one after the fixed
                # instructions lets every page's call reuse them (measured on
                # Doc 3: no cached tokens without it). Not sent through the
                # gateway until a run there shows it is accepted.
                settings["openai_cache_instructions"] = True
            if level:
                settings["openai_reasoning_effort"] = level
        if code_tool:
            settings["openai_include_code_execution_outputs"] = True
        return OpenAIResponsesModelSettings(**settings)

    if provider == "anthropic" and current_setup() == "direct":
        settings = {"anthropic_cache_instructions": True, "anthropic_cache_tool_definitions": True}
        if level:
            # "none" is not a PydanticAI level; PydanticAI spells "off" as False.
            settings["thinking"] = False if level == "none" else level
        return AnthropicModelSettings(**settings)

    if provider == "anthropic":
        # Claude on the gateway. reasoning_effort is the one thinking field the
        # gateway (LiteLLM) translates for Claude, as in v1. Nothing else.
        if level in ("low", "medium", "high"):
            return OpenAIChatModelSettings(openai_reasoning_effort=level)
        return OpenAIChatModelSettings()

    return {}


def provider_client(provider: str) -> Any:
    """A raw async client for listing models. Gateway: the one address."""
    ensure_certificate_trust()
    if current_setup() == "gateway":
        from openai import AsyncOpenAI

        url, key = _gateway()
        return AsyncOpenAI(base_url=url, api_key=key, timeout=10, max_retries=0)
    if provider == "openai":
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=_direct_key("openai", "listing"), timeout=10, max_retries=0)
    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=_direct_key("anthropic", "listing"), timeout=10, max_retries=0)
    raise ValueError(f"Unknown provider {provider!r}.")
