from mybot.providers.base import LLMProvider, LLMResponse


class AgentRunner:
    def __init__(self, provider: LLMProvider, model: str):
        self.provider = provider
        self.model = model

    async def run(self, messages: list) -> LLMResponse:
        return await self._request_model(messages)

    async def _request_model(self, messages) -> LLMResponse:
        kwargs = self._build_request_kwargs(messages)
        return await self.provider.chat_with_retry(**kwargs)

    def _build_request_kwargs(self, messages) -> dict:
        return {"messages": messages, "model": self.model}
