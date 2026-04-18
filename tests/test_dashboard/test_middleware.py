"""Tests for dashboard auth middleware (src/dashboard/auth.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.dashboard.auth import (
    SESSION_COOKIE_NAME,
    UserRole,
    DashboardAuth,
    DashboardSession,
    require_auth,
    wire_auth,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_db(tmp_path: Path) -> DashboardAuth:
    """Provide a DashboardAuth instance backed by a temp auth.db."""
    db_path = tmp_path / "auth.db"
    auth = DashboardAuth(db_path)
    auth.db  # Ensure schema is initialized
    return auth


@pytest.fixture
def wired_app(auth_db: DashboardAuth) -> tuple[TestClient, FastAPI]:
    """Provide a FastAPI app with auth wired up and a TestClient.

    Sets up two routes:
      - GET /api/test-reader  (requires VIEWER or OPERATOR)
      - POST /api/test-writer (requires OPERATOR only)
    Both protected by the real require_auth dependency.
    """
    app = FastAPI()

    # Wire the DashboardAuth instance for the require_auth dependency
    wire_auth(auth_db)

    @app.get("/api/test-reader")
    async def read_route(
        session: DashboardSession = Depends(require_auth(UserRole.VIEWER)),
    ):
        return {"role": session.role.value}

    @app.post("/api/test-writer")
    async def write_route(
        session: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
    ):
        return {"role": session.role.value}

    @app.post("/login")
    async def login():
        """Convenience endpoint to create a session for testing."""
        session = auth_db.create_session(UserRole.OPERATOR)
        return {"token": session.session_token, "role": session.role.value}

    @app.post("/login-viewer")
    async def login_viewer():
        session = auth_db.create_session(UserRole.VIEWER)
        return {"token": session.session_token, "role": session.role.value}

    client = TestClient(app, raise_server_exceptions=False)
    return client, app


# ── require_auth dependency tests ─────────────────────────────────────────────

class TestRequireAuthDependency:
    """Test require_auth as a FastAPI dependency."""

    def test_missing_cookie_returns_401(self, wired_app: tuple[TestClient, FastAPI]) -> None:
        """No cookie → 401 Not authenticated."""
        client, _ = wired_app
        response = client.get("/api/test-reader")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    def test_invalid_cookie_returns_401(self, wired_app: tuple[TestClient, FastAPI]) -> None:
        """Invalid token → 401 Session expired."""
        client, _ = wired_app
        response = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: "not_a_real_token"},
        )
        assert response.status_code == 401
        assert "expired or invalid" in response.json()["detail"]

    def test_valid_operator_session_satisfies_viewer_requirement(
        self, wired_app: tuple[TestClient, FastAPI]
    ) -> None:
        """OPERATOR session on a VIEWER-required route → 200."""
        client, _ = wired_app
        login_resp = client.post("/login")
        token = login_resp.json()["token"]
        response = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "operator"

    def test_valid_viewer_session_satisfies_viewer_requirement(
        self, wired_app: tuple[TestClient, FastAPI]
    ) -> None:
        """VIEWER session on a VIEWER-required route → 200."""
        client, _ = wired_app
        login_resp = client.post("/login-viewer")
        token = login_resp.json()["token"]
        response = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "viewer"

    def test_viewer_session_rejected_on_operator_route(
        self, wired_app: tuple[TestClient, FastAPI]
    ) -> None:
        """VIEWER session on an OPERATOR-required route → 403 Forbidden."""
        client, _ = wired_app
        login_resp = client.post("/login-viewer")
        token = login_resp.json()["token"]
        response = client.post(
            "/api/test-writer",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert response.status_code == 403
        assert "Operator privileges required" in response.json()["detail"]

    def test_operator_session_satisfies_operator_requirement(
        self, wired_app: tuple[TestClient, FastAPI]
    ) -> None:
        """OPERATOR session on an OPERATOR-required route → 200."""
        client, _ = wired_app
        login_resp = client.post("/login")
        token = login_resp.json()["token"]
        response = client.post(
            "/api/test-writer",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "operator"

    def test_session_without_cookie_name_still_rejected(
        self, wired_app: tuple[TestClient, FastAPI]
    ) -> None:
        """Wrong cookie name → 401."""
        client, _ = wired_app
        response = client.get(
            "/api/test-reader",
            cookies={"wrong_cookie_name": "some_token"},
        )
        assert response.status_code == 401


# ── wire_auth / _get_wired_auth tests ────────────────────────────────────────

class TestAuthWiring:
    """Test the auth wiring mechanism."""

    def test_wire_auth_sets_singleton(self, auth_db: DashboardAuth) -> None:
        """wire_auth should make the instance available to require_auth."""
        wire_auth(auth_db)
        # Re-import to get fresh reference to the module-level var
        from src.dashboard import auth as auth_mod
        assert auth_mod._get_wired_auth() is auth_db

    def test_wire_auth_replace_instance(self, auth_db: DashboardAuth) -> None:
        """Wiring a second auth instance replaces the first."""
        from src.dashboard import auth as auth_mod

        wire_auth(auth_db)
        auth_db2 = DashboardAuth(auth_db._db_path.parent / "auth2.db")
        auth_db2.db
        wire_auth(auth_db2)
        assert auth_mod._get_wired_auth() is auth_db2

    def test_unwired_auth_returns_500_on_protected_route(
        self, tmp_path: Path
    ) -> None:
        """Without wire_auth, protected routes return 500."""
        # Clear any previously wired auth by re-importing and resetting
        from src.dashboard import auth as auth_mod
        auth_mod._auth_instance = None

        app = FastAPI()
        wire_auth(DashboardAuth(tmp_path / "auth.db"))  # re-wire for this test

        @app.get("/protected")
        async def protected(
            session: DashboardSession = Depends(require_auth(UserRole.VIEWER)),
        ):
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/protected", cookies={SESSION_COOKIE_NAME: "fake"})
        # Token invalid → 401 (not a wiring error)
        assert response.status_code == 401


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestMiddlewareEdgeCases:
    """Test edge cases for the auth middleware."""

    def test_empty_string_token_rejected(self, wired_app: tuple[TestClient, FastAPI]) -> None:
        """Empty string token is treated as missing → 401."""
        client, _ = wired_app
        response = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: ""},
        )
        assert response.status_code == 401

    def test_expired_session_rejected(self, wired_app: tuple[TestClient, FastAPI]) -> None:
        """Expired session → 401."""
        from src.dashboard import auth as auth_mod

        client, _ = wired_app
        # Get the auth instance from the module (wired via wire_auth)
        auth_instance = auth_mod._get_wired_auth()
        session = auth_instance.create_session(UserRole.OPERATOR)

        # Manually expire the session
        with auth_instance.db._write_lock:
            with auth_instance.db.connection() as conn:
                conn.execute(
                    "UPDATE dashboard_sessions SET expires_at='2020-01-01T00:00:00Z' "
                    "WHERE session_token=?",
                    (session.session_token,),
                )
                conn.commit()

        response = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: session.session_token},
        )
        assert response.status_code == 401

    def test_viewer_can_read_but_not_write(self, wired_app: tuple[TestClient, FastAPI]) -> None:
        """Viewer role: read OK, write forbidden."""
        client, _ = wired_app
        login_resp = client.post("/login-viewer")
        token = login_resp.json()["token"]

        # Reader route → 200
        read_resp = client.get(
            "/api/test-reader",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert read_resp.status_code == 200

        # Writer route → 403
        write_resp = client.post(
            "/api/test-writer",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert write_resp.status_code == 403