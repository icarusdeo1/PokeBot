"""Dashboard route modules.

Each module exposes route handlers that are registered in server.py.
"""

from src.dashboard.routes import config, daemon_restart, events, health, monitor, status

__all__ = ["config", "daemon_restart", "events", "health", "monitor", "status"]
