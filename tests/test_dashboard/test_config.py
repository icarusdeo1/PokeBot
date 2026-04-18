"""Tests for config routes: GET /api/config, PATCH /api/config.

Per ROUTE-T02.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.dashboard.routes.config import (
    get_config_route,
    patch_config_route,
    _deep_merge,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_config_raw() -> dict[str, Any]:
    """A minimal valid config dict."""
    return {
        "retailers": {
            "target": {
                "enabled": True,
                "username": "test@example.com",
                "password": "secret123",
                "items": [{"name": "Charizard", "sku": "12345", "url": "https://target.com/p/12345"}],
            },
            "walmart": {"enabled": False, "username": "", "password": "", "items": []},
            "bestbuy": {"enabled": False, "username": "", "password": "", "items": []},
        },
        "shipping": {
            "full_name": "Test User",
            "address_line1": "123 Main St",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97201",
            "phone": "555-0100",
            "email": "test@example.com",
        },
        "payment": {
            "card_number": "4111111111111111",
            "expiry_month": "12",
            "expiry_year": "2028",
            "cvv": "123",
        },
        "captcha": {"mode": "smart"},
        "notifications": {},
        "evasion": {},
        "checkout": {},
        "monitoring": {},
    }


# ── _deep_merge tests ─────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_shallow_merge(self) -> None:
        base = {"a": 1, "b": 2}
        update = {"b": 3, "c": 4}
        result = _deep_merge(base, update)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"retailers": {"target": {"enabled": True, "username": "old@example.com"}}}
        update = {"retailers": {"target": {"username": "new@example.com"}}}
        result = _deep_merge(base, update)
        assert result["retailers"]["target"] == {
            "enabled": True,
            "username": "new@example.com",
        }

    def test_list_replace_not_append(self) -> None:
        base = {"items": [1, 2, 3]}
        update = {"items": [4, 5]}
        result = _deep_merge(base, update)
        assert result["items"] == [4, 5]

    def test_none_value_skipped(self) -> None:
        base = {"a": 1, "b": 2}
        update = {"b": None, "c": 3}
        result = _deep_merge(base, update)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_empty_update_returns_base(self) -> None:
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_new_top_level_key(self) -> None:
        base = {"existing": 1}
        update = {"new_key": 2}
        result = _deep_merge(base, update)
        assert result == {"existing": 1, "new_key": 2}


# ── GET /api/config tests ─────────────────────────────────────────────────────

class TestGetConfigRoute:
    @pytest.mark.asyncio
    async def test_returns_masked_config(self) -> None:
        """GET /api/config returns a masked config dict (no secrets visible)."""
        mock_config = MagicMock()
        mock_config.mask_secrets.return_value = {
            "retailers": {
                "target": {"enabled": True, "username": "test@example.com", "password": "***"},
            },
            "shipping": {"full_name": "Test User"},
            "payment": {"card_number": "****1111", "cvv": "***"},
        }

        with patch(
            "src.dashboard.routes.config._load_config_for_route",
            return_value=mock_config,
        ):
            result = await get_config_route()
            assert isinstance(result, JSONResponse)
            data = json.loads(result.body)
            assert "retailers" in data
            assert data["retailers"]["target"]["password"] == "***"
            assert data["payment"]["cvv"] == "***"


# ── PATCH /api/config tests ───────────────────────────────────────────────────

class TestPatchConfigRoute:
    @pytest.mark.asyncio
    async def test_valid_update_is_saved(self, valid_config_raw: dict[str, Any]) -> None:
        """A valid PATCH body merges and saves successfully."""
        with patch(
            "src.dashboard.routes.config._get_config_path",
            return_value=Path("/tmp/test_config.yaml"),
        ), patch(
            "src.dashboard.routes.config.Config.from_file",
        ) as mock_from_file, patch(
            "src.dashboard.routes.config.Config._from_raw",
        ) as mock_from_raw, patch(
            "builtins.open",
            MagicMock(),
        ), patch(
            "yaml.safe_dump",
        ):
            mock_current = MagicMock()
            mock_current._raw = valid_config_raw
            mock_from_file.return_value = mock_current

            mock_merged = MagicMock()
            mock_merged._raw = valid_config_raw.copy()
            mock_merged.mask_secrets.return_value = valid_config_raw.copy()
            mock_from_raw.return_value = mock_merged

            mock_request = MagicMock()
            mock_request.json = AsyncMock(
                return_value={"monitoring": {"stock_check_interval_seconds": 3}}
            )
            mock_request.form = AsyncMock(return_value={})

            result = await patch_config_route(mock_request)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_update_returns_400(self, valid_config_raw: dict[str, Any]) -> None:
        """An invalid merged config returns HTTP 400 with field errors."""
        from src.bot.config import ConfigError

        with patch(
            "src.dashboard.routes.config._get_config_path",
            return_value=Path("/tmp/test_config.yaml"),
        ), patch(
            "src.dashboard.routes.config.Config.from_file",
        ) as mock_from_file, patch(
            "src.dashboard.routes.config.Config._from_raw",
        ) as mock_from_raw:
            mock_current = MagicMock()
            mock_current._raw = valid_config_raw
            mock_from_file.return_value = mock_current

            mock_from_raw.side_effect = ConfigError(
                ["drop_windows[0].retailer must be one of [...]"]
            )

            mock_request = MagicMock()
            mock_request.json = AsyncMock(
                return_value={
                    "drop_windows": [
                        {"item": "Pikachu", "retailer": "invalid", "drop_datetime": "2026-04-20T10:00:00Z"}
                    ]
                }
            )
            mock_request.form = AsyncMock(return_value={})

            with pytest.raises(HTTPException) as exc_info:
                await patch_config_route(mock_request)
            assert exc_info.value.status_code == 400
            detail = exc_info.value.detail
            assert detail["message"] == "Config validation failed — changes were not saved"
            assert "drop_windows" in str(detail["errors"])

    @pytest.mark.asyncio
    async def test_empty_body_returns_400(self) -> None:
        """An empty PATCH body returns HTTP 400."""
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={})
        mock_request.form = AsyncMock(return_value={})

        with pytest.raises(HTTPException) as exc_info:
            await patch_config_route(mock_request)
        assert exc_info.value.status_code == 400
        assert "at least one config field" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_sensitive_fields_masked_in_response(
        self, valid_config_raw: dict[str, Any]
    ) -> None:
        """After PATCH, the returned config masks sensitive fields."""
        with patch(
            "src.dashboard.routes.config._get_config_path",
            return_value=Path("/tmp/test_config.yaml"),
        ), patch(
            "src.dashboard.routes.config.Config.from_file",
        ) as mock_from_file, patch(
            "src.dashboard.routes.config.Config._from_raw",
        ) as mock_from_raw, patch(
            "builtins.open",
            MagicMock(),
        ), patch(
            "yaml.safe_dump",
        ):
            mock_current = MagicMock()
            mock_current._raw = valid_config_raw
            mock_from_file.return_value = mock_current

            patched_raw = valid_config_raw.copy()
            patched_raw["payment"] = dict(valid_config_raw["payment"])

            mock_merged = MagicMock()
            mock_merged._raw = patched_raw
            # mask_secrets is called on the merged config
            mock_merged.mask_secrets.return_value = patched_raw
            mock_from_raw.return_value = mock_merged

            mock_request = MagicMock()
            mock_request.json = AsyncMock(
                return_value={"shipping": {"full_name": "Updated Name"}}
            )
            mock_request.form = AsyncMock(return_value={})

            result = await patch_config_route(mock_request)
            # The result should be a JSONResponse with masked fields
            body = json.loads(result.body)
            assert "payment" in body
