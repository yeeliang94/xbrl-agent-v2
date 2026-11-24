"""The model factory: set-up choice, provider and family by name, settings per
family, the code tool, and certificate trust."""
from __future__ import annotations

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from app.models import factory

GATEWAY = "https://gateway.example/v1"


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", GATEWAY)
    monkeypatch.setenv("LLM_PROXY_API_KEY", "gateway-key")


def test_setup_follows_the_gateway_address(monkeypatch):
    assert factory.current_setup() == "direct"
    monkeypatch.setenv("LLM_PROXY_URL", "  ")
    assert factory.current_setup() == "direct"
    monkeypatch.setenv("LLM_PROXY_URL", GATEWAY)
    assert factory.current_setup() == "gateway"


@pytest.mark.parametrize("model_id, provider, family", [
    ("gpt-6-luna", "openai", "luna"),
    ("openai.global.gpt-6-luna", "openai", "luna"),
    ("openai.eu.gpt-6-luna", "openai", "luna"),
    ("gpt-6.1-terra", "openai", "terra"),
    ("gpt-5.4", "openai", "other"),
    ("claude-sonnet-4-6", "anthropic", "claude"),
    ("bedrock.anthropic.claude-opus-4-7", "anthropic", "claude"),
    ("gemini-3-flash", "unknown", "other"),
])
def test_provider_and_family_come_from_the_name(model_id, provider, family):
    assert factory.provider_of(model_id) == provider
    assert factory.family_of(model_id) == family


def test_gateway_names_keep_v1_naming():
    assert factory.gateway_name("gpt-6-luna") == "openai.global.gpt-6-luna"
    assert factory.gateway_name("openai.eu.gpt-6-luna") == "openai.eu.gpt-6-luna"
    assert factory.gateway_name("claude-opus-4-7") == "bedrock.anthropic.claude-opus-4-7"
    assert factory.short_id("openai.global.gpt-6-luna") == "gpt-6-luna"
    assert factory.short_id("openai.eu.gpt-6-luna") == "openai.eu.gpt-6-luna"


def test_direct_builds_responses_for_gpt_and_anthropic_for_claude(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    gpt = factory.build_model("gpt-6-luna")
    assert isinstance(gpt, OpenAIResponsesModel) and gpt.model_name == "gpt-6-luna"
    assert "api.openai.com" in str(gpt.base_url)
    claude = factory.build_model("claude-sonnet-4-6")
    assert isinstance(claude, AnthropicModel) and claude.model_name == "claude-sonnet-4-6"


def test_direct_without_a_key_says_which_key(monkeypatch):
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        factory.build_model("gpt-6-luna")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        factory.build_model("claude-sonnet-4-6")


def test_unknown_models_are_refused(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    with pytest.raises(ValueError, match="not a GPT or Claude model"):
        factory.build_model("gemini-3-flash")


def test_gateway_sends_everything_to_the_one_address(gateway):
    gpt = factory.build_model("gpt-6-luna")
    assert isinstance(gpt, OpenAIResponsesModel)
    assert gpt.model_name == "openai.global.gpt-6-luna"
    assert str(gpt.base_url).startswith(GATEWAY)
    # Reasoning support comes from the bare name, not the gateway name.
    assert gpt.profile.get("openai_supports_encrypted_reasoning_content") is True
    claude = factory.build_model("claude-opus-4-7")
    assert type(claude) is OpenAIChatModel
    assert claude.model_name == "bedrock.anthropic.claude-opus-4-7"
    assert str(claude.base_url).startswith(GATEWAY)


def test_gateway_accepts_v1s_older_key_name(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", GATEWAY)
    with pytest.raises(ValueError, match="LLM_PROXY_API_KEY"):
        factory.build_model("gpt-6-luna")
    monkeypatch.setenv("GOOGLE_API_KEY", "enterprise-key")
    assert factory.build_model("gpt-6-luna").model_name == "openai.global.gpt-6-luna"


def test_claude_on_the_gateway_gets_no_openai_only_setting(gateway):
    for level in (None, "none", "low", "high"):
        for code_tool in (False, True):
            settings = factory.model_settings("claude-opus-4-7", thinking=level, code_tool=code_tool)
            assert not set(settings) & factory.OPENAI_ONLY_SETTINGS, settings


def test_gpt_settings_for_luna_and_terra_match(monkeypatch):
    for setup_url in ("", GATEWAY):
        monkeypatch.setenv("LLM_PROXY_URL", setup_url)
        luna = factory.model_settings("gpt-6-luna", thinking="high", code_tool=True)
        terra = factory.model_settings("gpt-6.1-terra", thinking="high", code_tool=True)
        assert luna == terra
        assert luna["openai_reasoning_effort"] == "high"
        assert luna["openai_include_code_execution_outputs"] is True
        assert luna["extra_body"] == {"prompt_cache_options": {"ttl": "30m"}}
        assert luna.get("openai_cache_instructions") is (True if not setup_url else None)


def test_thinking_levels_per_family():
    assert factory.thinking_levels("gpt-6.1-terra") == factory.thinking_levels("gpt-6-luna")
    assert "minimal" not in factory.thinking_levels("gpt-6-luna")
    assert factory.model_settings("gpt-6-luna", thinking="minimal")["openai_reasoning_effort"] == "low"
    assert factory.model_settings("claude-sonnet-4-6", thinking="none")["thinking"] is False
    assert "thinking" not in factory.model_settings("claude-sonnet-4-6")


def test_unknown_family_gets_safe_defaults():
    assert factory.thinking_levels("gpt-5.4") == ()
    assert factory.model_settings("gpt-5.4", thinking="high") == {}
    assert factory.model_settings("gemini-3-flash", thinking="high") == {}


@pytest.mark.parametrize("model_id, setup, allowed", [
    ("gpt-6-luna", "direct", True),
    ("claude-sonnet-4-6", "direct", True),
    ("gpt-6-luna", "gateway", True),
    ("claude-sonnet-4-6", "gateway", False),
    ("bedrock.anthropic.claude-opus-4-7", "gateway", False),
    ("gemini-3-flash", "direct", False),
])
def test_code_tool_support(model_id, setup, allowed):
    assert factory.code_tool_supported(model_id, setup) is allowed


def test_certificate_store_is_loaded_before_a_client_is_built(monkeypatch):
    import truststore

    calls = []
    monkeypatch.setattr(factory, "_trust_done", False)
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: calls.append("trust"))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    factory.build_model("gpt-6-luna")
    factory.build_model("gpt-6-luna")
    assert calls == ["trust"]
