"""Tests for agent/tools/registry.py and the Tool base class."""

from typing import Any

import pytest

from mybot.agent.tools.base import Tool
from mybot.agent.tools.registry import ToolRegistry


class EchoTool(Tool):
    """Minimal concrete Tool for testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input back."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, text: str = "", **kwargs) -> str:
        return text


class PingTool(Tool):
    @property
    def name(self) -> str:
        return "ping"

    @property
    def description(self) -> str:
        return "Pings."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "pong"


class TestToolBase:
    def test_to_schema_structure(self):
        schema = EchoTool().to_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "echo"
        assert "Echoes" in fn["description"]
        assert fn["parameters"]["type"] == "object"

    def test_to_schema_includes_required(self):
        schema = EchoTool().to_schema()
        assert "text" in schema["function"]["parameters"]["required"]


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = EchoTool()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_has_registered_tool(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert reg.has("echo") is True

    def test_has_unregistered_tool(self):
        reg = ToolRegistry()
        assert reg.has("echo") is False

    def test_unregister_removes_tool(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.unregister("echo")
        assert reg.get("echo") is None
        assert reg.has("echo") is False

    def test_unregister_nonexistent_is_safe(self):
        reg = ToolRegistry()
        reg.unregister("never_existed")  # should not raise

    def test_register_overwrites_duplicate(self):
        reg = ToolRegistry()
        t1 = EchoTool()
        t2 = EchoTool()
        reg.register(t1)
        reg.register(t2)
        assert reg.get("echo") is t2

    def test_multiple_tools_independent(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(PingTool())
        assert reg.get("echo") is not None
        assert reg.get("ping") is not None

    async def test_execute_via_registry(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        tool = reg.get("echo")
        result = await tool.execute(text="hello")
        assert result == "hello"
