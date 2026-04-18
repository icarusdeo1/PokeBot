# SPDX-License-Identifier: MIT
"""Tests for the proxy rotation module."""

from __future__ import annotations

import pytest

from bot.evasion.proxy import ProxyConfig, ProxyPool


class TestProxyConfig:
    """Tests for ProxyConfig dataclass."""

    def test_basic_proxy_uri(self) -> None:
        cfg = ProxyConfig(host="192.168.1.1", port=8080)
        assert cfg.uri == "http://192.168.1.1:8080"
        assert cfg.display_host == "192.168.1.1:8080"

    def test_proxy_with_auth(self) -> None:
        cfg = ProxyConfig(
            host="proxy.example.com",
            port=3128,
            username="user123",
            password="pass456",
        )
        assert cfg.uri == "http://user123:pass456@proxy.example.com:3128"
        assert cfg.display_host == "proxy.example.com:3128"

    def test_proxy_without_auth_no_user_pass(self) -> None:
        cfg = ProxyConfig(host="10.0.0.1", port=80)
        assert cfg.username is None
        assert cfg.password is None


class TestProxyPool:
    """Tests for ProxyPool."""

    def test_empty_pool_returns_none(self) -> None:
        pool = ProxyPool([])
        assert pool.get_random_proxy() is None
        assert pool.get_round_robin_proxy() is None
        assert pool.get_proxy_count() == 0
        assert pool.get_healthy_count() == 0

    def test_parse_host_port(self) -> None:
        pool = ProxyPool(["192.168.1.1:8080"])
        assert pool.get_proxy_count() == 1
        proxy = pool.get_random_proxy()
        assert proxy is not None
        assert proxy.host == "192.168.1.1"
        assert proxy.port == 8080

    def test_parse_host_port_user_pass(self) -> None:
        pool = ProxyPool(["proxy.example.com:3128:user:pass"])
        assert pool.get_proxy_count() == 1
        proxy = pool.get_random_proxy()
        assert proxy is not None
        assert proxy.host == "proxy.example.com"
        assert proxy.port == 3128
        assert proxy.username == "user"
        assert proxy.password == "pass"

    def test_parse_malformed_returns_none(self) -> None:
        pool = ProxyPool(["not-a-proxy", "host:invalid_port", ""])
        assert pool.get_proxy_count() == 0

    def test_multiple_proxies(self) -> None:
        pool = ProxyPool([
            "proxy1.example.com:8080",
            "proxy2.example.com:8080",
            "proxy3.example.com:8080",
        ])
        assert pool.get_proxy_count() == 3
        assert pool.get_healthy_count() == 3

    def test_random_proxy_skips_unhealthy(self) -> None:
        pool = ProxyPool(["p1:8080", "p2:8080", "p3:8080"], max_failures=2)
        # Record 2 failures on p1
        proxy1 = pool.get_random_proxy()
        assert proxy1 is not None
        pool.record_failure(proxy1)
        pool.record_failure(proxy1)
        # p1 should now be unhealthy
        assert pool.get_healthy_count() == 2

    def test_record_success_resets_count(self) -> None:
        pool = ProxyPool(["p1:8080"], max_failures=2)
        proxy = pool.get_random_proxy()
        assert proxy is not None
        pool.record_failure(proxy)
        pool.record_failure(proxy)
        assert pool.get_healthy_count() == 0
        pool.record_success(proxy)
        assert pool.get_healthy_count() == 1

    def test_round_robin_order(self) -> None:
        pool = ProxyPool(["p1:8080", "p2:8080", "p3:8080"])
        seen = set()
        for _ in range(6):
            proxy = pool.get_round_robin_proxy()
            assert proxy is not None
            seen.add(proxy.display_host)
        assert len(seen) == 3

    def test_round_robin_skips_unhealthy(self) -> None:
        pool = ProxyPool(["p1:8080", "p2:8080"], max_failures=1)
        # First call returns p1 (index 0 → then advances to 1, returns proxy at 1)
        # Actually trace: start idx=0, advance to 1, return healthy[1] = p2
        # Get p2 first, then fail it, leaving only p1 healthy
        p2 = pool.get_round_robin_proxy()
        assert p2 is not None
        # Record failure on p2
        pool.record_failure(p2)
        # Now only p1 is healthy; call again, should return p1
        p1 = pool.get_round_robin_proxy()
        assert p1 is not None
        assert p1.host == "p1"

    def test_backoff_increases_with_failures(self) -> None:
        pool = ProxyPool(["p1:8080"], backoff_base_ms=1000)
        proxy = pool.get_random_proxy()
        assert proxy is not None
        assert pool.get_backoff_ms(proxy) == 1000
        pool.record_failure(proxy)
        assert pool.get_backoff_ms(proxy) == 2000
        pool.record_failure(proxy)
        assert pool.get_backoff_ms(proxy) == 4000

    def test_reset_proxy(self) -> None:
        pool = ProxyPool(["p1:8080"], max_failures=2)
        proxy = pool.get_random_proxy()
        assert proxy is not None
        pool.record_failure(proxy)
        pool.record_failure(proxy)
        pool.reset_proxy(proxy)
        assert pool.get_healthy_count() == 1

    def test_from_config_empty(self) -> None:
        class FakeEvasion:
            proxy_list = []
        class FakeConfig:
            evasion = FakeEvasion()
        pool = ProxyPool.from_config(FakeConfig())
        assert pool.get_proxy_count() == 0

    def test_from_config_with_proxies(self) -> None:
        class FakeEvasion:
            proxy_list = ["p1:8080", "p2:8080"]
        class FakeConfig:
            evasion = FakeEvasion()
        pool = ProxyPool.from_config(FakeConfig())
        assert pool.get_proxy_count() == 2
        assert pool.get_healthy_count() == 2

    def test_as_httpx_proxy_with_auth(self) -> None:
        pool = ProxyPool(["proxy.com:8080:user:pass"])
        proxy = pool.get_random_proxy()
        assert proxy is not None
        httpx_proxy = pool.as_httpx_proxy(proxy)
        # Auth is stored separately in httpx.Proxy; URL is host:port without embedded creds
        assert httpx_proxy.url == "http://proxy.com:8080"
        assert httpx_proxy.auth == ("user", "pass")

    def test_as_httpx_proxy_no_auth(self) -> None:
        pool = ProxyPool(["proxy.com:8080"])
        proxy = pool.get_random_proxy()
        assert proxy is not None
        httpx_proxy = pool.as_httpx_proxy(proxy)
        assert httpx_proxy.url == "http://proxy.com:8080"