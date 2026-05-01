"""Tests for agent/tools/subagent.py."""

import asyncio

import pytest

from mybot.agent.tools.subagent import SubagentTool
from mybot.providers.base import LLMResponse
from tests.conftest import FakeProvider


@pytest.fixture
def provider():
    return FakeProvider([LLMResponse(content="subagent result")])


@pytest.fixture
def subagent(provider):
    return SubagentTool(provider=provider, model="fake/model")


class TestSubagentSchema:
    def test_name(self, subagent):
        assert subagent.name == "subagent"

    def test_parameters_has_action(self, subagent):
        params = subagent.parameters
        assert "action" in params["properties"]
        assert "action" in params["required"]

    def test_action_enum(self, subagent):
        enum = subagent.parameters["properties"]["action"]["enum"]
        assert set(enum) == {"spawn", "result", "list"}


class TestSubagentExecute:
    async def test_unknown_action_returns_error(self, subagent):
        result = await subagent.execute(action="fly")
        assert "error" in result.lower()
        assert "fly" in result

    async def test_spawn_missing_task_returns_error(self, subagent):
        result = await subagent.execute(action="spawn")
        assert "error" in result.lower()
        assert "task" in result.lower()

    async def test_result_missing_task_id_returns_error(self, subagent):
        result = await subagent.execute(action="result")
        assert "error" in result.lower()
        assert "task_id" in result.lower()

    async def test_result_unknown_task_id_returns_error(self, subagent):
        result = await subagent.execute(action="result", task_id="sub_nonexistent")
        assert "error" in result.lower()

    async def test_list_no_tasks(self, subagent):
        result = await subagent.execute(action="list")
        assert "No subagent tasks" in result

    async def test_spawn_returns_task_id(self, subagent):
        result = await subagent.execute(action="spawn", task="do something")
        assert "task_id=" in result

    async def test_spawn_then_list_shows_task(self, subagent):
        spawn_result = await subagent.execute(action="spawn", task="do something")
        task_id = spawn_result.split("task_id=")[1].split("\n")[0]

        list_result = await subagent.execute(action="list")
        assert task_id in list_result

    async def test_spawn_then_poll_result(self):
        provider = FakeProvider([LLMResponse(content="task complete output")])
        subagent = SubagentTool(provider=provider, model="fake/model")

        spawn_result = await subagent.execute(action="spawn", task="some task")
        task_id = spawn_result.split("task_id=")[1].split("\n")[0]

        # Give the background task time to complete
        await asyncio.sleep(0.2)

        result = await subagent.execute(action="result", task_id=task_id)
        assert "DONE" in result or "task complete output" in result

    async def test_spawn_with_instructions(self, subagent):
        result = await subagent.execute(
            action="spawn",
            task="do something",
            instructions="Be concise",
        )
        assert "task_id=" in result

    async def test_spawn_multiple_tasks_tracked(self, subagent):
        for i in range(3):
            await subagent.execute(action="spawn", task=f"task {i}")

        list_result = await subagent.execute(action="list")
        # Should list all 3 tasks
        count = list_result.count("sub_")
        assert count >= 3
