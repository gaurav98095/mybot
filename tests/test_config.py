"""Tests for config/schema.py and config/loader.py."""

import json
import os

import pytest

from mybot.config.loader import load_config, save_config
from mybot.config.schema import (
    AgentDefaults,
    Config,
    MCPConfig,
    MCPServerConfig,
    PhoenixConfig,
    WebSearchConfig,
)


# ---------------------------------------------------------------------------
# Schema defaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def test_default_model(self):
        cfg = Config()
        assert cfg.agents.defaults.model == "anthropic/claude-opus-4-5"

    def test_default_provider_no_key(self):
        cfg = Config()
        assert cfg.providers.anthropic.api_key is None

    def test_default_search_provider(self):
        cfg = Config()
        assert cfg.tools.web.search.provider == "duckduckgo"

    def test_default_phoenix_disabled(self):
        cfg = Config()
        assert cfg.phoenix.enabled is False
        assert cfg.phoenix.port == 6006

    def test_default_mcp_empty(self):
        cfg = Config()
        assert cfg.mcp.servers == {}

    def test_default_max_tokens(self):
        cfg = Config()
        assert cfg.agents.defaults.max_tokens == 8192


class TestMCPServerConfig:
    def test_stdio(self):
        s = MCPServerConfig(type="stdio", command="npx", args=["-y", "server"])
        assert s.type == "stdio"
        assert s.command == "npx"
        assert s.args == ["-y", "server"]
        assert s.url is None

    def test_sse(self):
        s = MCPServerConfig(type="sse", url="http://localhost:8000/sse")
        assert s.type == "sse"
        assert s.url == "http://localhost:8000/sse"
        assert s.command is None

    def test_http_with_headers(self):
        s = MCPServerConfig(
            type="http",
            url="http://localhost:9000/mcp",
            headers={"Authorization": "Bearer tok"},
        )
        assert s.headers == {"Authorization": "Bearer tok"}

    def test_camel_case_input(self):
        # Config accepts camelCase keys from JSON
        s = MCPServerConfig.model_validate({"type": "sse", "url": "http://x"})
        assert s.url == "http://x"


# ---------------------------------------------------------------------------
# Config round-trip (save + load)
# ---------------------------------------------------------------------------

class TestConfigLoader:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config()
        cfg.providers.anthropic.api_key = "sk-test-123"
        cfg.agents.defaults.model = "anthropic/claude-sonnet-4-6"
        cfg.phoenix.enabled = True

        save_config(cfg, path)
        loaded = load_config(path)

        assert loaded.providers.anthropic.api_key == "sk-test-123"
        assert loaded.agents.defaults.model == "anthropic/claude-sonnet-4-6"
        assert loaded.phoenix.enabled is True

    def test_load_missing_file_returns_defaults(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        cfg = load_config(path)
        assert isinstance(cfg, Config)
        assert cfg.agents.defaults.model == "anthropic/claude-opus-4-5"

    def test_load_invalid_json_returns_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not valid json{{{")
        cfg = load_config(path)
        assert isinstance(cfg, Config)

    def test_load_camelCase_json(self, tmp_path):
        path = tmp_path / "config.json"
        data = {
            "agents": {"defaults": {"maxTokens": 4096, "model": "anthropic/claude-haiku-4-5"}},
            "providers": {"anthropic": {"apiKey": "sk-camel"}},
        }
        path.write_text(json.dumps(data))
        cfg = load_config(path)
        assert cfg.providers.anthropic.api_key == "sk-camel"
        assert cfg.agents.defaults.max_tokens == 4096

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "config.json"
        save_config(Config(), path)
        assert path.exists()

    def test_roundtrip_mcp_servers(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config()
        cfg.mcp.servers["fs"] = MCPServerConfig(
            type="stdio", command="npx", args=["-y", "srv"]
        )
        save_config(cfg, path)
        loaded = load_config(path)
        assert "fs" in loaded.mcp.servers
        assert loaded.mcp.servers["fs"].command == "npx"

    def test_env_var_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYBOT_PROVIDERS__ANTHROPIC__API_KEY", "sk-from-env")
        cfg = Config()
        assert cfg.providers.anthropic.api_key == "sk-from-env"
