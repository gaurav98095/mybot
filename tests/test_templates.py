"""Tests for mybot.templates — the prompt-template loader."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mybot import templates as tpl


def test_load_known_template():
    text = tpl.load("classifier", "system")
    assert "simple" in text
    assert "medium" in text
    assert "complex" in text


def test_load_tool_shell():
    text = tpl.load("tools", "shell")
    assert "shell" in text.lower()


def test_load_tool_web_search():
    text = tpl.load("tools", "web_search")
    assert "search" in text.lower()


def test_load_tool_subagent():
    text = tpl.load("tools", "subagent")
    assert "subagent" in text.lower()


def test_load_missing_raises():
    tpl.load.cache_clear()
    with pytest.raises(FileNotFoundError, match="Prompt template not found"):
        tpl.load("nonexistent_usecase", "no_such_file")


def test_load_caches_result():
    tpl.load.cache_clear()
    first = tpl.load("classifier", "system")
    second = tpl.load("classifier", "system")
    assert first is second  # same object — cache hit


def test_env_override(tmp_path: Path):
    custom = tmp_path / "tools"
    custom.mkdir()
    (custom / "shell.md").write_text("custom shell description")

    tpl.load.cache_clear()
    with patch.dict(os.environ, {"MYBOT_TEMPLATES_DIR": str(tmp_path)}):
        text = tpl.load("tools", "shell")
    assert text == "custom shell description"
    tpl.load.cache_clear()


def test_env_override_missing_raises(tmp_path: Path):
    tpl.load.cache_clear()
    with patch.dict(os.environ, {"MYBOT_TEMPLATES_DIR": str(tmp_path)}):
        with pytest.raises(FileNotFoundError):
            tpl.load("tools", "shell")
    tpl.load.cache_clear()


def test_shell_tool_uses_template():
    from mybot.agent.tools.shell import ShellTool
    tool = ShellTool()
    expected = tpl.load("tools", "shell")
    assert tool.description == expected


def test_web_search_tool_uses_template():
    from mybot.agent.tools.web_search import WebSearchTool
    tool = WebSearchTool()
    expected = tpl.load("tools", "web_search")
    assert tool.description == expected


def test_subagent_tool_uses_template(fake_provider):
    from mybot.agent.tools.subagent import SubagentTool
    tool = SubagentTool(provider=fake_provider, model="test-model")
    expected = tpl.load("tools", "subagent")
    assert tool.description == expected
