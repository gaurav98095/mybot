import asyncio

from loguru import logger

from mybot.agent.runner import AgentRunner
from mybot.agent.tools.base import Tool
from mybot.agent.tools.registry import ToolRegistry
from mybot.agent.tools.shell import ShellTool
from mybot.agent.tools.subagent import SubagentTool
from mybot.agent.tools.web_search import WebSearchTool
from mybot.bus.events import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.config.schema import WebSearchConfig
from mybot.providers.base import LLMProvider


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds conversation history
    3. Calls the LLM via AgentRunner (with tool-call loop)
    4. Sends responses back on the outbound bus
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        bus: MessageBus,
        tools: list[Tool] | None = None,
        search_config: WebSearchConfig | None = None,
        proxy: str | None = None,
    ):
        self.bus = bus
        self.model = model
        self._running = False
        self._history: list[dict] = []

        if tools is None:
            # sub_tools are given to subagents — no SubagentTool to prevent recursion
            sub_tools: list[Tool] = [
                ShellTool(),
                WebSearchTool(config=search_config, proxy=proxy),
            ]
            tools = sub_tools + [
                SubagentTool(provider=provider, model=model, sub_tools=sub_tools),
            ]

        registry = ToolRegistry()
        for tool in tools:
            registry.register(tool)

        self.runner = AgentRunner(provider, model, registry)

    async def run(self) -> None:
        """Run the agent loop, processing inbound messages one at a time."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            await self._process_message(msg)

    async def _process_message(self, msg: InboundMessage) -> None:
        self._history.append({"role": "user", "content": msg.content})
        try:
            # runner mutates self._history with any intermediate tool call/result
            # messages, then returns the final text response
            response = await self.runner.run(self._history)
            reply = response.content or ""
            self._history.append({"role": "assistant", "content": reply})
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=reply,
                    type="final",
                )
            )
        except Exception as e:
            logger.error("Error processing message: {}", e)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Error: {e}",
                    type="error",
                )
            )
