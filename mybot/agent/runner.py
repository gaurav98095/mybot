
import asyncio

class AgentRunner:
    def __init__(self, provider):
        self.provider = provider

    async def run(self, messages: list):
        response = await self._request_model(messages)

    async def _request_model(self, messages):
        kwargs = self._build_request_kwargs(messages)
        coro = self.provider.chat_with_retry(**kwargs)
        return await asyncio.wait_for(coro, timeout=10)


    def _build_request_kwargs(
        self,
        messages
    ):
        kwargs = {
            "messages": messages
        }
        return kwargs