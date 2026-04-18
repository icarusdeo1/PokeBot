"""Tests for daemon.py entry point."""

from __future__ import annotations

import asyncio
import signal as stdlib_signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Test argument parsing ─────────────────────────────────────────────────────

def test_parse_args_defaults():
    """_parse_args returns defaults when no args provided."""
    from daemon import _parse_args

    with patch("sys.argv", ["daemon.py"]):
        args = _parse_args()
        assert args.config == "config.yaml"


def test_parse_args_custom_config():
    """_parse_args respects --config argument."""
    from daemon import _parse_args

    with patch("sys.argv", ["daemon.py", "--config", "/path/to/custom.yaml"]):
        args = _parse_args()
        assert args.config == "/path/to/custom.yaml"


# ── Test main exits on missing config ───────────────────────────────────────

def test_main_exits_when_config_not_found():
    """main() exits with code 1 when config file doesn't exist."""
    from daemon import main

    with patch("sys.argv", ["daemon.py", "--config", "/nonexistent/config.yaml"]):
        with patch("sys.exit") as mock_exit:
            mock_exit.return_value = None  # suppress SystemExit
            main()
            mock_exit.assert_called_with(1)


# ── Test async_main initialization ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_main_loads_config():
    """_async_main loads and validates config."""
    from daemon import _async_main

    config_path = Path("/fake/config.yaml")
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.error = MagicMock()
    mock_logger.warning = MagicMock()

    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock()

    with patch("daemon.DatabaseManager") as mock_db_cls:
        mock_db = MagicMock()
        mock_db.initialize = MagicMock()
        mock_db_cls.return_value = mock_db

        with patch("daemon.SessionPrewarmer") as mock_pw_cls:
            mock_pw = MagicMock()
            mock_pw_cls.return_value = mock_pw

            with patch("daemon.CartManager") as mock_cm_cls:
                mock_cm = MagicMock()
                mock_cm_cls.return_value = mock_cm

                with patch("daemon.CheckoutFlow") as mock_cf_cls:
                    mock_cf = MagicMock()
                    mock_cf_cls.return_value = mock_cf

                    with patch("daemon.StockMonitor") as mock_sm_cls:
                        mock_sm_cls.return_value = mock_monitor

                        with patch("daemon.CrashRecovery") as mock_cr_cls:
                            mock_cr = MagicMock()
                            mock_cr.__enter__ = MagicMock(return_value=None)
                            mock_cr.__exit__ = MagicMock(return_value=None)
                            mock_cr_cls.return_value = mock_cr

                            with patch("daemon.Config") as mock_config_cls:
                                mock_config = MagicMock()
                                mock_config_cls.from_file.return_value = mock_config

                                # Prevent _build_webhook_callback from trying to create
                                # DiscordWebhook/TelegramWebhook with MagicMock config values
                                with patch(
                                    "daemon._build_webhook_callback",
                                    MagicMock(return_value=None),
                                ):
                                    with patch("asyncio.create_task"):
                                        mock_monitor.start = AsyncMock(
                                            side_effect=asyncio.CancelledError()
                                        )

                                        try:
                                            await _async_main(config_path, mock_logger)
                                        except asyncio.CancelledError:
                                            pass

                                # Verify config was loaded
                                mock_config_cls.from_file.assert_called_once_with(
                                    config_path
                                )
                                mock_logger.info.assert_any_call(
                                    "CONFIG_LOADED", path=str(config_path)
                                )


@pytest.mark.asyncio
async def test_async_main_initializes_all_components():
    """_async_main initializes DatabaseManager, SessionPrewarmer, CheckoutFlow, StockMonitor."""
    from daemon import _async_main

    config_path = Path("/fake/config.yaml")
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.error = MagicMock()
    mock_logger.warning = MagicMock()

    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("daemon.DatabaseManager") as mock_db_cls:
        mock_db = MagicMock()
        mock_db.initialize = MagicMock()
        mock_db_cls.return_value = mock_db

        with patch("daemon.SessionPrewarmer") as mock_pw_cls:
            mock_pw = MagicMock()
            mock_pw_cls.return_value = mock_pw

            with patch("daemon.CartManager") as mock_cm_cls:
                mock_cm = MagicMock()
                mock_cm_cls.return_value = mock_cm

                with patch("daemon.CheckoutFlow") as mock_cf_cls:
                    mock_cf = MagicMock()
                    mock_cf_cls.return_value = mock_cf

                    with patch("daemon.StockMonitor") as mock_sm_cls:
                        mock_sm_cls.return_value = mock_monitor

                        with patch("daemon.CrashRecovery") as mock_cr_cls:
                            mock_cr = MagicMock()
                            mock_cr.__enter__ = MagicMock(return_value=None)
                            mock_cr.__exit__ = MagicMock(return_value=None)
                            mock_cr_cls.return_value = mock_cr

                            with patch("daemon.Config") as mock_config_cls:
                                mock_config = MagicMock()
                                mock_config_cls.from_file.return_value = mock_config

                                # Prevent _build_webhook_callback from trying to create
                                # DiscordWebhook/TelegramWebhook with MagicMock config values
                                with patch(
                                    "daemon._build_webhook_callback",
                                    MagicMock(return_value=None),
                                ):
                                    try:
                                        await _async_main(config_path, mock_logger)
                                    except asyncio.CancelledError:
                                        pass

    # Verify all components were initialized
    mock_db_cls.assert_called_once()
    mock_pw_cls.assert_called_once()
    mock_cm_cls.assert_called_once()
    mock_cf_cls.assert_called_once()
    mock_sm_cls.assert_called_once()

    # Verify expected log events
    logged_events = [c[0][0] for c in mock_logger.info.call_args_list]
    assert "CONFIG_LOADED" in logged_events
    assert "DATABASE_INITIALIZED" in logged_events
    assert "SESSION_PREWARMER_INITIALIZED" in logged_events
    assert "CHECKOUT_FLOW_INITIALIZED" in logged_events


# ── Test signal handler registration ────────────────────────────────────────

@pytest.mark.asyncio
async def test_signal_handlers_registered_on_start():
    """Signal handlers for SIGTERM and SIGINT are registered when daemon starts."""
    from daemon import _async_main

    config_path = Path("/fake/config.yaml")
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.error = MagicMock()
    mock_logger.warning = MagicMock()

    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("daemon.DatabaseManager") as mock_db_cls:
        mock_db = MagicMock()
        mock_db.initialize = MagicMock()
        mock_db_cls.return_value = mock_db

        with patch("daemon.SessionPrewarmer") as mock_pw_cls:
            mock_pw = MagicMock()
            mock_pw_cls.return_value = mock_pw

            with patch("daemon.CartManager") as mock_cm_cls:
                mock_cm = MagicMock()
                mock_cm_cls.return_value = mock_cm

                with patch("daemon.CheckoutFlow") as mock_cf_cls:
                    mock_cf = MagicMock()
                    mock_cf_cls.return_value = mock_cf

                    with patch("daemon.StockMonitor") as mock_sm_cls:
                        mock_sm_cls.return_value = mock_monitor

                        with patch("daemon.CrashRecovery") as mock_cr_cls:
                            mock_cr = MagicMock()
                            mock_cr.__enter__ = MagicMock(return_value=None)
                            mock_cr.__exit__ = MagicMock(return_value=None)
                            mock_cr_cls.return_value = mock_cr

                            with patch("daemon.Config") as mock_config_cls:
                                mock_config = MagicMock()
                                mock_config_cls.from_file.return_value = mock_config

                                # Prevent _build_webhook_callback from trying to create
                                # DiscordWebhook/TelegramWebhook with MagicMock config values
                                with patch(
                                    "daemon._build_webhook_callback",
                                    MagicMock(return_value=None),
                                ):
                                    # Patch signal.signal in daemon module
                                    mock_sig = MagicMock(
                                        return_value=stdlib_signal.SIG_DFL
                                    )
                                    with patch(
                                        "daemon.signal.signal", mock_sig
                                    ):
                                        try:
                                            await _async_main(
                                                config_path, mock_logger
                                            )
                                        except BaseException:
                                            pass

    # Verify SIGTERM and SIGINT handlers were registered
    sig_calls = [
        c for c in mock_sig.call_args_list
        if c[0][0] in (stdlib_signal.SIGTERM, stdlib_signal.SIGINT)
    ]
    assert len(sig_calls) >= 2, (
        f"Expected SIGTERM and SIGINT handlers, got {sig_calls}"
    )
