"""daemon.py — PokeDrop Bot daemon entry point.

Runs silently in the background. Handles all bot logic:
monitoring, cart, checkout, evasion.

Per PRD Section 7: Two-process model (daemon + dashboard).

Usage:
    python daemon.py [--config path/to/config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

from src.bot.config import Config
from src.bot.logger import Logger, init_logger
from src.bot.monitor.stock_monitor import StockMonitor
from src.bot.session.prewarmer import SessionPrewarmer
from src.bot.checkout.cart_manager import CartManager
from src.bot.checkout.checkout_flow import CheckoutFlow
from src.shared.crash_recovery import CrashRecovery
from src.shared.db import DatabaseManager


async def _run_monitor(monitor: StockMonitor) -> None:
    """Run the stock monitor (awaitable entry point)."""
    await monitor.start()


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="PokeDrop Bot — background daemon for stock monitoring and checkout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml in cwd)",
    )
    return parser.parse_args()


async def _async_main(config_path: Path, logger: Logger) -> None:
    """Async main entry point for the daemon.

    Initializes all components and runs the stock monitor loop.
    """
    # Load and validate config
    try:
        config = Config.from_file(config_path)
        logger.info("CONFIG_LOADED", path=str(config_path))
    except Exception as exc:
        logger.error("CONFIG_LOAD_FAILED", error=str(exc))
        raise

    # Initialize database
    db = DatabaseManager(db_path=Path("state.db"))
    db.initialize()
    logger.info("DATABASE_INITIALIZED", path=str(db.path))

    # Initialize session prewarmer
    session_prewarmer = SessionPrewarmer(
        config=config,
        logger=logger,
        db=db,
    )
    logger.info("SESSION_PREWARMER_INITIALIZED")

    # Initialize checkout flow
    cart_manager = CartManager(config=config, logger=logger)
    checkout_flow = CheckoutFlow(
        config=config,
        logger=logger,
        cart_manager=cart_manager,
    )
    logger.info("CHECKOUT_FLOW_INITIALIZED")

    # Initialize stock monitor
    monitor = StockMonitor(
        config=config,
        logger=logger,
        checkout_flow=checkout_flow,
        session_prewarmer=session_prewarmer,
    )

    # Crash recovery — wrap main loop
    crash = CrashRecovery(state_dir=Path.cwd())

    def _handle_sigterm(signum: int, frame: Any) -> None:
        logger.warning("RECEIVED_SIGTERM", signal="SIGTERM")
        asyncio.create_task(monitor.stop())

    def _handle_sigint(signum: int, frame: Any) -> None:
        logger.warning("RECEIVED_SIGINT", signal="SIGINT")
        asyncio.create_task(monitor.stop())

    # Install signal handlers
    prev_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)
    prev_sigint = signal.signal(signal.SIGINT, _handle_sigint)

    try:
        logger.info("DAEMON_STARTING")

        with crash:
            # Run monitor — blocks until shutdown
            await _run_monitor(monitor)

    except asyncio.CancelledError:
        logger.warning("DAEMON_CANCELLED")
    except Exception as exc:
        logger.error("DAEMON_ERROR", error=str(exc))
        raise
    finally:
        # Restore signal handlers
        signal.signal(signal.SIGTERM, prev_sigterm)
        signal.signal(signal.SIGINT, prev_sigint)
        logger.info("DAEMON_STOPPED")


def main() -> None:
    """Main entry point for the daemon."""
    args = _parse_args()
    config_path = Path(args.config)

    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    # Initialize logger (singleton)
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger_instance = init_logger(log_dir=log_dir)

    logger_instance.info(
        "DAEMON_LAUNCHED",
        config=str(config_path),
    )

    exception_to_raise: BaseException | None = None

    _exit_code = 0
    try:
        asyncio.run(_async_main(config_path, logger_instance))
    except KeyboardInterrupt:
        pass  # Handled by SIGINT handler
    except FileNotFoundError as exc:
        logger_instance.error("DAEMON_CONFIG_NOT_FOUND", error=str(exc))
        _exit_code = 1
    except BaseException as exc:
        logger_instance.error("DAEMON_UNHANDLED", error=str(exc))
        _exit_code = 1
    finally:
        logger_instance.info("DAEMON_EXIT")

    sys.exit(_exit_code)


if __name__ == "__main__":
    main()
