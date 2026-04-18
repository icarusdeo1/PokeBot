"""Retailer adapter plugin registry.

Auto-discovers and loads retailer adapters from the `src.bot.monitor.retailers`
package. Adapters are registered by retailer name, enabling runtime discovery
without hardcoding.

Per PRD Section 9.15 (ADP-1, ADP-2, ADP-3).
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from src.bot.monitor.retailers.base import RetailerAdapter

RETAILER_MODULE_NAMES = frozenset(["target", "walmart", "bestbuy"])


@dataclass
class AdapterPlugin:
    """A discovered retailer adapter plugin."""

    name: str
    """Retailer name (e.g. 'target')."""

    cls: type[RetailerAdapter]
    """The adapter class."""

    module_name: str
    """Dotted module path the adapter was loaded from."""

    version: str = "1.0"
    """Plugin version string. Adapters may override this."""

    dependencies: list[str] = field(default_factory=list)
    """Optional list of dependency names (e.g. ['turnstile'])."""


class AdapterRegistry:
    """Registry for retailer adapter plugins.

    Discovers adapters in `src.bot.monitor.retailers` that inherit from
    `RetailerAdapter` and exposes them as a mapping: retailer name → class.

    Usage::

        registry = AdapterRegistry()
        registry.discover()
        for name, cls in registry.adapters.items():
            print(f"{name}: {cls}")

    Per PRD Section 9.15 (ADP-1, ADP-2, ADP-3).
    """

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterPlugin] = {}
        self._discovered: bool = False

    @property
    def adapters(self) -> dict[str, AdapterPlugin]:
        """Return the mapping of retailer name → adapter plugin."""
        return dict(self._adapters)

    @property
    def retailer_names(self) -> list[str]:
        """Return sorted list of discovered retailer names."""
        return sorted(self._adapters.keys())

    def register(self, plugin: AdapterPlugin) -> None:
        """Manually register an adapter plugin.

        Raises:
            ValueError: If an adapter with the same name is already registered.
        """
        if plugin.name in self._adapters:
            raise ValueError(
                f"Adapter named '{plugin.name}' is already registered "
                f"(existing: {self._adapters[plugin.name].module_name}, "
                f"new: {plugin.module_name})"
            )
        self._adapters[plugin.name] = plugin

    def discover(self) -> None:
        """Discover and load all retailer adapters from the retailers package.

        Imports every module in `src.bot.monitor.retailers` whose name is in
        RETAILER_MODULE_NAMES (target, walmart, bestbuy). For each module,
        inspects classes that inherit from `RetailerAdapter` and registers them.

        Logs a warning and skips modules that fail to import.
        """
        if self._discovered:
            return
        self._discovered = True

        package_name = "src.bot.monitor.retailers"
        package = importlib.import_module(package_name)

        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name not in RETAILER_MODULE_NAMES:
                continue

            full_name = f"{package_name}.{module_info.name}"
            try:
                mod = importlib.import_module(full_name)
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.warning(
                    "Failed to import retailer module '%s': %s",
                    full_name,
                    exc,
                )
                continue

            self._register_module_classes(mod)

    def _register_module_classes(self, mod: object) -> None:
        """Register RetailerAdapter subclasses from a loaded module.

        Inspects all public classes in `mod`. For each class that is a subclass
        of `RetailerAdapter` (but not `RetailerAdapter` itself) and has a
        non-empty `name` attribute, creates an `AdapterPlugin` and registers it.

        Args:
            mod: An already-imported module object.
        """
        from src.bot.monitor.retailers.base import RetailerAdapter as ABC

        mod_name = getattr(mod, "__name__", None) or "unknown"

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                cls = getattr(mod, attr_name)
            except AttributeError:
                continue
            if not isinstance(cls, type):
                continue
            if cls is ABC:
                continue
            if issubclass(cls, ABC):
                try:
                    inst = cls.__new__(cls)
                except TypeError:
                    # Can't instantiate abstract class; skip
                    continue
                # Read the class-level name attribute
                retailer_name = getattr(inst, "name", None)
                if not retailer_name:
                    continue
                # Build plugin metadata; allow class-level version/dependencies
                version = getattr(cls, "VERSION", "1.0")
                deps = getattr(cls, "DEPENDENCIES", [])
                plugin = AdapterPlugin(
                    name=retailer_name,
                    cls=cls,
                    module_name=mod_name,
                    version=version,
                    dependencies=deps,
                )
                try:
                    self.register(plugin)
                except ValueError:
                    # Already registered by a previous module; skip
                    pass

    def get(self, name: str) -> type[RetailerAdapter] | None:
        """Return the adapter class for a given retailer name, or None."""
        plugin = self._adapters.get(name)
        if plugin is None:
            return None
        return plugin.cls

    def is_registered(self, name: str) -> bool:
        """Return True if an adapter for the given retailer name is registered."""
        return name in self._adapters

    def validate(self) -> list[str]:
        """Validate all registered adapters.

        Checks that each adapter class has all required abstract methods.

        Returns:
            List of error messages. Empty list means all adapters are valid.
        """
        errors: list[str] = []
        for name, plugin in self._adapters.items():
            cls = plugin.cls
            for method in (
                "login",
                "check_stock",
                "add_to_cart",
                "get_cart",
                "checkout",
                "handle_captcha",
                "check_queue",
            ):
                if not hasattr(cls, method):
                    errors.append(
                        f"Adapter '{name}' ({plugin.module_name}) is missing "
                        f"required method: {method}"
                    )
        return errors


# ── Module-level singleton ───────────────────────────────────────────────────

_default_registry: AdapterRegistry | None = None


def get_default_registry() -> AdapterRegistry:
    """Return the module-level default registry (lazily created)."""
    global _default_registry  # noqa: PLW0603
    if _default_registry is None:
        _default_registry = AdapterRegistry()
        _default_registry.discover()
    return _default_registry
