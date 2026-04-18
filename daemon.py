"""daemon.py — PokeDrop Bot daemon entry point.

Runs silently in the background. Handles all bot logic:
monitoring, cart, checkout, evasion, and command queue processing.

Per PRD Section 7: Two-process model (daemon + dashboard).
The daemon processes commands from the dashboard via the state.db command queue.

Usage:
    python daemon.py [--config path/to/config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
from src.shared.models import WebhookEvent


# ── Command Poller ──────────────────────────────────────────────────────────────

_COMMAND_POLL_INTERVAL_SEC = 1.0  # Poll every 1 second


def _build_webhook_callback(config: Config) -> Any:
    """Build a combined webhook callback that sends to all configured notifiers.

    Creates DiscordWebhook and/or TelegramWebhook instances based on config,
    then returns an async callback that delivers events to all configured endpoints.
    Returns None if no webhook URLs are configured.
    """
    clients: list[Any] = []

    # Discord
    if config.notifications.discord_webhook_url:
        try:
            from src.bot.notifications.discord import DiscordWebhook
            clients.append(DiscordWebhook(config.notifications.discord_webhook_url))
        except ValueError:
            pass  # Invalid URL — skip

    # Telegram
    if config.notifications.telegram_bot_token and config.notifications.telegram_chat_id:
        try:
            from src.bot.notifications.telegram import TelegramWebhook
            telegram_url = (
                f"https://api.telegram.org/bot{config.notifications.telegram_bot_token}/sendMessage"
            )
            clients.append(
                TelegramWebhook(
                    webhook_url=telegram_url,
                    chat_id=config.notifications.telegram_chat_id,
                )
            )
        except ValueError:
            pass  # Invalid token/chat_id — skip

    if not clients:
        return None

    async def callback(event: WebhookEvent) -> None:
        for client in clients:
            try:
                await client.send(event)
            except Exception:
                pass  # Best effort — don't fail one client due to another

    return callback


async def _command_poller(
    db: DatabaseManager,
    monitor: StockMonitor,
    checkout_flow: CheckoutFlow,
    config: Config,
    logger: Logger,
    shutdown_event: asyncio.Event,
) -> None:
    """Poll the command queue and process dashboard commands.

    Handles: start, stop, restart, dryrun.
    Runs until shutdown_event is set.

    Per PRD Section 7.1 (Daemon ↔ Dashboard communication):
      - Dashboard enqueues commands via state.db command_queue table
      - Daemon polls and processes them asynchronously
    """
    logger.info("COMMAND_POLLER_STARTED")

    # Ensure monitor knows about the shutdown event so it can stop gracefully
    # Give monitor reference to shutdown event for graceful teardown
    monitor._daemon_shutdown_event = shutdown_event

    while not shutdown_event.is_set():
        await asyncio.sleep(_COMMAND_POLL_INTERVAL_SEC)

        try:
            # Claim the oldest pending command
            cmd = db.claim_pending_command()
            if cmd is None:
                continue

            command_id = cmd["id"]
            command_name = cmd["command"]
            args = json.loads(cmd["args_json"]) if cmd["args_json"] else {}

            logger.info(
                "COMMAND_RECEIVED",
                command_id=command_id,
                command=command_name,
            )

            try:
                if command_name == "start":
                    await _handle_start_command(monitor, logger)
                    db.complete_command(command_id, status="completed")

                elif command_name == "stop":
                    await _handle_stop_command(monitor, logger)
                    db.complete_command(command_id, status="completed")

                elif command_name == "restart":
                    await _handle_stop_command(monitor, logger)
                    await asyncio.sleep(0.5)
                    await _handle_start_command(monitor, logger)
                    db.complete_command(command_id, status="completed")

                elif command_name == "dryrun":
                    success = await _handle_dryrun_command(
                        monitor=monitor,
                        checkout_flow=checkout_flow,
                        config=config,
                        logger=logger,
                        command_id=command_id,
                        args=args,
                    )
                    db.complete_command(command_id, status="completed" if success else "failed")

                else:
                    logger.warning("COMMAND_UNKNOWN", command=command_name)
                    db.complete_command(command_id, status="failed")

            except Exception as exc:
                logger.error("COMMAND_FAILED", command=command_name, error=str(exc))
                db.complete_command(command_id, status="failed")

        except Exception as exc:
            # DB error — log and continue polling
            logger.error("COMMAND_POLL_ERROR", error=str(exc))
            await asyncio.sleep(5)  # Back off on DB errors

    logger.info("COMMAND_POLLER_STOPPED")


async def _handle_start_command(monitor: StockMonitor, logger: Logger) -> None:
    """Handle 'start' command: begin monitoring."""
    if monitor.is_running():
        logger.info("COMMAND_START_IGNORED_ALREADY_RUNNING")
        return

    logger.info("COMMAND_START_INITIATED")
    # _monitor_requested is a one-shot event — clear it first if this is a restart
    # so start() will wait for it again
    monitor._monitor_requested.clear()
    # Signal the monitor to begin its monitoring loop
    monitor._monitor_requested.set()
    logger.info("COMMAND_START_COMPLETE")


async def _handle_stop_command(monitor: StockMonitor, logger: Logger) -> None:
    """Handle 'stop' command: pause monitoring gracefully (daemon keeps running)."""
    if not monitor.is_running():
        logger.info("COMMAND_STOP_IGNORED_NOT_RUNNING")
        return

    logger.info("COMMAND_STOP_INITIATED")
    await monitor.stop_monitoring()
    logger.info("COMMAND_STOP_COMPLETE")


async def _handle_dryrun_command(
    monitor: StockMonitor,
    checkout_flow: CheckoutFlow,
    config: Config,
    logger: Logger,
    command_id: int,
    args: dict[str, Any],
) -> bool:
    """Handle 'dryrun' command: run full checkout flow without placing order.

    Returns True on success, False on failure.
    """
    logger.info("DRYRUN_STARTED", command_id=command_id)

    # Determine which item/retailer to dry-run, or use first configured
    item_name = args.get("item")
    retailer_name = args.get("retailer")
    sku = args.get("sku")

    if not item_name or not retailer_name or not sku:
        # Use first enabled item from config
        for rname, rcfg in config.retailers.items():
            if rcfg.enabled and rcfg.items:
                item_def = rcfg.items[0]
                item_name = item_def.get("name", "unknown")
                retailer_name = rname
                sku = (item_def.get("skus") or [None])[0]
                break

    if not item_name or not retailer_name or not sku:
        logger.error("DRYRUN_NO_ITEM", message="No item/retailer/sku configured for dryrun")
        return False

    try:
        adapter = await monitor._get_adapter_for_retailer(retailer_name)
        if adapter is None:
            logger.error("DRYRUN_NO_ADAPTER", retailer=retailer_name)
            return False

        # Run the full checkout flow in dry-run mode
        result = await checkout_flow.run(
            adapter=adapter,
            sku=sku,
            item_name=item_name,
            dry_run=True,
        )

        if result.success:
            logger.info(
                "DRYRUN_COMPLETED",
                command_id=command_id,
                item=item_name,
                retailer=retailer_name,
                order_id=result.order_id,
            )
            return True
        else:
            logger.warning(
                "DRYRUN_FAILED",
                command_id=command_id,
                item=item_name,
                retailer=retailer_name,
                stage=result.stage,
                error=result.error,
            )
            return False

    except Exception as exc:
        logger.error("DRYRUN_ERROR", command_id=command_id, error=str(exc))
        return False


# ── Daemon main ────────────────────────────────────────────────────────────────

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

    Initializes all components, runs the stock monitor (waiting for start command),
    and processes dashboard commands via the command queue.
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
        session_prewarmer=session_prewarmer,
    )
    logger.info("CHECKOUT_FLOW_INITIALIZED")

    # Build webhook callback for DROP_WINDOW events (PHASE3-T04)
    webhook_callback = _build_webhook_callback(config)

    # Initialize stock monitor
    monitor = StockMonitor(
        config=config,
        logger=logger,
        checkout_flow=checkout_flow,
        session_prewarmer=session_prewarmer,
        webhook_callback=webhook_callback,
    )
    logger.info("STOCK_MONITOR_INITIALIZED")

    # Shared shutdown event — used by both signal handlers and command poller
    shutdown_event: asyncio.Event = asyncio.Event()

    def _handle_sigterm(signum: int, frame: Any) -> None:
        logger.warning("RECEIVED_SIGTERM", signal="SIGTERM")
        shutdown_event.set()
        # Trigger graceful shutdown of monitor
        asyncio.create_task(monitor.trigger_shutdown())

    def _handle_sigint(signum: int, frame: Any) -> None:
        logger.warning("RECEIVED_SIGINT", signal="SIGINT")
        shutdown_event.set()
        # Trigger graceful shutdown of monitor
        asyncio.create_task(monitor.trigger_shutdown())

    # Install signal handlers
    prev_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)
    prev_sigint = signal.signal(signal.SIGINT, _handle_sigint)

    # Crash recovery — wrap main loop
    crash = CrashRecovery(state_dir=Path.cwd())

    try:
        logger.info("DAEMON_STARTING")

        with crash:
            # Run monitor + command poller concurrently
            # Monitor waits for start command before beginning actual monitoring
            # Command poller processes dashboard commands from state.db
            monitor_task = asyncio.create_task(monitor.start())
            poller_task = asyncio.create_task(
                _command_poller(
                    db=db,
                    monitor=monitor,
                    checkout_flow=checkout_flow,
                    config=config,
                    logger=logger,
                    shutdown_event=shutdown_event,
                )
            )

            # Wait for either to finish (poller runs until shutdown;
            # monitor finishes when shutdown is set)
            done, pending = await asyncio.wait(
                [monitor_task, poller_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel any remaining tasks
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

            # Check which one finished first
            if not shutdown_event.is_set():
                # Neither poller nor signal set shutdown — one of the tasks failed
                for d in done:
                    if d.exception() is not None:
                        logger.error(
                            "DAEMON_TASK_FAILED",
                            error=str(d.exception()),
                        )

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
