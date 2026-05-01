"""Tests for agent/tools/shell.py."""

import pytest

from mybot.agent.tools.shell import ShellTool


@pytest.fixture
def shell():
    return ShellTool()


class TestShellToolSchema:
    def test_name(self, shell):
        assert shell.name == "shell"

    def test_description_non_empty(self, shell):
        assert len(shell.description) > 10

    def test_parameters_structure(self, shell):
        params = shell.parameters
        assert params["type"] == "object"
        assert "command" in params["properties"]
        assert "command" in params["required"]

    def test_to_schema_format(self, shell):
        schema = shell.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "shell"


class TestShellToolExecute:
    async def test_echo_command(self, shell):
        result = await shell.execute(command="echo hello")
        assert "hello" in result
        assert "exit_code: 0" in result

    async def test_exit_code_nonzero(self, shell):
        result = await shell.execute(command="exit 42")
        assert "exit_code: 42" in result

    async def test_stderr_captured(self, shell):
        result = await shell.execute(command="ls /nonexistent_path_xyz 2>&1 || true")
        assert "exit_code:" in result

    async def test_command_with_output(self, shell):
        result = await shell.execute(command="printf 'line1\nline2\n'")
        assert "line1" in result
        assert "line2" in result

    async def test_timeout_returns_error(self, shell):
        result = await shell.execute(command="sleep 60", timeout=1)
        assert "timed out" in result.lower() or "error" in result.lower()

    async def test_working_dir(self, shell, tmp_path):
        result = await shell.execute(command="pwd", working_dir=str(tmp_path))
        assert str(tmp_path) in result

    async def test_invalid_command(self, shell):
        result = await shell.execute(command="this_command_does_not_exist_xyz")
        assert "exit_code:" in result or "error" in result.lower()

    async def test_multiline_output(self, shell):
        result = await shell.execute(command="printf 'a\nb\nc\n'")
        assert "a" in result
        assert "b" in result
        assert "c" in result
