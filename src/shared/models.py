"""Shared dataclasses/models for the PokeDrop bot.

All core domain models are defined here to avoid circular imports.
Per PRD Section 8.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────────────


class CaptchaMode(Enum):
    """CAPTCHA solving mode per PRD Section 9.4.1."""

    AUTO = "auto"
    MANUAL = "manual"
    SMART = "smart"


class CaptchaType(Enum):
    """Known CAPTCHA challenge types."""

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"
    UNKNOWN = "unknown"


class CheckoutStage(Enum):
    """Checkout flow stages for error reporting."""

    PRE_CHECK = "pre_check"
    SHIPPING = "shipping"
    PAYMENT = "payment"
    REVIEW = "review"
    SUBMIT = "submit"
    CONFIRMATION = "confirmation"


class RetailerName(Enum):
    """Supported retailer adapters."""

    TARGET = "target"
    WALMART = "walmart"
    BESTBUY = "bestbuy"


# ── Core Domain Models ────────────────────────────────────────────────────────


@dataclass
class MonitoredItem:
    """A product the bot is configured to monitor and auto-purchase."""

    id: str = ""
    name: str = ""
    retailers: list[str] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    enabled: bool = True
    max_cart_quantity: int = 1


@dataclass
class RetailerAdapterConfig:
    """Configuration for a retailer adapter."""

    name: str = ""
    base_url: str = ""
    enabled: bool = True
    check_interval_ms: int = 500
    prewarm_minutes: int = 15
    requires_login: bool = True
    has_queue: bool = False


@dataclass
class CheckoutConfig:
    """Checkout flow configuration."""

    shipping: ShippingInfo
    payment: PaymentInfo
    use_1click_if_available: bool = True
    human_delay_ms: int = 300


@dataclass
class ShippingInfo:
    """Shipping address details."""

    name: str = ""
    address1: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    address2: str = ""
    email: str = ""


@dataclass
class PaymentInfo:
    """Payment card details.

    card_number and cvv are stored as-is in config;
    production deployments should use encrypted storage.
    card_type is auto-detected (visa/mastercard/amex).
    """

    card_number: str = ""
    expiry_month: str = ""
    expiry_year: str = ""
    cvv: str = ""
    card_type: str = ""


@dataclass
class WebhookEvent:
    """A bot lifecycle event for logging and webhook dispatch."""

    event: str
    item: str = ""
    retailer: str = ""
    timestamp: str = ""
    order_id: str = ""
    error: str = ""
    attempt: int = 1
    url: str = ""
    sku: str = ""
    cart_url: str = ""
    captcha_type: str = ""
    solve_time_ms: int = 0
    pause_url: str = ""
    timeout_seconds: int = 0
    daily_spent_usd: float = 0.0
    budget_cap_usd: float = 0.0
    queue_url: str = ""
    decline_code: str = ""
    total: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict, omitting empty fields."""
        result: dict[str, Any] = {"event": self.event}
        for k, v in [
            ("item", self.item),
            ("retailer", self.retailer),
            ("timestamp", self.timestamp),
            ("order_id", self.order_id),
            ("error", self.error),
            ("attempt", self.attempt),
            ("url", self.url),
            ("sku", self.sku),
            ("cart_url", self.cart_url),
            ("captcha_type", self.captcha_type),
            ("solve_time_ms", self.solve_time_ms),
            ("pause_url", self.pause_url),
            ("timeout_seconds", self.timeout_seconds),
            ("daily_spent_usd", self.daily_spent_usd),
            ("budget_cap_usd", self.budget_cap_usd),
            ("queue_url", self.queue_url),
            ("decline_code", self.decline_code),
            ("total", self.total),
            ("reason", self.reason),
        ]:
            if v:
                result[k] = v
        return result


@dataclass
class SessionState:
    """Browser session state persisted to state.db per retailer."""

    cookies: dict[str, str] = field(default_factory=dict)
    auth_token: str = ""
    cart_token: str = ""
    prewarmed_at: str = ""
    expires_at: str = ""  # ISO-8601 UTC — session is valid until this time
    is_valid: bool = True


@dataclass
class DropWindow:
    """A scheduled drop event with auto-prewarm support."""

    id: int = 0
    item: str = ""
    retailer: str = ""
    drop_datetime: str = ""  # ISO-8601 UTC
    prewarm_minutes: int = 15
    enabled: bool = True
    max_cart_quantity: int = 1


@dataclass
class CaptchaSolveResult:
    """Result of a CAPTCHA solve attempt."""

    success: bool
    token: str = ""
    solve_time_ms: int = 0
    error: str = ""


@dataclass
class StockStatus:
    """Result of a stock check."""

    in_stock: bool
    sku: str
    url: str = ""
    price: str = ""
    available_quantity: int = 0


# ── Abstract Base ─────────────────────────────────────────────────────────────


class RetailerAdapter(ABC):
    """Abstract base class for all retailer adapters.

    Subclasses must implement all abstract methods.
    Per PRD Section 9.1.
    """

    name: str
    base_url: str

    @abstractmethod
    async def login(self, username: str, password: str) -> bool:
        """Authenticate with the retailer. Returns True on success."""
        ...

    @abstractmethod
    async def check_stock(self, sku: str) -> StockStatus:
        """Check if a SKU is in stock at this retailer."""
        ...

    @abstractmethod
    async def add_to_cart(self, sku: str, quantity: int = 1) -> bool:
        """Add a SKU to the cart. Returns True on success."""
        ...

    @abstractmethod
    async def get_cart(self) -> list[dict[str, Any]]:
        """Return current cart contents as list of item dicts."""
        ...

    @abstractmethod
    async def checkout(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
    ) -> dict[str, Any]:
        """Complete checkout. Returns dict with order confirmation or error."""
        ...

    @abstractmethod
    async def handle_captcha(self, page: Any) -> CaptchaSolveResult:
        """Detect and handle any CAPTCHA challenge on the given page."""
        ...

    @abstractmethod
    async def check_queue(self) -> bool:
        """Return True if currently in a queue/waiting room."""
        ...