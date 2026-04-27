


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
    
    def __init__(self, provider: str, model : str):
        self.provider = provider
        self.model = model