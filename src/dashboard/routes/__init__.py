"""Dashboard route modules.

Each module exposes route handlers that are registered in server.py.
"""

from src.dashboard.routes import events, status

__all__ = ["events", "status"]
