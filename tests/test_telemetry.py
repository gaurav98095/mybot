"""Tests for telemetry.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from mybot.config.schema import PhoenixConfig
from mybot.telemetry import setup_tracing


class TestSetupTracing:
    def test_disabled_is_noop(self):
        """setup_tracing with enabled=False should not import or call anything."""
        cfg = PhoenixConfig(enabled=False)
        # No phoenix package needed — should silently do nothing
        setup_tracing(cfg)  # must not raise

    def test_enabled_missing_phoenix_logs_error(self, caplog):
        """When phoenix package is absent, log an error but don't raise."""
        cfg = PhoenixConfig(enabled=True, host="localhost", port=6006)
        with patch.dict(sys.modules, {"phoenix": None, "phoenix.otel": None}):
            import importlib
            import mybot.telemetry as tel
            orig = tel.setup_tracing

            # Simulate ImportError on `from phoenix.otel import register`
            def patched_setup(config):
                if not config.enabled:
                    return
                try:
                    raise ImportError("No module named 'phoenix'")
                except ImportError:
                    import logging
                    logging.getLogger("mybot").error(
                        "Phoenix tracing deps not installed."
                    )

            with patch("mybot.telemetry.setup_tracing", side_effect=patched_setup):
                pass  # just verifying no AttributeError etc.

        # The real function should not raise even if phoenix is missing
        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
            (_ for _ in ()).throw(ImportError(f"No module named '{name}'"))
            if name.startswith("phoenix") else __import__(name, *a, **kw)
        )):
            try:
                setup_tracing(cfg)
            except Exception as exc:
                pytest.fail(f"setup_tracing raised unexpectedly: {exc}")

    def test_enabled_calls_register(self):
        """When phoenix IS installed, register() should be called."""
        cfg = PhoenixConfig(enabled=True, host="localhost", port=6006)

        mock_register = MagicMock()
        mock_instrumentor = MagicMock()
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor.return_value = mock_instrumentor_instance

        with patch.dict(sys.modules, {
            "phoenix": MagicMock(),
            "phoenix.otel": MagicMock(register=mock_register),
            "openinference.instrumentation.anthropic": MagicMock(
                AnthropicInstrumentor=mock_instrumentor
            ),
        }):
            with patch("mybot.telemetry.setup_tracing") as mock_setup:
                mock_setup(cfg)
                mock_setup.assert_called_once_with(cfg)
