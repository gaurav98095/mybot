import asyncio

from loguru import logger

from mybot.agent.runner import AgentRunner
from mybot.bus.queue import MessageBus


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It's the plan to build..

    It:
    1. Receives messages
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(self, provider: str, model: str, bus: MessageBus):
        self.bus = bus
        self.provider = provider
        self.model = model
        self._running = False
        self.runner = AgentRunner(provider)

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            raw = msg.content.strip()

    async def _process_message(self, msg):
        pass

    async def _run_agent_loop(self, msg):
        pass
