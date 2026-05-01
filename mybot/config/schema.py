"""Configuration schema using Pydantic."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.mybot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.1


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str | None = None
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)


class WebSearchConfig(Base):
    """Web search tool configuration."""

    provider: str = "duckduckgo"  # brave, tavily, duckduckgo, searxng, jina, kagi
    api_key: str = ""
    base_url: str = ""  # SearXNG base URL
    max_results: int = 5
    timeout: int = 30


class WebToolsConfig(Base):
    """Web tools configuration."""

    proxy: str | None = None  # HTTP/SOCKS5 proxy URL
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)


class PhoenixConfig(Base):
    """Arize Phoenix tracing configuration."""

    enabled: bool = False
    host: str = "localhost"
    port: int = 6006
    container_name: str = "mybot-phoenix"
    image: str = "arizephoenix/phoenix:latest"


class ClassifierConfig(Base):
    """Pre-turn task complexity classifier."""

    enabled: bool = False
    classifier_model: str = "anthropic/claude-haiku-4-5-20251001"
    simple_model: str = "anthropic/claude-haiku-4-5-20251001"
    medium_model: str = "anthropic/claude-sonnet-4-6"
    complex_model: str = "anthropic/claude-opus-4-5"


class MCPServerConfig(Base):
    """Configuration for a single MCP server connection."""

    type: str  # "stdio" | "sse" | "http"
    # stdio transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    # sse / http transport
    url: str | None = None
    headers: dict[str, str] | None = None


class MCPConfig(Base):
    """MCP server configuration."""

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class Config(BaseSettings):
    """Root configuration for mybot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)

    model_config = ConfigDict(env_prefix="MYBOT_", env_nested_delimiter="__")
