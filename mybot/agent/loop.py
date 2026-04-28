import asyncio

from loguru import logger

from mybot.agent.runner import AgentRunner
from mybot.bus.events import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.providers.base import LLMProvider


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds conversation history
    3. Calls the LLM via AgentRunner
    4. Sends responses back on the outbound bus
    """

    def __init__(self, provider: LLMProvider, model: str, bus: MessageBus):
        self.bus = bus
        self.model = model
        self._running = False
        self.runner = AgentRunner(provider, model)
        self._history: list[dict] = []

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
