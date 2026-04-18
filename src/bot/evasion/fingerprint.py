# SPDX-License-Identifier: MIT
"""
Playwright fingerprint randomization for evasion.

Randomizes browser fingerprint signals to avoid detection: viewport,
timezone, locale, hardware concurrency, device memory, and automation
signals. Implements EV-2 from PRD Section 9.5.
"""

from __future__ import annotations

import random
from typing import Any

from dataclasses import dataclass


# Realistic viewport dimensions used by actual browsers
_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
    {"width": 1680, "height": 1050},
    {"width": 1920, "height": 1200},
    {"width": 2048, "height": 1152},
    {"width": 2560, "height": 1440},
    {"width": 3840, "height": 2160},
    {"width": 360, "height": 800},   # mobile-like
    {"width": 375, "height": 812},   # iPhone X
    {"width": 390, "height": 844},   # iPhone 12/13
    {"width": 414, "height": 896},   # iPhone 11
    {"width": 412, "height": 915},   # Android
    {"width": 430, "height": 932},   # larger Android
    {"width": 820, "height": 1180},  # iPad
    {"width": 1024, "height": 1366}, # iPad Pro
    {"width": 1180, "height": 820},  # iPad landscape
]

# Real locales matching actual browser installations
_LOCALES: list[str] = [
    "en-US", "en-GB", "en-CA", "en-AU", "en-NZ",
    "en-IE", "en-ZA", "en-IN",
    "de-DE", "de-AT", "de-CH",
    "fr-FR", "fr-CA", "fr-BE", "fr-CH",
    "es-ES", "es-MX", "es-AR", "es-CL",
    "pt-BR", "pt-PT",
    "it-IT",
    "nl-NL", "nl-BE",
    "pl-PL",
    "ja-JP",
    "ko-KR",
    "zh-CN", "zh-TW", "zh-HK",
    "ru-RU",
    "sv-SE",
    "nb-NO",
    "da-DK",
    "fi-FI",
    "tr-TR",
    "ar-SA",
    "th-TH",
    "vi-VN",
    "id-ID",
    "ms-MY",
    "he-IL",
]

# Real IANA timezone IDs
_TIMEZONES: list[str] = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Toronto",
    "America/Vancouver",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Vienna",
    "Europe/Stockholm",
    "Europe/Oslo",
    "Europe/Copenhagen",
    "Europe/Helsinki",
    "Europe/Warsaw",
    "Europe/Prague",
    "Europe/Bucharest",
    "Europe/Athens",
    "Europe/Istanbul",
    "Europe/Moscow",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Hong_Kong",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Manila",
    "Asia/Jakarta",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Australia/Perth",
    "Australia/Brisbane",
    "Pacific/Auckland",
    "Pacific/Tahiti",
]

# Realistic hardware concurrency values (CPU logical cores)
_HARDWARE_CONCURRENCIES: list[int] = [2, 4, 6, 8, 10, 12, 16, 20, 24, 32]

# Realistic device memory values in GB
_DEVICE_MEMORIES: list[float] = [0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 16.0, 32.0]

# Realistic device scale factors
_DEVICE_SCALE_FACTORS: list[float] = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


@dataclass
class BrowserFingerprint:
    """Collected fingerprint parameters for a browser context."""

    viewport: dict[str, int]
    locale: str
    timezone_id: str
    user_agent: str
    hardware_concurrency: int
    device_memory: float
    device_scale_factor: float


def get_random_fingerprint(user_agent: str) -> BrowserFingerprint:
    """Generate a randomized browser fingerprint.

    Args:
        user_agent: The User-Agent string to use for this session.
                    Should come from user_agents.get_random_user_agent().

    Returns:
        A BrowserFingerprint with all randomized values.
    """
    return BrowserFingerprint(
        viewport=random.choice(_VIEWPORTS),
        locale=random.choice(_LOCALES),
        timezone_id=random.choice(_TIMEZONES),
        user_agent=user_agent,
        hardware_concurrency=random.choice(_HARDWARE_CONCURRENCIES),
        device_memory=random.choice(_DEVICE_MEMORIES),
        device_scale_factor=random.choice(_DEVICE_SCALE_FACTORS),
    )


def get_automation_mask_script(fingerprint: BrowserFingerprint) -> str:
    """Return a JavaScript init script that masks automation signals.

    This script patches navigator properties to match the fingerprint
    and hides common Playwright/automation detection vectors.

    Args:
        fingerprint: The BrowserFingerprint with spoofed values.

    Returns:
        A JavaScript string to be injected via add_init_script.
    """
    return f"""
    // Spoof navigator.hardwareConcurrency to match fingerprint
    Object.defineProperty(navigator, 'hardwareConcurrency', {{
        get: () => {fingerprint.hardware_concurrency},
        configurable: true,
    }});

    // Spoof navigator.deviceMemory to match fingerprint
    Object.defineProperty(navigator, 'deviceMemory', {{
        get: () => {fingerprint.device_memory},
        configurable: true,
    }});

    // Spoof webdriver flag — the primary Playwright/Selenium detection vector
    Object.defineProperty(navigator, 'webdriver', {{
        get: () => false,
        configurable: true,
    }});

    // Remove chrome.runtime object which is present in real Chrome extensions
    // but absent or modified in automation contexts
    if (window.chrome && window.chrome.runtime) {{
        try {{
            Object.defineProperty(window.chrome, 'runtime', {{
                get: () => undefined,
                configurable: true,
            }});
        }} catch (e) {{
            // ignore if chrome is not accessible
        }}
    }}

    // Patch Permissions API to return 'denied' for automation-related queries
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' || parameters.name === 'geolocation'
            ? Promise.resolve({{ state: Notification.permission === 'granted' ? 'granted' : 'denied' }})
            : originalQuery(parameters)
    );

    // Spoof connection info (if available)
    if (navigator.connection) {{
        Object.defineProperty(navigator.connection, 'effectiveType', {{
            get: () => '4g',
            configurable: true,
        }});
        Object.defineProperty(navigator.connection, 'downlink', {{
            get: () => 10,
            configurable: true,
        }});
    }}

    // Canvas noise — randomize canvas fingerprint slightly
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attributes) {{
        const ctx = origGetContext.call(this, type, attributes);
        if (type === '2d') {{
            const origFillText = ctx.fillText;
            ctx.fillText = function(...args) {{
                // Seed with a small random offset to defeat exact canvas fingerprinting
                const seed = Math.random() * 0.001;
                args[0] = args[0] + String.fromCharCode(8203).repeat(Math.floor(seed * 100));
                return origFillText.apply(this, args);
            }};
        }}
        return ctx;
    }};
    """


def get_viewport() -> dict[str, int]:
    """Return a random realistic viewport size."""
    return random.choice(_VIEWPORTS)


def get_locale() -> str:
    """Return a random realistic locale."""
    return random.choice(_LOCALES)


def get_timezone_id() -> str:
    """Return a random IANA timezone ID."""
    return random.choice(_TIMEZONES)


def get_hardware_concurrency() -> int:
    """Return a random realistic hardware concurrency value."""
    return random.choice(_HARDWARE_CONCURRENCIES)


def get_device_memory() -> float:
    """Return a random realistic device memory value in GB."""
    return random.choice(_DEVICE_MEMORIES)


def get_device_scale_factor() -> float:
    """Return a random realistic device scale factor."""
    return random.choice(_DEVICE_SCALE_FACTORS)
