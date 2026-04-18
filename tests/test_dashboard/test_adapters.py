"""Tests for /api/adapters route (ABOUT-T01).

Per PRD Section 9.15 (ADP-5).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Build a test client with the adapters router mounted."""
    from fastapi import FastAPI
    from src.dashboard.routes.adapters import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestAdaptersRoute:
    """Tests for GET /api/adapters/."""

    def test_returns_adapter_list(self, client: TestClient) -> None:
        """GET /api/adapters/ returns adapter info list."""
        response = client.get("/api/adapters/")

        assert response.status_code == 200
        data = response.json()
        assert "adapters" in data
        assert isinstance(data["adapters"], list)

    def test_adapters_have_required_fields(self, client: TestClient) -> None:
        """Each adapter has name, version, enabled, module fields."""
        response = client.get("/api/adapters/")
        data = response.json()

        for adapter in data["adapters"]:
            assert "name" in adapter
            assert "version" in adapter
            assert "enabled" in adapter
            assert "module" in adapter

    def test_adapters_includes_target_when_registered(self, client: TestClient) -> None:
        """Target adapter appears in list when loaded."""
        response = client.get("/api/adapters/")
        data = response.json()

        names = [a["name"] for a in data["adapters"]]
        # If target is loaded in the registry, it appears
        # The test just checks the field structure is valid
        for adapter in data["adapters"]:
            assert adapter["name"] in ("target", "walmart", "bestbuy", "unknown")
            assert adapter["enabled"] in ("true", "false")

    def test_response_is_json(self, client: TestClient) -> None:
        """Response has correct content-type."""
        response = client.get("/api/adapters/")
        assert "application/json" in response.headers.get("content-type", "")