import asyncio
from typing import Any

from mybot.agent.tools.base import Tool


class ShellTool(Tool):
    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Run a shell command and return its stdout, stderr, and exit code. "
            "Use for file operations, running scripts, checking system state, etc."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30).",
                    "default": 30,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command (default: current directory).",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self, command: str, timeout: int = 30, working_dir: str | None = None
    ) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return f"error: command timed out after {timeout}s"
        except Exception as e:
            return f"error: {e}"

        parts: list[str] = [f"exit_code: {proc.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout.decode(errors='replace').rstrip()}")
        if stderr:
            parts.append(f"stderr:\n{stderr.decode(errors='replace').rstrip()}")
        return "\n".join(parts)
