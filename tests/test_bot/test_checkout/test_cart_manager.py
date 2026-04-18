"""Tests for CartManager.

Per PRD Section 9.2 (CART-1 through CART-8).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.checkout.cart_manager import (
    CartManager,
    CartItem,
    CartOperationResult,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config() -> MagicMock:
    """Minimal config mock for CartManager."""
    cfg = MagicMock()
    cfg.max_cart_quantity = 2
    cfg.retailers = {}
    cfg.items = []
    return cfg


@pytest.fixture
def mock_logger() -> MagicMock:
    """Minimal logger mock for CartManager."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def cart_manager(mock_config: MagicMock, mock_logger: MagicMock) -> CartManager:
    """Construct a CartManager with mocks."""
    return CartManager(config=mock_config, logger=mock_logger)


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Minimal RetailerAdapter mock."""
    adapter = MagicMock()
    adapter.name = "target"
    adapter.add_to_cart = AsyncMock(return_value=True)
    adapter.get_cart = AsyncMock(return_value=[])
    return adapter


# ── Constructor Tests ──────────────────────────────────────────────────────────

def test_cart_manager_init(mock_config: MagicMock, mock_logger: MagicMock) -> None:
    """CartManager initializes with config and logger."""
    cm = CartManager(config=mock_config, logger=mock_logger)
    assert cm.config is mock_config
    assert cm.logger is mock_logger
    assert cm._added_skus == {}
    assert cm._adapters == {}


# ── add_item Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_item_success(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """add_item succeeds when adapter.add_to_cart returns True and item is verified."""
    mock_adapter.get_cart = AsyncMock(return_value=[
        {"sku": "SKU123", "name": "Test Item", "quantity": 1, "price": "$99"},
    ])
    # Mock _get_adapter to return our mock adapter
    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        result = await cart_manager.add_item(
            sku="SKU123",
            quantity=1,
            retailer_name="target",
        )

    assert result.success is True
    assert result.sku == "SKU123"
    assert result.quantity == 1
    mock_adapter.add_to_cart.assert_called_once_with("SKU123", 1)


@pytest.mark.asyncio
async def test_add_item_duplicate_prevents_readd(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """add_item returns error when SKU already added this session (CART-6)."""
    # Pre-mark SKU as added
    cart_manager._added_skus[("target", "SKU123")] = 1

    result = await cart_manager.add_item(
        sku="SKU123",
        quantity=1,
        retailer_name="target",
    )

    assert result.success is False
    assert result.error_type == "duplicate_add"
    mock_adapter.add_to_cart.assert_not_called()


@pytest.mark.asyncio
async def test_add_item_enforces_max_cart_quantity(
    mock_config: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """add_item respects max_cart_quantity from config (CART-7)."""
    mock_config.max_cart_quantity = 1
    cm = CartManager(config=mock_config, logger=mock_logger)

    mock_adapter = MagicMock()
    mock_adapter.name = "target"
    mock_adapter.add_to_cart = AsyncMock(return_value=True)
    mock_adapter.get_cart = AsyncMock(return_value=[])

    with patch.object(cm, "_get_adapter", AsyncMock(return_value=mock_adapter)):
        result = await cm.add_item(
            sku="SKU123",
            quantity=5,  # Request more than max
            retailer_name="target",
        )

    # Should be capped to 1 (max_cart_quantity)
    mock_adapter.add_to_cart.assert_called_once_with("SKU123", 1)


@pytest.mark.asyncio
async def test_add_item_retailer_limit_precedence(
    mock_config: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """Retailer-specific max_cart_quantity takes precedence over global (CART-8)."""
    mock_config.max_cart_quantity = 4
    mock_config.retailers = {
        "target": {"max_cart_quantity": 2},
    }
    mock_config.items = []
    cm = CartManager(config=mock_config, logger=mock_logger)

    mock_adapter = MagicMock()
    mock_adapter.name = "target"
    mock_adapter.add_to_cart = AsyncMock(return_value=True)
    mock_adapter.get_cart = AsyncMock(return_value=[])

    with patch.object(cm, "_get_adapter", AsyncMock(return_value=mock_adapter)):
        result = await cm.add_item(
            sku="SKU123",
            quantity=3,
            retailer_name="target",
        )

    # Should be capped to 2 (retailer-specific limit)
    mock_adapter.add_to_cart.assert_called_once_with("SKU123", 2)


@pytest.mark.asyncio
async def test_add_item_no_adapter(
    cart_manager: CartManager,
) -> None:
    """add_item fails gracefully when no adapter is found."""
    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=None),
    ):
        result = await cart_manager.add_item(
            sku="SKU123",
            quantity=1,
            retailer_name="unknown_retailer",
        )

    assert result.success is False
    assert result.error_type == "no_adapter"


@pytest.mark.asyncio
async def test_add_item_api_failure_then_ui_fallback(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """add_item tries UI fallback when API add fails."""
    mock_adapter.add_to_cart = AsyncMock(return_value=False)
    mock_adapter.get_cart = AsyncMock(return_value=[])  # verification fails

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        result = await cart_manager.add_item(
            sku="SKU123",
            quantity=1,
            retailer_name="target",
        )

    # Should have tried both API and UI fallback, ultimately failed
    assert result.success is False


@pytest.mark.asyncio
async def test_add_item_verification_fails(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """add_item returns error when item is not found in cart after adding (CART-2)."""
    mock_adapter.add_to_cart = AsyncMock(return_value=True)
    # get_cart returns empty — item not actually in cart
    mock_adapter.get_cart = AsyncMock(return_value=[])

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        result = await cart_manager.add_item(
            sku="SKU123",
            quantity=1,
            retailer_name="target",
        )

    assert result.success is False
    assert result.error_type == "verification_failed"


# ── verify_cart Tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_cart_item_present(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """verify_cart returns True when SKU is in cart."""
    mock_adapter.get_cart = AsyncMock(return_value=[
        {"sku": "SKU123", "name": "Test Item", "quantity": 1, "price": "$99"},
        {"sku": "SKU456", "name": "Other Item", "quantity": 2, "price": "$49"},
    ])

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        present, items = await cart_manager.verify_cart("SKU123", "target")

    assert present is True
    assert len(items) == 2
    assert items[0].sku == "SKU123"


@pytest.mark.asyncio
async def test_verify_cart_item_not_present(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """verify_cart returns False when SKU is not in cart."""
    mock_adapter.get_cart = AsyncMock(return_value=[
        {"sku": "SKU999", "name": "Other Item", "quantity": 1, "price": "$10"},
    ])

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        present, items = await cart_manager.verify_cart("SKU123", "target")

    assert present is False


@pytest.mark.asyncio
async def test_verify_cart_no_adapter(
    cart_manager: CartManager,
) -> None:
    """verify_cart returns False when no adapter found."""
    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=None),
    ):
        present, items = await cart_manager.verify_cart("SKU123", "target")

    assert present is False
    assert items == []


# ── clear_cart Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_cart_success(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """clear_cart succeeds when adapter has _clear_cart method."""
    mock_adapter._clear_cart = AsyncMock(return_value=True)

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        result = await cart_manager.clear_cart("target")

    assert result is True
    cart_manager.logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_clear_cart_no_adapter(
    cart_manager: CartManager,
) -> None:
    """clear_cart returns False when no adapter found."""
    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=None),
    ):
        result = await cart_manager.clear_cart("target")

    assert result is False


@pytest.mark.asyncio
async def test_clear_cart_via_page_fallback(
    cart_manager: CartManager,
) -> None:
    """clear_cart falls back to UI when no _clear_cart method but page exists."""
    mock_adapter = MagicMock()
    mock_adapter.name = "target"
    mock_adapter._clear_cart = AsyncMock(side_effect=AttributeError("no method"))
    mock_adapter._page = MagicMock()
    mock_adapter._page.goto = AsyncMock()
    mock_adapter._page.query_selector_all = AsyncMock(return_value=[])

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        result = await cart_manager.clear_cart("target")

    # No remove buttons found, so False
    assert result is True  # UI navigation succeeded even with no buttons


# ── get_cart Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_cart_success(
    cart_manager: CartManager,
    mock_adapter: MagicMock,
) -> None:
    """get_cart returns list of CartItems."""
    mock_adapter.get_cart = AsyncMock(return_value=[
        {"sku": "SKU123", "name": "Item A", "quantity": 2, "price": "$99"},
        {"sku": "SKU456", "name": "Item B", "quantity": 1, "price": "$49"},
    ])

    with patch.object(
        cart_manager,
        "_get_adapter",
        AsyncMock(return_value=mock_adapter),
    ):
        items = await cart_manager.get_cart("target")

    assert len(items) == 2
    assert items[0].sku == "SKU123"
    assert items[0].quantity == 2


# ── reset_session Tests ─────────────────────────────────────────────────────────

def test_reset_session_single_retailer(cart_manager: CartManager) -> None:
    """reset_session clears tracking for one retailer."""
    cart_manager._added_skus[("target", "SKU1")] = 1
    cart_manager._added_skus[("walmart", "SKU2")] = 2

    cart_manager.reset_session("target")

    assert ("target", "SKU1") not in cart_manager._added_skus
    assert ("walmart", "SKU2") in cart_manager._added_skus


def test_reset_session_all(cart_manager: CartManager) -> None:
    """reset_session with no args clears all tracking."""
    cart_manager._added_skus[("target", "SKU1")] = 1
    cart_manager._added_skus[("walmart", "SKU2")] = 2

    cart_manager.reset_session()

    assert cart_manager._added_skus == {}


# ── _get_effective_quantity Tests ──────────────────────────────────────────────

def test_effective_quantity_respects_max(mock_config: MagicMock, mock_logger: MagicMock) -> None:
    """_get_effective_quantity caps at max_cart_quantity."""
    mock_config.max_cart_quantity = 3
    mock_config.retailers = {}
    mock_config.items = []
    cm = CartManager(config=mock_config, logger=mock_logger)

    qty = cm._get_effective_quantity("SKU123", requested_quantity=5, retailer_name="target")
    assert qty == 3


def test_effective_quantity_min_one(mock_config: MagicMock, mock_logger: MagicMock) -> None:
    """_get_effective_quantity never returns less than 1."""
    mock_config.max_cart_quantity = 0  # Edge case
    mock_config.retailers = {}
    mock_config.items = []
    cm = CartManager(config=mock_config, logger=mock_logger)

    qty = cm._get_effective_quantity("SKU123", requested_quantity=1, retailer_name="target")
    assert qty == 1


def test_effective_quantity_item_specific(
    mock_config: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """Item-specific max_cart_quantity overrides global and retailer."""
    mock_config.max_cart_quantity = 5
    mock_config.retailers = {"target": {"max_cart_quantity": 4}}
    mock_config.items = [{"name": "Test Item", "skus": ["SKU123"], "max_cart_quantity": 2}]

    cm = CartManager(config=mock_config, logger=mock_logger)

    qty = cm._get_effective_quantity("SKU123", requested_quantity=10, retailer_name="target")
    # SKU-specific (2) < retailer (4) < global (5)
    assert qty == 2


# ── CartItem dataclass Tests ────────────────────────────────────────────────────

def test_cart_item_fields() -> None:
    """CartItem stores all fields correctly."""
    item = CartItem(sku="SKU123", name="Test Product", quantity=2, price="$99.99")
    assert item.sku == "SKU123"
    assert item.name == "Test Product"
    assert item.quantity == 2
    assert item.price == "$99.99"


# ── CartOperationResult Tests ──────────────────────────────────────────────────

def test_cart_operation_result_success() -> None:
    """CartOperationResult stores success result correctly."""
    result = CartOperationResult(
        success=True,
        sku="SKU123",
        quantity=2,
        cart_url="https://target.com/cart",
        items_in_cart=3,
    )
    assert result.success is True
    assert result.sku == "SKU123"
    assert result.quantity == 2


def test_cart_operation_result_error() -> None:
    """CartOperationResult stores error information correctly."""
    result = CartOperationResult(
        success=False,
        sku="SKU123",
        error="Item out of stock",
        error_type="out_of_stock",
    )
    assert result.success is False
    assert result.error == "Item out of stock"
    assert result.error_type == "out_of_stock"


# ── _mark_sku_added Tests ─────────────────────────────────────────────────────

def test_mark_sku_added_increments(mock_config: MagicMock, mock_logger: MagicMock) -> None:
    """_mark_sku_added increments count for same SKU."""
    cm = CartManager(config=mock_config, logger=mock_logger)
    cm._mark_sku_added("target", "SKU123", 1)
    cm._mark_sku_added("target", "SKU123", 1)
    assert cm._added_skus[("target", "SKU123")] == 2


# ── _get_cart_url Tests ───────────────────────────────────────────────────────

def test_get_cart_url_all_retailers(cart_manager: CartManager) -> None:
    """_get_cart_url returns correct URLs for known retailers."""
    assert "target.com" in cart_manager._get_cart_url("target")
    assert "walmart.com" in cart_manager._get_cart_url("walmart")
    assert "bestbuy.com" in cart_manager._get_cart_url("bestbuy")
    assert cart_manager._get_cart_url("unknown") == ""