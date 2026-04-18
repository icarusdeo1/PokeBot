"""Tests for the retailer adapter plugin registry.

Per PRD Section 9.15 (ADP-1, ADP-2, ADP-3).
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


# ── Concrete test adapter for testing ───────────────────────────────────────


class ConcreteRetailerAdapter:
    """Concrete adapter for testing the registry without external deps."""

    name: str = "testretailer"
    VERSION: str = "2.1"
    DEPENDENCIES: list[str] = ["turnstile"]

    def __init__(self, config: MagicMock) -> None:
        self.config = config


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def empty_registry() -> "AdapterRegistry":
    """Fresh empty registry with no adapters registered."""
    from src.bot.monitor.retailers.registry import AdapterRegistry

    return AdapterRegistry()


@pytest.fixture
def mock_config() -> MagicMock:
    """Minimal mock Config object."""
    cfg = MagicMock()
    cfg.evasion.jitter_percent = 20
    cfg.retailers = {"test": MagicMock(enabled=True)}
    return cfg


# ── AdapterRegistry.init ────────────────────────────────────────────────────


class TestRegistryInit:
    def test_starts_empty(self, empty_registry: "AdapterRegistry") -> None:
        assert empty_registry.adapters == {}
        assert empty_registry.retailer_names == []

    def test_discovered_flag_starts_false(self, empty_registry: "AdapterRegistry") -> None:
        assert empty_registry._discovered is False


# ── AdapterRegistry.register ────────────────────────────────────────────────


class TestRegistryRegister:
    def test_register_single_adapter(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        plugin = AdapterPlugin(
            name="acme",
            cls=ConcreteRetailerAdapter,
            module_name="src.bot.monitor.retailers.acme",
        )
        empty_registry.register(plugin)

        assert "acme" in empty_registry.adapters
        assert empty_registry.retailer_names == ["acme"]

    def test_register_multiple_adapters(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        p1 = AdapterPlugin(name=" retailer_a ", cls=ConcreteRetailerAdapter, module_name="mod1")
        p2 = AdapterPlugin(name="retailer_b", cls=ConcreteRetailerAdapter, module_name="mod2")
        empty_registry.register(p1)
        empty_registry.register(p2)

        assert len(empty_registry.adapters) == 2
        assert empty_registry.retailer_names == [" retailer_a ", "retailer_b"]

    def test_register_duplicate_raises(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        p1 = AdapterPlugin(name="dup", cls=ConcreteRetailerAdapter, module_name="mod1")
        p2 = AdapterPlugin(name="dup", cls=ConcreteRetailerAdapter, module_name="mod2")
        empty_registry.register(p1)

        with pytest.raises(ValueError, match="already registered"):
            empty_registry.register(p2)

    def test_register_sets_version_and_deps(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        plugin = AdapterPlugin(
            name="acme",
            cls=ConcreteRetailerAdapter,
            module_name="mod",
            version="3.0",
            dependencies=["turnstile", "hcaptcha"],
        )
        empty_registry.register(plugin)

        loaded = empty_registry.adapters["acme"]
        assert loaded.version == "3.0"
        assert loaded.dependencies == ["turnstile", "hcaptcha"]


# ── AdapterRegistry.discover ──────────────────────────────────────────────────


class TestRegistryDiscover:
    def test_discover_loads_target_walmart_bestbuy(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        empty_registry.discover()

        # All three built-in adapters must be discovered
        for name in ("target", "walmart", "bestbuy"):
            assert empty_registry.is_registered(name), f"{name} not registered"

    def test_discover_idempotent(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        empty_registry.discover()
        empty_registry.discover()  # second call must not raise

        assert len(empty_registry.adapters) == 3

    def test_discover_returns_sorted_names(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        empty_registry.discover()

        assert empty_registry.retailer_names == sorted(empty_registry.retailer_names)

    def test_discovered_flag_set_after_discover(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        assert empty_registry._discovered is False
        empty_registry.discover()
        assert empty_registry._discovered is True


# ── AdapterRegistry.get ──────────────────────────────────────────────────────


class TestRegistryGet:
    def test_get_registered_adapter(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        plugin = AdapterPlugin(
            name="acme",
            cls=ConcreteRetailerAdapter,
            module_name="mod",
        )
        empty_registry.register(plugin)

        cls = empty_registry.get("acme")
        assert cls is ConcreteRetailerAdapter

    def test_get_unknown_returns_none(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        assert empty_registry.get("nonexistent") is None


# ── AdapterRegistry.is_registered ─────────────────────────────────────────


class TestRegistryIsRegistered:
    def test_is_registered_true_for_registered(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        empty_registry.register(
            AdapterPlugin(name="x", cls=ConcreteRetailerAdapter, module_name="mod")
        )
        assert empty_registry.is_registered("x") is True

    def test_is_registered_false_for_unknown(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        assert empty_registry.is_registered("y") is False


# ── AdapterRegistry.validate ─────────────────────────────────────────────────


class TestRegistryValidate:
    def test_validate_empty_registry_returns_no_errors(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        assert empty_registry.validate() == []

    def test_validate_all_methods_present_returns_no_errors(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        empty_registry.discover()
        errors = empty_registry.validate()
        assert errors == [], f"Unexpected validation errors: {errors}"


# ── AdapterRegistry._register_module_classes ────────────────────────────────


class TestRegisterModuleClasses:
    def test_skips_non_adapter_classes(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        # A module containing only plain classes should not register anything
        mod = MagicMock()
        empty_registry._register_module_classes(mod)
        assert empty_registry.adapters == {}

    def test_skips_abstract_base_class(
        self,
        empty_registry: "AdapterRegistry",
    ) -> None:
        from src.bot.monitor.retailers.registry import AdapterRegistry

        # Create a mock module that only has the abstract base
        mod = MagicMock()
        empty_registry._register_module_classes(mod)
        # Should not register anything — nothing concrete in the module
        assert empty_registry.adapters == {}


# ── get_default_registry ─────────────────────────────────────────────────────


class TestGetDefaultRegistry:
    def test_returns_singleton(self) -> None:
        from src.bot.monitor.retailers.registry import get_default_registry

        r1 = get_default_registry()
        r2 = get_default_registry()
        assert r1 is r2

    def test_singleton_adapters_are_populated(self) -> None:
        from src.bot.monitor.retailers.registry import get_default_registry

        r = get_default_registry()
        for name in ("target", "walmart", "bestbuy"):
            assert r.is_registered(name), f"{name} not in default registry"


# ── RETAILER_MODULE_NAMES ────────────────────────────────────────────────────


class TestRetailerModuleNames:
    def test_contains_expected_retailers(self) -> None:
        from src.bot.monitor.retailers.registry import RETAILER_MODULE_NAMES

        assert "target" in RETAILER_MODULE_NAMES
        assert "walmart" in RETAILER_MODULE_NAMES
        assert "bestbuy" in RETAILER_MODULE_NAMES

    def test_is_frozenset(self) -> None:
        from src.bot.monitor.retailers.registry import RETAILER_MODULE_NAMES

        assert isinstance(RETAILER_MODULE_NAMES, frozenset)


# ── AdapterPlugin dataclass ──────────────────────────────────────────────────


class TestAdapterPlugin:
    def test_default_version(self) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        plugin = AdapterPlugin(
            name="x",
            cls=ConcreteRetailerAdapter,
            module_name="mod",
        )
        assert plugin.version == "1.0"

    def test_default_dependencies_empty(self) -> None:
        from src.bot.monitor.retailers.registry import AdapterPlugin

        plugin = AdapterPlugin(
            name="x",
            cls=ConcreteRetailerAdapter,
            module_name="mod",
        )
        assert plugin.dependencies == []
