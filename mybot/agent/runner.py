from loguru import logger

from mybot.agent.tools.registry import ToolRegistry
from mybot.providers.base import LLMProvider, LLMResponse

MAX_TOOL_ROUNDS = 10


class AgentRunner:
    def __init__(
        self, provider: LLMProvider, model: str, registry: ToolRegistry | None = None
    ):
        self.provider = provider
        self.model = model
        self.registry = registry or ToolRegistry()

    async def run(self, messages: list) -> LLMResponse:
        tools = self._tool_schemas() or None
        response = LLMResponse(content=None)

        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = await self.provider.chat_with_retry(
                messages=messages,
                model=self.model,
                tools=tools,
            )
            if not response.should_execute_tools:
                return response

            # Append assistant turn carrying the tool calls
            assistant_msg: dict = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [tc.to_openai_tool_call() for tc in response.tool_calls],
            }
            if response.thinking_blocks:
                assistant_msg["thinking_blocks"] = response.thinking_blocks
            messages.append(assistant_msg)

            # Execute each requested tool and collect results
            for tc in response.tool_calls:
                tool = self.registry.get(tc.name)
                if tool is None:
                    result = f"error: unknown tool '{tc.name}'"
                    logger.warning("Unknown tool requested: {}", tc.name)
                else:
                    logger.info("Executing tool '{}' args={}", tc.name, tc.arguments)
                    try:
                        result = await tool.execute(**tc.arguments)
                    except Exception as exc:
                        result = f"error: {exc}"
                        logger.error("Tool '{}' raised: {}", tc.name, exc)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    }
                )

        return response

    def _tool_schemas(self) -> list:
        return [tool.to_schema() for tool in self.registry._tools.values()]
