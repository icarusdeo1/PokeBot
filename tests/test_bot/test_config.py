"""Tests for bot/config.py (SHARED-T04: Config loading and validation)."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from src.bot.config import (
    Config,
    ConfigError,
    _apply_env_overrides,
    _is_valid_card_number,
    _set_nested,
    _get_nested,
    _deep_copy_dict,
)


# ── Test Fixtures ─────────────────────────────────────────────────────────────


def minimal_valid_config() -> dict:
    """Return a minimally valid config dict for testing."""
    return {
        "retailers": {
            "target": {
                "enabled": True,
                "username": "user@example.com",
                "password": "password123",
                "items": [{"sku": "123456", "keyword": "pikachu", "max_price": 100.0}],
            },
            "walmart": {"enabled": False, "username": "", "password": "", "items": []},
            "bestbuy": {"enabled": False, "username": "", "password": "", "items": []},
        },
        "shipping": {
            "full_name": "Jane Doe",
            "address_line1": "123 Main St",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97201",
            "phone": "555-123-4567",
        },
        "payment": {
            "card_number": "4111111111111111",
            "expiry_month": "12",
            "expiry_year": "2027",
            "cvv": "123",
        },
    }


def write_config_file(tmp_dir: Path, config: dict) -> Path:
    """Write a config dict to config.yaml in tmp_dir and return path."""
    path = tmp_dir / "config.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


# ── Helper Function Tests ─────────────────────────────────────────────────────


class TestIsValidCardNumber:
    """Test _is_valid_card_number helper."""

    def test_valid_16_digits(self) -> None:
        assert _is_valid_card_number("4111111111111111") is True

    def test_valid_15_digits_amex(self) -> None:
        assert _is_valid_card_number("378282246310005") is True

    def test_valid_13_digits(self) -> None:
        assert _is_valid_card_number("4222222222222") is True

    def test_invalid_too_short(self) -> None:
        assert _is_valid_card_number("411111111111") is False

    def test_invalid_too_long(self) -> None:
        assert _is_valid_card_number("41111111111111111111") is False

    def test_invalid_non_digits_only(self) -> None:
        assert _is_valid_card_number("abc-defg-hijk") is False

    def test_invalid_empty(self) -> None:
        assert _is_valid_card_number("") is False


class TestSetNested:
    """Test _set_nested helper."""

    def test_sets_nested_value(self) -> None:
        d: dict = {"a": {}}
        _set_nested(d, ["a", "b"], "value")
        assert d == {"a": {"b": "value"}}

    def test_creates_intermediate_dicts(self) -> None:
        d: dict = {}
        _set_nested(d, ["x", "y", "z"], 123)
        assert d == {"x": {"y": {"z": 123}}}

    def test_replaces_existing_value(self) -> None:
        d: dict = {"a": {"b": "old"}}
        _set_nested(d, ["a", "b"], "new")
        assert d["a"]["b"] == "new"


class TestGetNested:
    """Test _get_nested helper."""

    def test_gets_nested_value(self) -> None:
        d = {"a": {"b": "value"}}
        assert _get_nested(d, ["a", "b"], None) == "value"

    def test_returns_default_on_missing_key(self) -> None:
        d = {"a": {}}
        assert _get_nested(d, ["a", "b"], "default") == "default"

    def test_returns_default_on_missing_path(self) -> None:
        d: dict = {}
        assert _get_nested(d, ["x", "y"], "default") == "default"


class TestDeepCopyDict:
    """Test _deep_copy_dict helper."""

    def test_shallow_copy_is_independent(self) -> None:
        original = {"a": 1, "b": 2}
        copy = _deep_copy_dict(original)
        copy["a"] = 99
        assert original["a"] == 1

    def test_nested_dict_is_independent(self) -> None:
        original = {"a": {"b": 1}}
        copy = _deep_copy_dict(original)
        copy["a"]["b"] = 99
        assert original["a"]["b"] == 1

    def test_list_is_copied(self) -> None:
        original = {"a": [{"b": 1}]}
        copy = _deep_copy_dict(original)
        copy["a"][0]["b"] = 99
        assert original["a"][0]["b"] == 1

    def test_empty_dict(self) -> None:
        assert _deep_copy_dict({}) == {}


# ── Apply Env Overrides Tests ─────────────────────────────────────────────────


class TestApplyEnvOverrides:
    """Test _apply_env_overrides helper."""

    def test_no_env_vars_leaves_config_unchanged(self) -> None:
        raw = {"captcha": {"2captcha_api_key": "from-file"}}
        result = _apply_env_overrides(raw)
        assert result["captcha"]["2captcha_api_key"] == "from-file"

    def test_env_var_overrides_file_value(self) -> None:
        raw = {"captcha": {"2captcha_api_key": "from-file"}}
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_2CAPTCHA_KEY", "from-env")
            result = _apply_env_overrides(raw)
        assert result["captcha"]["2captcha_api_key"] == "from-env"

    def test_env_var_sets_value_when_missing_in_file(self) -> None:
        raw = {"captcha": {}}
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_2CAPTCHA_KEY", "from-env")
            result = _apply_env_overrides(raw)
        assert result["captcha"]["2captcha_api_key"] == "from-env"

    def test_missing_env_var_and_missing_file_uses_default(self) -> None:
        raw = {}
        with pytest.MonkeyPatch().context() as mp:
            # No env vars set
            result = _apply_env_overrides(raw)
        assert result["captcha"]["2captcha_api_key"] == ""


# ── Config Loading Tests ───────────────────────────────────────────────────────


class TestConfigFromFile:
    """Test Config.from_file class method."""

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.shipping.full_name == "Jane Doe"
        assert cfg.payment.card_number == "4111111111111111"
        assert cfg.captcha.mode == "smart"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Config.from_file(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("  invalid: [yaml")
        with pytest.raises(yaml.YAMLError):
            Config.from_file(path)


class TestConfigValidation:
    """Test Config._validate() error collection."""

    def test_empty_retailers_section_raises(self, tmp_path: Path) -> None:
        """Missing retailers config should raise an error."""
        config = minimal_valid_config()
        del config["retailers"]
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert any("At least one retailer" in e for e in exc_info.value.errors)

    def test_missing_shipping_key(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        del config["shipping"]
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "Missing required top-level key: 'shipping'" in exc_info.value.errors

    def test_missing_payment_key_raises(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        del config["payment"]
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        # Missing payment top-level key should trigger ConfigError
        assert exc_info.value.errors

    def test_missing_shipping_fields(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["shipping"]["city"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "shipping.city is required" in exc_info.value.errors

    def test_missing_card_number_raises(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["card_number"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        # Error message includes env var hint
        assert any("card_number" in e for e in exc_info.value.errors)

    def test_invalid_card_number_format(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["card_number"] = "123"
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "payment.card_number must be 13-19 digits" in exc_info.value.errors

    def test_invalid_cvv_format(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["cvv"] = "12"
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "payment.cvv must be 3 or 4 digits" in exc_info.value.errors

    def test_invalid_captcha_mode(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["captcha"] = {"mode": "invalid_mode"}
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "captcha.mode must be 'auto', 'manual', or 'smart'" in exc_info.value.errors

    def test_multiple_errors_collected(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["shipping"]["city"] = ""
        config["payment"]["cvv"] = "12"
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        errors = exc_info.value.errors
        assert len(errors) >= 2

    def test_valid_captcha_modes(self, tmp_path: Path) -> None:
        for mode in ["auto", "manual", "smart"]:
            config = minimal_valid_config()
            config["captcha"] = {"mode": mode}
            path = write_config_file(tmp_path, config)
            cfg = Config.from_file(path)
            assert cfg.captcha.mode == mode

    def test_expiry_month_required(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["expiry_month"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "payment.expiry_month is required" in exc_info.value.errors

    def test_expiry_year_required(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["expiry_year"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.raises(ConfigError) as exc_info:
            Config.from_file(path)
        assert "payment.expiry_year is required" in exc_info.value.errors


class TestConfigFieldsPopulated:
    """Test that Config objects correctly populate all sub-configs."""

    def test_shipping_fields(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.shipping.full_name == "Jane Doe"
        assert cfg.shipping.city == "Portland"
        assert cfg.shipping.address_line2 == ""

    def test_payment_fields(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.payment.expiry_month == "12"
        assert cfg.payment.card_number == "4111111111111111"
        assert cfg.payment.cvv == "123"
        assert cfg.payment.billing_address_same_as_shipping is True

    def test_retailers_populated(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert "target" in cfg.retailers
        assert cfg.retailers["target"].enabled is True
        assert cfg.retailers["target"].username == "user@example.com"
        assert len(cfg.retailers["target"].items) == 1

    def test_default_captcha_mode_is_smart(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.captcha.mode == "smart"

    def test_default_jitter_percent(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.evasion.jitter_percent == 20

    def test_default_retry_attempts(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.checkout.retry_attempts == 2

    def test_drop_windows_default_empty(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.drop_windows == []


class TestMaskSecrets:
    """Test Config.mask_secrets() method."""

    def test_masks_card_number(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        masked = cfg.mask_secrets()
        assert masked["payment"]["card_number"] == "****1111"

    def test_masks_cvv(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        masked = cfg.mask_secrets()
        assert masked["payment"]["cvv"] == "***"

    def test_masks_retailer_passwords(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        masked = cfg.mask_secrets()
        assert masked["retailers"]["target"]["password"] == "***"

    def test_masks_captcha_api_key(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["captcha"] = {"2captcha_api_key": "secretkey12345"}
        path = write_config_file(tmp_path, config)
        cfg = Config.from_file(path)
        masked = cfg.mask_secrets()
        assert masked["captcha"]["2captcha_api_key"] == "****2345"

    def test_does_not_modify_original(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        cfg.mask_secrets()
        assert cfg.payment.card_number == "4111111111111111"


class TestGetEnabledRetailers:
    """Test Config.get_enabled_retailers() method."""

    def test_returns_only_enabled(self, tmp_path: Path) -> None:
        path = write_config_file(tmp_path, minimal_valid_config())
        cfg = Config.from_file(path)
        assert cfg.get_enabled_retailers() == ["target"]

    def test_returns_empty_when_none_enabled(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["retailers"]["target"]["enabled"] = False
        path = write_config_file(tmp_path, config)
        cfg = Config.from_file(path)
        assert cfg.get_enabled_retailers() == []


class TestEnvVarOverrides:
    """Test environment variable overrides for secrets."""

    def test_card_number_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["card_number"] = ""  # empty in file
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_CC_NUMBER", "5555555555554444")
            cfg = Config.from_file(path)
        assert cfg.payment.card_number == "5555555555554444"

    def test_cvv_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["payment"]["cvv"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_CC_CVV", "789")
            cfg = Config.from_file(path)
        assert cfg.payment.cvv == "789"

    def test_retailer_password_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["retailers"]["target"]["password"] = ""
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_TARGET_PASSWORD", "env_password")
            cfg = Config.from_file(path)
        assert cfg.retailers["target"].password == "env_password"

    def test_2captcha_key_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["captcha"] = {"2captcha_api_key": ""}
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_2CAPTCHA_KEY", "env_api_key")
            cfg = Config.from_file(path)
        assert cfg.captcha.api_key == "env_api_key"

    def test_discord_url_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["notifications"] = {"discord_webhook_url": ""}
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_DISCORD_URL", "https://discord.com/api/webhooks/123")
            cfg = Config.from_file(path)
        assert cfg.notifications.discord_webhook_url == "https://discord.com/api/webhooks/123"

    def test_proxy_list_from_env(self, tmp_path: Path) -> None:
        config = minimal_valid_config()
        config["evasion"] = {"proxy_list": []}
        path = write_config_file(tmp_path, config)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("POKEDROP_PROXY_LIST", "http://user:pass@proxy.com:8080")
            cfg = Config.from_file(path)
        assert "http://user:pass@proxy.com:8080" in cfg.evasion.proxy_list