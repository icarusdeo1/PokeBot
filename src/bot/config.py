"""Config loading and validation for PokeDrop Bot.

Loads config.yaml, validates all required fields, and supports
environment variable overrides for secrets.

Per PRD Sections 9.8, 11.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Environment variable mappings: env var -> (config key path, default value)
_ENV_OVERRIDES: list[tuple[str, list[str], str]] = [
    ("POKEDROP_2CAPTCHA_KEY", ["captcha", "2captcha_api_key"], ""),
    ("POKEDROP_DISCORD_URL", ["notifications", "discord_webhook_url"], ""),
    ("POKEDROP_TELEGRAM_TOKEN", ["notifications", "telegram_bot_token"], ""),
    ("POKEDROP_TELEGRAM_CHAT_ID", ["notifications", "telegram_chat_id"], ""),
    ("POKEDROP_TARGET_USERNAME", ["retailers", "target", "username"], ""),
    ("POKEDROP_TARGET_PASSWORD", ["retailers", "target", "password"], ""),
    ("POKEDROP_WALMART_USERNAME", ["retailers", "walmart", "username"], ""),
    ("POKEDROP_WALMART_PASSWORD", ["retailers", "walmart", "password"], ""),
    ("POKEDROP_BESTBUY_USERNAME", ["retailers", "bestbuy", "username"], ""),
    ("POKEDROP_BESTBUY_PASSWORD", ["retailers", "bestbuy", "password"], ""),
    ("POKEDROP_CC_NUMBER", ["payment", "card_number"], ""),
    ("POKEDROP_CC_CVV", ["payment", "cvv"], ""),
    ("POKEDROP_PROXY_LIST", ["evasion", "proxy_list"], ""),
]

_RETAILERS = {"target", "walmart", "bestbuy"}
_REQUIRED_TOP_LEVEL = {"retailers", "shipping", "payment"}
_REQUIRED_SHIPPING = {"full_name", "address_line1", "city", "state", "zip_code", "phone"}
_REQUIRED_PAYMENT = {"expiry_month", "expiry_year"}


class ConfigError(Exception):
    """Raised when config validation fails with field-level error messages."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Config validation failed: {'; '.join(errors)}")


@dataclass
class _RetailerConfig:
    enabled: bool = False
    username: str = ""
    password: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _ShippingConfig:
    full_name: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class _PaymentConfig:
    card_number: str = ""
    expiry_month: str = ""
    expiry_year: str = ""
    cvv: str = ""
    billing_address_same_as_shipping: bool = True
    billing_address_line1: str = ""
    billing_address_line2: str = ""
    billing_city: str = ""
    billing_state: str = ""
    billing_zip_code: str = ""


@dataclass
class _NotificationsConfig:
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@dataclass
class _CaptchaConfig:
    mode: str = "smart"
    api_key: str = ""
    daily_budget_usd: float = 5.0
    per_retailer_budget_override: dict[str, float] = field(default_factory=dict)


@dataclass
class _EvasionConfig:
    jitter_percent: int = 20
    proxy_list: list[str] = field(default_factory=list)


@dataclass
class _CheckoutConfig:
    retry_attempts: int = 2
    human_delay_ms: int = 300
    max_human_delay_ms: int = 350


@dataclass
class _MonitoringConfig:
    stock_check_interval_seconds: int = 5
    prewarm_minutes_before_drop: int = 15


class Config:
    """Loaded and validated PokeDrop Bot configuration.

    Access is granted to all code that needs it.
    Sensitive fields are masked in logs and API responses via mask_secrets().
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self.retailers: dict[str, _RetailerConfig] = {}
        self.shipping = _ShippingConfig()
        self.payment = _PaymentConfig()
        self.notifications = _NotificationsConfig()
        self.captcha = _CaptchaConfig()
        self.evasion = _EvasionConfig()
        self.checkout = _CheckoutConfig()
        self.monitoring = _MonitoringConfig()
        self.drop_windows: list[dict[str, Any]] = []
        self.accounts: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def from_file(cls, path: Path | str) -> Config:
        """Load and validate a config.yaml file.

        Args:
            path: Path to config.yaml

        Returns:
            Validated Config instance

        Raises:
            ConfigError: If validation fails
            FileNotFoundError: If config file doesn't exist
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p) as f:
            raw = yaml.safe_load(f) or {}
        raw = _apply_env_overrides(raw)
        cfg = cls(raw)
        cfg._validate()
        return cfg

    def _validate(self) -> None:
        """Validate all config fields. Raises ConfigError on failure."""
        errors: list[str] = []

        for key in _REQUIRED_TOP_LEVEL:
            if key not in self._raw:
                errors.append(f"Missing required top-level key: '{key}'")

        raw_retailers = self._raw.get("retailers", {})
        # Verify at least one retailer is configured with items
        has_items = any(raw_retailers.get(name, {}).get("items") for name in _RETAILERS)
        if not has_items:
            errors.append("At least one retailer must have at least one monitored item")
        for name in _RETAILERS:
            self.retailers[name] = _RetailerConfig(
                enabled=raw_retailers.get(name, {}).get("enabled", False),
                username=raw_retailers.get(name, {}).get("username", ""),
                password=raw_retailers.get(name, {}).get("password", ""),
                items=raw_retailers.get(name, {}).get("items", []),
            )

        raw_shipping = self._raw.get("shipping", {})
        for field_name in _REQUIRED_SHIPPING:
            value = raw_shipping.get(field_name, "").strip()
            if not value:
                errors.append(f"shipping.{field_name} is required")
        self.shipping = _ShippingConfig(
            full_name=raw_shipping.get("full_name", "").strip(),
            address_line1=raw_shipping.get("address_line1", "").strip(),
            address_line2=raw_shipping.get("address_line2", "").strip(),
            city=raw_shipping.get("city", "").strip(),
            state=raw_shipping.get("state", "").strip(),
            zip_code=raw_shipping.get("zip_code", "").strip(),
            phone=raw_shipping.get("phone", "").strip(),
            email=raw_shipping.get("email", "").strip(),
        )

        raw_payment = self._raw.get("payment", {})
        for field_name in _REQUIRED_PAYMENT:
            value = raw_payment.get(field_name, "").strip()
            if not value:
                errors.append(f"payment.{field_name} is required")
        self.payment = _PaymentConfig(
            card_number=raw_payment.get("card_number", "").strip(),
            expiry_month=raw_payment.get("expiry_month", "").strip(),
            expiry_year=raw_payment.get("expiry_year", "").strip(),
            cvv=raw_payment.get("cvv", "").strip(),
            billing_address_same_as_shipping=raw_payment.get(
                "billing_address_same_as_shipping", True
            ),
            billing_address_line1=raw_payment.get("billing_address_line1", "").strip(),
            billing_address_line2=raw_payment.get("billing_address_line2", "").strip(),
            billing_city=raw_payment.get("billing_city", "").strip(),
            billing_state=raw_payment.get("billing_state", "").strip(),
            billing_zip_code=raw_payment.get("billing_zip_code", "").strip(),
        )
        if not self.payment.card_number:
            errors.append("payment.card_number is required (or set POKEDROP_CC_NUMBER)")
        elif not _is_valid_card_number(self.payment.card_number):
            errors.append("payment.card_number must be 13-19 digits")
        if not self.payment.cvv:
            errors.append("payment.cvv is required (or set POKEDROP_CC_CVV)")
        elif not re.match(r"^\d{3,4}$", self.payment.cvv):
            errors.append("payment.cvv must be 3 or 4 digits")

        raw_captcha = self._raw.get("captcha", {})
        captcha_mode = raw_captcha.get("mode", "smart").strip().lower()
        if captcha_mode not in {"auto", "manual", "smart"}:
            errors.append("captcha.mode must be 'auto', 'manual', or 'smart'")
        self.captcha = _CaptchaConfig(
            mode=captcha_mode,
            api_key=raw_captcha.get("2captcha_api_key", "").strip(),
            daily_budget_usd=float(raw_captcha.get("daily_budget_usd", 5.0)),
            per_retailer_budget_override=raw_captcha.get(
                "per_retailer_budget_override", {}
            ),
        )

        raw_notif = self._raw.get("notifications", {})
        self.notifications = _NotificationsConfig(
            discord_webhook_url=raw_notif.get("discord_webhook_url", "").strip(),
            telegram_bot_token=raw_notif.get("telegram_bot_token", "").strip(),
            telegram_chat_id=raw_notif.get("telegram_chat_id", "").strip(),
        )

        raw_evasion = self._raw.get("evasion", {})
        self.evasion = _EvasionConfig(
            jitter_percent=int(raw_evasion.get("jitter_percent", 20)),
            proxy_list=raw_evasion.get("proxy_list", []),
        )

        raw_checkout = self._raw.get("checkout", {})
        self.checkout = _CheckoutConfig(
            retry_attempts=int(raw_checkout.get("retry_attempts", 2)),
            human_delay_ms=int(raw_checkout.get("human_delay_ms", 300)),
            max_human_delay_ms=int(raw_checkout.get("max_human_delay_ms", 350)),
        )

        raw_monitoring = self._raw.get("monitoring", {})
        self.monitoring = _MonitoringConfig(
            stock_check_interval_seconds=int(
                raw_monitoring.get("stock_check_interval_seconds", 5)
            ),
            prewarm_minutes_before_drop=int(
                raw_monitoring.get("prewarm_minutes_before_drop", 15)
            ),
        )

        self.drop_windows = self._raw.get("drop_windows", []) or []
        self.accounts = self._raw.get("accounts", {}) or {}

        if errors:
            raise ConfigError(errors)

    def mask_secrets(self) -> dict[str, Any]:
        """Return a copy of the raw config with sensitive fields masked.

        Masks card_number, cvv, passwords, and API keys as '****1234'.
        """
        masked = _deep_copy_dict(self._raw)

        def _mask_str(val: str) -> str:
            if len(val) <= 4:
                return "****"
            return "****" + val[-4:]

        if "payment" in masked:
            if masked["payment"].get("card_number"):
                masked["payment"]["card_number"] = _mask_str(
                    masked["payment"]["card_number"]
                )
            masked["payment"]["cvv"] = "***"

        for retailer in ["target", "walmart", "bestbuy"]:
            if retailer in masked.get("retailers", {}):
                if "password" in masked["retailers"][retailer]:
                    masked["retailers"][retailer]["password"] = "***"

        if "captcha" in masked and masked["captcha"].get("2captcha_api_key"):
            masked["captcha"]["2captcha_api_key"] = _mask_str(
                masked["captcha"]["2captcha_api_key"]
            )

        return masked

    def get_enabled_retailers(self) -> list[str]:
        """Return list of retailer names that are enabled."""
        return [name for name, cfg in self.retailers.items() if cfg.enabled]


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to the raw config dict.

    Env vars take precedence over config file values.
    """
    result = _deep_copy_dict(raw)
    for env_var, path, default in _ENV_OVERRIDES:
        value = os.environ.get(env_var, "")
        if value:
            _set_nested(result, path, value)
        else:
            current = _get_nested(result, path, None)
            if current is None:
                _set_nested(result, path, default)
    return result


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively deep-copy a dict (handles nested dicts + lists)."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            result[k] = [
                (_deep_copy_dict(x) if isinstance(x, dict) else x) for x in v
            ]
        else:
            result[k] = v
    return result


def _get_nested(d: dict[str, Any], path: list[str], default: Any) -> Any:
    """Get a nested dict value by path, returning default if not found."""
    current: Any = d
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current


def _set_nested(d: dict[str, Any], path: list[str], value: Any) -> None:
    """Set a nested dict value by path, creating intermediate dicts as needed."""
    for key in path[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]
    d[path[-1]] = value


def _is_valid_card_number(number: str) -> bool:
    """Check if a card number is 13-19 digits (basic format check)."""
    cleaned = re.sub(r"\D", "", number)
    return bool(re.match(r"^\d{13,19}$", cleaned))