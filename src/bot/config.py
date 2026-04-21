"""Config loading and validation for PokeDrop Bot.

Loads config.yaml, validates all required fields, and supports
environment variable overrides for secrets.

Per PRD Sections 9.8, 11.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

# UTC timezone for drop window comparisons
_UTC = ZoneInfo("UTC")


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
_SCHEDULE_TYPES = ("once", "recurring")


def _validate_cron_field(value: str, min_val: int, max_val: int) -> list[int] | None:
    """Parse a single cron field into a list of integers.

    Supports: * (any), */step (stepped), range (1-5), comma-separated (1,5,10).
    Returns None if the field is invalid.
    """
    if value == "*":
        return list(range(min_val, max_val + 1))
    values: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if "/" in part:
            range_part, step_part = part.split("/", 1)
            step = int(step_part)
            if range_part == "*":
                rng = range(min_val, max_val + 1)
            elif "-" in range_part:
                s_str, e_str = range_part.split("-", 1)
                rng = range(int(s_str), int(e_str) + 1)
            else:
                rng = range(int(range_part), int(range_part) + 1)
            for v in rng:
                if (v - rng.start) % step == 0:
                    values.add(v)
        elif "-" in part:
            s_str, e_str = part.split("-", 1)
            for v in range(int(s_str), int(e_str) + 1):
                values.add(v)
        else:
            try:
                values.add(int(part))
            except ValueError:
                return None
    for v in values:
        if v < min_val or v > max_val:
            return None
    return sorted(values)


def _validate_cron_expr(expr: str) -> tuple[bool, str | None]:
    """Validate a 5-field cron expression (minute hour day month weekday).

    Returns (True, None) if valid, otherwise (False, error_message).
    Weekday: 0=Mon ... 6=Sun.
    """
    if not expr or not str(expr).strip():
        return False, "cron expression cannot be empty"
    parts = str(expr).strip().split()
    if len(parts) != 5:
        return False, f"cron expression must have exactly 5 fields, got {len(parts)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    # Weekday field: cron uses 0=Sun...6=Sat; we store as 0=Sun...6=Sat
    # Python datetime.weekday() uses 0=Mon...6=Sun, so we need to remap
    for part, (mn, mx) in zip(parts, bounds):
        if _validate_cron_field(part, mn, mx) is None:
            return False, f"invalid cron field '{part}' (valid range: {mn}-{mx})"
    return True, None


def _python_weekday_to_cron(python_wday: int) -> int:
    """Convert Python weekday (0=Mon...6=Sun) to cron weekday (0=Sun...6=Sat)."""
    # Python: 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri,5=Sat,6=Sun
    # Cron:    0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat
    return (python_wday + 1) % 7


def _cron_weekday_to_python(cron_wday: int) -> int:
    """Convert cron weekday (0=Sun...6=Sat) to Python weekday (0=Mon...6=Sun)."""
    # Cron:    0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat
    # Python: 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri,5=Sat,6=Sun
    return (cron_wday + 6) % 7


def _get_next_cron_occurrence(expr: str, after: datetime) -> datetime:
    """Return the next datetime matching the cron expression strictly after `after`.

    `after` must be timezone-aware (UTC). brute-forces up to 366 days forward.
    Cron weekday convention: 0=Sun, 1=Mon, ..., 6=Sat.
    """
    import datetime as _dt

    parts = expr.strip().split()
    minute_vals = _validate_cron_field(parts[0], 0, 59) or []
    hour_vals = _validate_cron_field(parts[1], 0, 23) or []
    day_vals = _validate_cron_field(parts[2], 1, 31) or []
    month_vals = _validate_cron_field(parts[3], 1, 12) or []
    wday_vals = _validate_cron_field(parts[4], 0, 6) or []

    current = after.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)

    for _ in range(366 * 24 * 60):
        cron_wday = _python_weekday_to_cron(current.weekday())
        if (
            current.minute in minute_vals
            and current.hour in hour_vals
            and current.day in day_vals
            and current.month in month_vals
            and cron_wday in wday_vals
        ):
            return current
        current += _dt.timedelta(minutes=1)

    # Should always find a match within a year for a valid expression
    return current


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


@dataclass
class _AccountConfig:
    """A single retailer account within the accounts: config section."""
    username: str
    password: str
    enabled: bool = True
    item_filter: list[str] = field(default_factory=list)  # assign to specific items
    round_robin: bool = False  # participate in round-robin item assignment


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
        self.accounts: dict[str, list[_AccountConfig]] = {}  # retailer -> account list

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

    @classmethod
    def _from_raw(cls, raw: dict[str, Any], path: Path | str | None = None) -> Config:
        """Build a Config from a raw dict (already merged, env overrides applied).

        Used by PATCH /api/config to validate a merged config before writing.

        Args:
            raw: Raw config dict (already merged from current + update).
            path: Path to config.yaml (used only for error messages).

        Returns:
            Validated Config instance.

        Raises:
            ConfigError: If validation fails.
        """
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
        # Lazy validation: card_number and cvv are checked at checkout time, not startup.
        # Format validation only (if provided).
        if self.payment.card_number and not _is_valid_card_number(self.payment.card_number):
            errors.append("payment.card_number must be 13-19 digits")
        if self.payment.cvv and not re.match(r"^\d{3,4}$", self.payment.cvv):
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

        # Validate and load drop windows
        raw_drop_windows = self._raw.get("drop_windows", []) or []
        validated_windows: list[dict[str, Any]] = []
        for i, dw in enumerate(raw_drop_windows):
            if not isinstance(dw, dict):
                errors.append(f"drop_windows[{i}]: must be a mapping, got {type(dw).__name__}")
                continue

            item = dw.get("item", "")
            if not item or not str(item).strip():
                errors.append(f"drop_windows[{i}].item is required")

            retailer = dw.get("retailer", "")
            if retailer not in _RETAILERS:
                errors.append(
                    f"drop_windows[{i}].retailer must be one of {sorted(_RETAILERS)}, "
                    f"got '{retailer}'"
                )

            drop_datetime_str = dw.get("drop_datetime", "")
            parsed_dt: datetime | None = None
            if not drop_datetime_str or not str(drop_datetime_str).strip():
                errors.append(f"drop_windows[{i}].drop_datetime is required (ISO-8601 with timezone)")
            else:
                try:
                    # Parse ISO-8601 datetime with timezone
                    parsed_dt = datetime.fromisoformat(str(drop_datetime_str).strip())
                    # Ensure it has timezone info (assume UTC if naive)
                    if parsed_dt.tzinfo is None:
                        parsed_dt = parsed_dt.replace(tzinfo=_UTC)
                except ValueError:
                    errors.append(
                        f"drop_windows[{i}].drop_datetime must be valid ISO-8601 "
                        f"(e.g. 2026-04-20T10:00:00-07:00), got '{drop_datetime_str}'"
                    )

            prewarm_minutes = dw.get("prewarm_minutes", 15)
            try:
                prewarm_minutes = int(prewarm_minutes)
                if prewarm_minutes < 0:
                    errors.append(
                        f"drop_windows[{i}].prewarm_minutes must be >= 0, got {prewarm_minutes}"
                    )
            except (TypeError, ValueError):
                errors.append(
                    f"drop_windows[{i}].prewarm_minutes must be an integer, "
                    f"got {type(prewarm_minutes).__name__}"
                )

            enabled = dw.get("enabled", True)
            if not isinstance(enabled, bool):
                # Accept string "true"/"false"
                if isinstance(enabled, str):
                    enabled = enabled.lower() in ("true", "1", "yes")
                else:
                    errors.append(
                        f"drop_windows[{i}].enabled must be a boolean, "
                        f"got {type(enabled).__name__}"
                    )
                    enabled = True

            max_cart_quantity = dw.get("max_cart_quantity", 1)
            try:
                max_cart_quantity = int(max_cart_quantity)
                if max_cart_quantity < 1:
                    errors.append(
                        f"drop_windows[{i}].max_cart_quantity must be >= 1, got {max_cart_quantity}"
                    )
            except (TypeError, ValueError):
                errors.append(
                    f"drop_windows[{i}].max_cart_quantity must be an integer, "
                    f"got {type(max_cart_quantity).__name__}"
                )
                max_cart_quantity = 1

            # DCT-T04: schedule_type (once/recurring) and cron_expr
            schedule_type = str(dw.get("schedule_type", "once")).strip().lower()
            if schedule_type not in _SCHEDULE_TYPES:
                errors.append(
                    f"drop_windows[{i}].schedule_type must be one of {list(_SCHEDULE_TYPES)}, "
                    f"got '{schedule_type}'"
                )
                schedule_type = "once"

            cron_expr = str(dw.get("cron_expr", "")).strip()
            if schedule_type == "recurring":
                if not cron_expr:
                    errors.append(
                        f"drop_windows[{i}].cron_expr is required when schedule_type is 'recurring'"
                    )
                else:
                    valid, err = _validate_cron_expr(cron_expr)
                    if not valid:
                        errors.append(f"drop_windows[{i}].cron_expr: {err}")

            # Only add to validated list if no errors for this window
            if not any("drop_windows[" + str(i) in e for e in errors):
                dw_entry: dict[str, Any] = {
                    "item": str(item).strip(),
                    "retailer": retailer,
                    "drop_datetime": str(drop_datetime_str).strip(),
                    "prewarm_minutes": prewarm_minutes,
                    "enabled": enabled,
                    "max_cart_quantity": max_cart_quantity,
                    "schedule_type": schedule_type,
                    "_parsed_datetime": parsed_dt,
                }
                if schedule_type == "recurring":
                    dw_entry["cron_expr"] = cron_expr
                validated_windows.append(dw_entry)

        # PHASE3-T03 / DCT-T04: prune past one-shot drops; recurring drops are never pruned
        now_utc = datetime.now(tz=_UTC)
        pruned_count = 0
        self.drop_windows = []
        for dw in validated_windows:
            schedule_type = dw.get("schedule_type", "once")
            if schedule_type == "recurring":
                # Compute next occurrence from now
                cron_expr = dw.get("cron_expr", "")
                next_occurrence = _get_next_cron_occurrence(cron_expr, now_utc)
                dw_copy = {k: v for k, v in dw.items() if k != "_parsed_datetime"}
                dw_copy["_next_occurrence"] = next_occurrence
                dw_copy["_parsed_datetime"] = next_occurrence
                self.drop_windows.append(dw_copy)
            else:
                parsed = dw.get("_parsed_datetime")
                if parsed is not None and parsed < now_utc:
                    pruned_count += 1
                    continue  # skip past one-shot drop windows
                dw_copy = {k: v for k, v in dw.items() if k != "_parsed_datetime"}
                self.drop_windows.append(dw_copy)

        # Validate and load multi-account config (MAC-T01 / MAC-1, MAC-6)
        raw_accounts = self._raw.get("accounts", {}) or {}
        for retailer, account_list in raw_accounts.items():
            if retailer not in _RETAILERS:
                errors.append(
                    f"accounts.{retailer}: retailer must be one of {sorted(_RETAILERS)}, "
                    f"got '{retailer}'"
                )
                continue
            if not isinstance(account_list, list):
                errors.append(
                    f"accounts.{retailer}: must be a list of account blocks, "
                    f"got {type(account_list).__name__}"
                )
                continue
            for j, acct in enumerate(account_list):
                if not isinstance(acct, dict):
                    errors.append(
                        f"accounts.{retailer}[{j}]: must be a mapping, "
                        f"got {type(acct).__name__}"
                    )
                    continue
                username = acct.get("username", "")
                password = acct.get("password", "")
                if not username:
                    errors.append(f"accounts.{retailer}[{j}].username is required")
                if not password:
                    errors.append(f"accounts.{retailer}[{j}].password is required")
                enabled = acct.get("enabled", True)
                if not isinstance(enabled, bool):
                    if isinstance(enabled, str):
                        enabled = enabled.lower() in ("true", "1", "yes")
                    else:
                        errors.append(
                            f"accounts.{retailer}[{j}].enabled must be a boolean"
                        )
                        enabled = True
                item_filter = acct.get("item_filter", [])
                if not isinstance(item_filter, list):
                    errors.append(
                        f"accounts.{retailer}[{j}].item_filter must be a list of item names"
                    )
                    item_filter = []
                round_robin = acct.get("round_robin", False)
                if not isinstance(round_robin, bool):
                    if isinstance(round_robin, str):
                        round_robin = round_robin.lower() in ("true", "1", "yes")
                    else:
                        errors.append(
                            f"accounts.{retailer}[{j}].round_robin must be a boolean"
                        )
                        round_robin = False
                # Build the typed account config
                if retailer not in self.accounts:
                    self.accounts[retailer] = []
                self.accounts[retailer].append(
                    _AccountConfig(
                        username=str(username).strip(),
                        password=str(password).strip(),
                        enabled=enabled,
                        item_filter=[str(x).strip() for x in item_filter],
                        round_robin=round_robin,
                    )
                )

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

        # Mask accounts passwords (MAC-T01 / MAC-6)
        if "accounts" in masked:
            for retailer, account_list in masked["accounts"].items():
                if isinstance(account_list, list):
                    for acct in account_list:
                        if isinstance(acct, dict) and "password" in acct:
                            acct["password"] = "***"

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