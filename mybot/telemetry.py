"""Arize Phoenix / OpenTelemetry tracing setup."""

from __future__ import annotations

from loguru import logger

from mybot.config.schema import PhoenixConfig


def setup_tracing(config: PhoenixConfig) -> None:
    """Configure the global OTel tracer to send spans to Phoenix.

    No-ops silently when tracing is disabled or packages are missing,
    so callers never need to guard this call.
    """
    if not config.enabled:
        return

    try:
        from phoenix.otel import register
    except ImportError:
        logger.error(
            "Phoenix tracing deps not installed. " "Run: pip install -e '.[tracing]'"
        )
        return

    endpoint = f"http://{config.host}:{config.port}/v1/traces"
    register(project_name="mybot", endpoint=endpoint)
    logger.info("Phoenix tracing active → {}", endpoint)

    try:
        from openinference.instrumentation.anthropic import \
            AnthropicInstrumentor

        AnthropicInstrumentor().instrument()
        logger.info("Anthropic SDK auto-instrumented")
    except ImportError:
        logger.warning(
            "openinference-instrumentation-anthropic not installed; "
            "LLM spans will not be captured"
        )
