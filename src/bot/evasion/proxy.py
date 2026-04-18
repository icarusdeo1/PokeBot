# SPDX-License-Identifier: MIT
"""
Proxy rotation module for residential proxy pool management.

Rotates through residential proxy pool loaded from config.
Supports proxy auth (user:pass format). Detects and retries on proxy failure.
Implements EV-4 from PRD Section 9.5.

The proxy list is configured in config.yaml under evasion.proxy_list,
or via POKEDROP_PROXY_LIST environment variable (comma-separated).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Optional

import httpx

from bot.config import Config


@dataclass
class ProxyConfig:
    """Parsed proxy configuration with auth details."""

    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def uri(self) -> str:
        """Return the proxy URI for httpx."""
        if self.username and self.password:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def display_host(self) -> str:
        """Return host:port without auth for logging."""
        return f"{self.host}:{self.port}"


class ProxyPool:
    """Rotating proxy pool with auth support and failure detection.

    Rotates proxies per-request or per-session. Retries on proxy failure.
    Thread-safe for use in async contexts.
    """

    def __init__(
        self,
        proxy_list: list[str],
        max_failures: int = 3,
        backoff_base_ms: int = 1000,
    ) -> None:
        """Initialize the proxy pool.

        Args:
            proxy_list: List of proxy strings. Formats:
                - host:port
                - host:port:user:pass
            max_failures: Max consecutive failures before proxy is skipped.
            backoff_base_ms: Base backoff time in ms for proxy retry.
        """
        self._proxies: list[ProxyConfig] = []
        self._failure_counts: dict[int, int] = {}
        self._max_failures = max_failures
        self._backoff_base_ms = backoff_base_ms
        self._lock = asyncio.Lock()
        self._index = 0

        for raw in proxy_list:
            cfg = self._parse_proxy(raw)
            if cfg:
                self._proxies.append(cfg)
                self._failure_counts[id(cfg)] = 0

    @staticmethod
    def from_config(config: Config) -> ProxyPool:
        """Build a ProxyPool from a Config object.

        Args:
            config: Validated Config instance with evasion.proxy_list.

        Returns:
            ProxyPool instance (empty if no proxies configured).
        """
        return ProxyPool(
            proxy_list=config.evasion.proxy_list,
            max_failures=3,
            backoff_base_ms=1000,
        )

    @staticmethod
    def _parse_proxy(raw: str) -> Optional[ProxyConfig]:
        """Parse a raw proxy string into ProxyConfig.

        Formats:
            host:port
            host:port:username:password

        Args:
            raw: Raw proxy string from config.

        Returns:
            ProxyConfig, or None if parsing fails.
        """
        parts = raw.strip().split(":")
        if len(parts) == 2:
            try:
                return ProxyConfig(host=parts[0], port=int(parts[1]))
            except ValueError:
                return None
        elif len(parts) == 4:
            try:
                return ProxyConfig(
                    host=parts[0],
                    port=int(parts[1]),
                    username=parts[2],
                    password=parts[3],
                )
            except ValueError:
                return None
        return None

    def get_random_proxy(self) -> Optional[ProxyConfig]:
        """Return a randomly selected proxy from the pool.

        Respects failure counts — proxies with >= max_failures are excluded
        from random selection until they are reset.

        Returns:
            ProxyConfig, or None if no healthy proxies remain.
        """
        if not self._proxies:
            return None

        healthy = [
            (i, p) for i, p in enumerate(self._proxies)
            if self._failure_counts.get(id(p), 0) < self._max_failures
        ]
        if not healthy:
            return None

        return random.choice(healthy)[1]

    def get_round_robin_proxy(self) -> Optional[ProxyConfig]:
        """Return the next proxy in round-robin order.

        Skips proxies that have exceeded failure thresholds.

        Returns:
            ProxyConfig, or None if no healthy proxies remain.
        """
        if not self._proxies:
            return None

        healthy = [
            p for p in self._proxies
            if self._failure_counts.get(id(p), 0) < self._max_failures
        ]
        if not healthy:
            return None

        # Advance position within the healthy pool
        self._index = (self._index + 1) % len(healthy)
        return healthy[self._index]

    def record_failure(self, proxy: ProxyConfig) -> None:
        """Record a proxy failure and increment failure count.

        Args:
            proxy: The proxy that failed.
        """
        fid = id(proxy)
        self._failure_counts[fid] = self._failure_counts.get(fid, 0) + 1

    def record_success(self, proxy: ProxyConfig) -> None:
        """Reset failure count on successful use.

        Args:
            proxy: The proxy that succeeded.
        """
        fid = id(proxy)
        self._failure_counts[fid] = 0

    def reset_proxy(self, proxy: ProxyConfig) -> None:
        """Manually reset failure count for a proxy.

        Args:
            proxy: The proxy to reset.
        """
        self._failure_counts[id(proxy)] = 0

    def get_backoff_ms(self, proxy: ProxyConfig) -> int:
        """Return exponential backoff delay in ms for a proxy.

        Uses the proxy's failure count to compute exponential backoff.

        Args:
            proxy: The proxy to compute backoff for.

        Returns:
            Backoff time in milliseconds.
        """
        failures = self._failure_counts.get(id(proxy), 0)
        backoff: int = self._backoff_base_ms * (2 ** failures)
        return backoff

    def get_proxy_count(self) -> int:
        """Return total number of proxies in the pool."""
        return len(self._proxies)

    def get_healthy_count(self) -> int:
        """Return number of proxies with failures below threshold."""
        return sum(
            1 for p in self._proxies
            if self._failure_counts.get(id(p), 0) < self._max_failures
        )

    def rotate_session_proxy(self) -> Optional[ProxyConfig]:
        """Return a proxy for a new session (uses random selection).

        For use when starting a new browser session.

        Returns:
            ProxyConfig, or None if no healthy proxies.
        """
        return self.get_random_proxy()

    async def proxy_health_check(
        self,
        proxy: ProxyConfig,
        test_url: str = "https://httpbin.org/ip",
        timeout_ms: int = 5000,
    ) -> bool:
        """Check if a proxy is functional by making a test request.

        Args:
            proxy: Proxy to test.
            test_url: URL to test connectivity through proxy.
            timeout_ms: Request timeout in milliseconds.

        Returns:
            True if proxy responds successfully, False otherwise.
        """
        try:
            httpx_proxy = self.as_httpx_proxy(proxy)
            async with httpx.AsyncClient(proxy=httpx_proxy, timeout=timeout_ms / 1000.0) as client:
                resp = await client.get(test_url)
                return resp.status_code == 200
        except Exception:
            return False

    async def check_and_retry_proxy(
        self,
        proxy: ProxyConfig,
        max_retries: int = 2,
    ) -> Optional[ProxyConfig]:
        """Test a proxy and retry with backoff if it fails.

        Args:
            proxy: The proxy to test.
            max_retries: Number of retry attempts.

        Returns:
            The same proxy if eventually healthy, or None if all retries failed.
        """
        for attempt in range(max_retries + 1):
            if await self.proxy_health_check(proxy):
                self.record_success(proxy)
                return proxy

            if attempt < max_retries:
                backoff_ms = self.get_backoff_ms(proxy)
                await asyncio.sleep(backoff_ms / 1000.0)
                self.record_failure(proxy)

        return None

    def as_httpx_proxy(self, proxy: ProxyConfig) -> httpx.Proxy:
        """Convert a ProxyConfig to an httpx.Proxy object.

        Args:
            proxy: The proxy configuration.

        Returns:
            httpx.Proxy configured with the proxy URI and auth.
        """
        if proxy.username and proxy.password:
            return httpx.Proxy(url=f"http://{proxy.host}:{proxy.port}", auth=(proxy.username, proxy.password))
        return httpx.Proxy(url=f"http://{proxy.host}:{proxy.port}")