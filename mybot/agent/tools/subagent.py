from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any

from mybot.agent.tools.base import Tool
from mybot.providers.base import LLMProvider

_ID_CHARS = string.ascii_lowercase + string.digits


def _gen_id() -> str:
    return "sub_" + "".join(secrets.choice(_ID_CHARS) for _ in range(8))


@dataclass
class _Task:
    task_id: str
    description: str
    started_at: float
    handle: asyncio.Task
    result: str | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        elapsed = f"{time.monotonic() - self.started_at:.1f}s"
        if self.error is not None:
            return f"FAILED ({elapsed})"
        if self.result is not None:
            return f"DONE ({elapsed})"
        return f"RUNNING ({elapsed})"


class SubagentTool(Tool):
    """
    Spawn background subagents for complex or parallelisable tasks.

    Each subagent is an independent AgentRunner that has access to shell
    and web-search but cannot spawn further subagents (prevents runaway
    recursion). Results are stored in memory and fetched by task_id.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        sub_tools: list[Tool] | None = None,
    ):
        self._provider = provider
        self._model = model
        self._sub_tools: list[Tool] = sub_tools or []
        self._tasks: dict[str, _Task] = {}

    @property
    def name(self) -> str:
        return "subagent"

    @property
    def description(self) -> str:
        return (
            "Spawn a background subagent to handle a complex or long-running task. "
            "Actions: 'spawn' starts a task and returns a task_id immediately; "
            "'result' retrieves output for a task_id (poll until DONE); "
            "'list' shows all tasks and their status."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["spawn", "result", "list"],
                    "description": (
                        "'spawn': launch a new subagent; "
                        "'result': fetch output by task_id; "
                        "'list': view all task statuses"
                    ),
                },
                "task": {
                    "type": "string",
                    "description": "Full task description for the subagent (required for spawn).",
                },
                "task_id": {
                    "type": "string",
                    "description": "ID returned by spawn (required for result).",
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional system-level instructions scoping the subagent's behaviour.",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task: str | None = None,
        task_id: str | None = None,
        instructions: str | None = None,
    ) -> str:
        if action == "spawn":
            return await self._spawn(task, instructions)
        if action == "result":
            return self._get_result(task_id)
        if action == "list":
            return self._list()
        return f"error: unknown action '{action}'"

    # ------------------------------------------------------------------

    async def _spawn(self, task: str | None, instructions: str | None) -> str:
        if not task:
            return "error: 'task' is required for spawn"

        tid = _gen_id()
        handle = asyncio.create_task(self._run(tid, task, instructions))
        rec = _Task(
            task_id=tid,
            description=task[:100],
            started_at=time.monotonic(),
            handle=handle,
        )
        self._tasks[tid] = rec
        handle.add_done_callback(lambda t: self._on_done(tid, t))
        return f"spawned task_id={tid}\nCall action='result' task_id='{tid}' to retrieve output."

    def _on_done(self, tid: str, t: asyncio.Task) -> None:
        rec = self._tasks.get(tid)
        if rec is None:
            return
        if t.cancelled():
            rec.error = "task was cancelled"
        elif (exc := t.exception()) is not None:
            rec.error = str(exc)

    def _get_result(self, task_id: str | None) -> str:
        if not task_id:
            return "error: 'task_id' is required for result"
        rec = self._tasks.get(task_id)
        if rec is None:
            return f"error: unknown task_id '{task_id}'"
        if rec.error is not None:
            return f"task_id={task_id} {rec.status}\n{rec.error}"
        if rec.result is not None:
            return f"task_id={task_id} {rec.status}\n\n{rec.result}"
        return f"task_id={task_id} {rec.status} — check back shortly."

    def _list(self) -> str:
        if not self._tasks:
            return "No subagent tasks."
        return "\n".join(
            f"  {rec.task_id}: {rec.status} — {rec.description}"
            for rec in self._tasks.values()
        )

    async def _run(self, tid: str, task: str, instructions: str | None) -> None:
        from mybot.agent.runner import AgentRunner
        from mybot.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for tool in self._sub_tools:
            registry.register(tool)

        runner = AgentRunner(self._provider, self._model, registry)

        messages: list[dict] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": task})

        try:
            response = await runner.run(messages)
            self._tasks[tid].result = response.content or "(no output)"
        except Exception as exc:
            self._tasks[tid].error = str(exc)
