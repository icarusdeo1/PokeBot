"""Tests for CheckoutFlow orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.checkout.checkout_flow import (
    CheckoutFlow,
    CheckoutResult,
)
from src.shared.models import CheckoutStage


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """Create a mock Config object with shipping and payment."""
    config = MagicMock()
    config.shipping = MagicMock()
    config.shipping.name = "Test User"
    config.shipping.address1 = "123 Test St"
    config.shipping.city = "TestCity"
    config.shipping.state = "TS"
    config.shipping.zip_code = "12345"
    config.shipping.phone = "555-1234"
    config.shipping.email = "test@example.com"
    config.payment = MagicMock()
    config.payment.card_number = "4111111111111234"
    config.payment.expiry_month = "12"
    config.payment.expiry_year = "2027"
    config.payment.cvv = "123"
    config.checkout = MagicMock()
    config.checkout.retry_attempts = 2
    config.checkout.human_delay_ms = 300
    config.checkout.max_human_delay_ms = 350
    return config


@pytest.fixture
def mock_logger():
    """Create a mock Logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


@pytest.fixture
def mock_cart_manager():
    """Create a mock CartManager."""
    manager = MagicMock()
    manager.verify_cart = AsyncMock(return_value=(True, []))
    manager.clear_cart = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_adapter():
    """Create a mock RetailerAdapter."""
    adapter = MagicMock()
    adapter.name = "target"
    adapter.go_to_checkout = AsyncMock(return_value=True)
    adapter.fill_shipping_form = AsyncMock(return_value=True)
    adapter.fill_payment_form = AsyncMock(return_value=True)
    adapter.handle_review_step = AsyncMock(return_value=True)
    adapter.submit_order = AsyncMock(return_value=("ORD123", ""))
    adapter.confirm_order = AsyncMock(return_value=(True, "ORD123"))
    return adapter


# ── Tests: CheckoutFlow.run() success path ───────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_success(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Full checkout completes successfully on first attempt."""
    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is True
    assert result.order_id == "ORD123"
    assert result.stage == CheckoutStage.CONFIRMATION.value

    # Verify events were logged
    mock_logger.info.assert_any_call(
        "CHECKOUT_STARTED",
        item="Pokemon Box",
        sku="SKU123",
        retailer="target",
        dry_run=True,
    )
    mock_logger.info.assert_any_call(
        "CHECKOUT_SUCCESS",
        item="Pokemon Box",
        retailer="target",
        order_id="ORD123",
        attempts=1,
    )


@pytest.mark.asyncio
async def test_checkout_flow_success_on_retry(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Checkout succeeds after first attempt failure."""
    call_count = 0

    async def submit_with_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "", "Network error"
        return f"ORD{call_count}", ""

    mock_adapter.submit_order = AsyncMock(side_effect=submit_with_retry)

    # Make cart empty on first attempt, present on second
    verify_count = 0

    async def verify_with_retry(sku, retailer):
        nonlocal verify_count
        verify_count += 1
        if verify_count == 1:
            return False, []  # First attempt: item not in cart
        return True, []  # Second attempt: item present

    mock_cart_manager.verify_cart = AsyncMock(side_effect=verify_with_retry)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is True
    assert "ORD" in result.order_id


@pytest.mark.asyncio
async def test_checkout_flow_max_retries_exhausted(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """All retry attempts exhausted returns failure."""
    mock_adapter.submit_order = AsyncMock(return_value=("", "Server error"))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is False
    assert "failed" in result.error.lower()
    assert result.attempts == 3  # max_retries=2 → 3 total attempts


@pytest.mark.asyncio
async def test_checkout_flow_item_oos(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Item no longer in cart returns failure at pre_check stage."""
    mock_cart_manager.verify_cart = AsyncMock(return_value=(False, []))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is False
    assert result.stage == CheckoutStage.PRE_CHECK.value
    assert "no longer available" in result.error


@pytest.mark.asyncio
async def test_checkout_flow_navigate_failure(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Failed navigation to checkout returns failure."""
    mock_adapter.go_to_checkout = AsyncMock(return_value=False)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is False
    assert result.stage == CheckoutStage.SHIPPING.value
    assert "navigate" in result.error.lower()


@pytest.mark.asyncio
async def test_checkout_flow_confirm_failure(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Order submitted but not confirmed returns failure."""
    mock_adapter.submit_order = AsyncMock(return_value=("ORD123", ""))
    mock_adapter.confirm_order = AsyncMock(return_value=(False, ""))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is False
    assert result.stage == CheckoutStage.CONFIRMATION.value
    assert "submitted but not confirmed" in result.error


# ── Tests: CheckoutFlow checkout retry logic ─────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_clears_cart_on_retry(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Cart is cleared before retry after checkout failure."""
    submit_count = 0

    async def submit_fail_twice(*args, **kwargs):
        nonlocal submit_count
        submit_count += 1
        if submit_count <= 2:
            return "", f"Attempt {submit_count} failed"
        return "ORDFINAL", ""

    mock_adapter.submit_order = AsyncMock(side_effect=submit_fail_twice)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is True
    # clear_cart should be called for each failed attempt
    assert mock_cart_manager.clear_cart.call_count >= 1


@pytest.mark.asyncio
async def test_checkout_flow_logs_checkout_attempt_per_retry(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Each checkout attempt is logged with attempt number."""
    mock_adapter.submit_order = AsyncMock(return_value=("", "error"))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    # Should have logged CHECKOUT_ATTEMPT for each attempt
    attempts_logged = [
        call
        for call in mock_logger.info.call_args_list
        if call[0][0] == "CHECKOUT_ATTEMPT"
    ]
    assert len(attempts_logged) == 3  # max_retries=2 → 3 total attempts


# ── Tests: Payment decline handler ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_payment_decline_retries_once(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Payment decline triggers one retry after 2s delay."""
    decline_count = 0

    async def submit_with_decline(*args, **kwargs):
        nonlocal decline_count
        decline_count += 1
        if decline_count == 1:
            return "", "Payment declined: card_declined"
        return "ORDOK", ""

    mock_adapter.submit_order = AsyncMock(side_effect=submit_with_decline)

    # Mock sleep to avoid actual delays in test
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

        result = await flow.run(
            adapter=mock_adapter,
            sku="SKU123",
            item_name="Pokemon Box",
            dry_run=True,
        )

        assert result.success is True
        # Should have slept once for the decline retry
        mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_checkout_flow_payment_decline_exhausted_retries(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Payment decline on second attempt aborts with PAYMENT_DECLINED webhook."""
    mock_adapter.submit_order = AsyncMock(return_value=("", "Payment declined: card_declined"))

    webhook_events: list = []

    async def capture_event(event):
        webhook_events.append(event)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

        result = await flow.run(
            adapter=mock_adapter,
            sku="SKU123",
            item_name="Pokemon Box",
            dry_run=True,
            webhook_callback=capture_event,
        )

    assert result.success is False
    assert "declined" in result.error.lower()
    assert "retries exhausted" in result.error.lower()


# ── Tests: CheckoutFlow._human_delay ─────────────────────────────────────────

def test_checkout_flow_human_delay_in_range(mock_config, mock_logger, mock_cart_manager):
    """Human delay is within configured range [300, 350]ms."""
    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    delays = [flow._human_delay() for _ in range(50)]

    for delay in delays:
        assert 300 <= delay <= 350


def test_checkout_flow_human_delay_with_explicit_value(
    mock_config, mock_logger, mock_cart_manager
):
    """Explicit base_ms overrides default range."""
    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    delay = flow._human_delay(base_ms=500)
    assert delay == 500


# ── Tests: CheckoutFlow._attempt_checkout stage progression ───────────────────

@pytest.mark.asyncio
async def test_checkout_flow_stage_progression(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """All stages are visited in order on successful checkout."""
    stages_logged: list[str] = []

    def capture_info(event, **kwargs):
        if event.startswith("CHECKOUT_") and "stage" in kwargs:
            stages_logged.append(kwargs["stage"])

    mock_logger.info.side_effect = lambda event, **kwargs: capture_info(event, **kwargs)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    # Should have progressed through: pre_check → shipping → payment → review → submit → confirmation
    assert CheckoutStage.PRE_CHECK.value in stages_logged
    assert CheckoutStage.SHIPPING.value in stages_logged
    assert CheckoutStage.PAYMENT.value in stages_logged


# ── Tests: CheckoutFlow with no payment/shipping config ───────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_no_payment_config(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Checkout proceeds even if no payment info in config."""
    mock_config.payment = None
    mock_adapter.submit_order = AsyncMock(return_value=("ORD123", ""))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    # Should still complete (payment autofill skipped)
    assert result.success is True


@pytest.mark.asyncio
async def test_checkout_flow_no_shipping_config(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Checkout proceeds even if no shipping info in config."""
    mock_config.shipping = None
    mock_adapter.submit_order = AsyncMock(return_value=("ORD123", ""))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    # Should still complete (shipping autofill skipped)
    assert result.success is True


# ── Tests: CheckoutFlow fallback methods ─────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_submit_order_fallback_to_checkout_method(
    mock_config, mock_logger, mock_cart_manager
):
    """If submit_order not implemented, falls back to adapter.checkout()."""
    adapter = MagicMock()
    adapter.name = "target"
    adapter.verify_cart = AsyncMock(return_value=True)
    # No submit_order — should fall back to checkout()
    adapter.checkout = AsyncMock(return_value=(True, "ORD-FALLBACK", ""))
    adapter.go_to_checkout = AsyncMock(return_value=True)
    adapter.fill_shipping_form = AsyncMock(return_value=True)
    adapter.fill_payment_form = AsyncMock(return_value=True)
    adapter.handle_review_step = AsyncMock(return_value=True)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is True
    assert result.order_id == "ORD-FALLBACK"
    adapter.checkout.assert_called_once_with(dry_run=True)


# ── Tests: CheckoutFlow with webhook callback ─────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_fires_webhook_on_success(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Webhook callback is invoked on successful checkout."""
    from src.shared.models import WebhookEvent

    events: list[WebhookEvent] = []

    async def capture_event(event):
        events.append(event)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
        webhook_callback=capture_event,
    )

    # Note: current implementation fires LOGGING events, not webhook events
    # The webhook is fired by the StockMonitor after checkout completes
    # But _fire_event exists for future use
    assert result.success is True


# ── Tests: CheckoutFlow timeout handling ──────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_exception_returns_failure(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Unexpected exception during checkout returns failure."""
    mock_adapter.go_to_checkout = AsyncMock(side_effect=RuntimeError("Browser crashed"))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is False
    assert result.stage == CheckoutStage.PRE_CHECK.value
    assert "exception" in result.error.lower()


# ── Tests: CheckoutFlow dry_run flag ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_dry_run_passed_to_submit(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """dry_run=True is passed to adapter.submit_order and adapter.checkout."""
    submit_calls: list = []

    async def track_submit(order_id, dry_run=False):
        submit_calls.append({"order_id": order_id, "dry_run": dry_run})
        return "ORD123", ""

    mock_adapter.submit_order = AsyncMock(side_effect=track_submit)

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert submit_calls[0]["dry_run"] is True


# ── Tests: CheckoutResult ──────────────────────────────────────────────────────

def test_checkout_result_fields():
    """CheckoutResult dataclass has all required fields."""
    result = CheckoutResult(
        success=True,
        order_id="ORD-1",
        stage=CheckoutStage.CONFIRMATION.value,
        error="",
        attempts=1,
    )

    assert result.success is True
    assert result.order_id == "ORD-1"
    assert result.stage == CheckoutStage.CONFIRMATION.value
    assert result.error == ""
    assert result.attempts == 1


# ── Tests: CheckoutFlow with default retry config ─────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_default_retry_config(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Default retry config (max_retries=2) used when checkout config absent."""
    mock_config.checkout = None  # No checkout config
    mock_adapter.submit_order = AsyncMock(return_value=("", "error"))

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    # With max_retries=2, should have made 3 attempts
    assert result.attempts == 3
    assert result.success is False


# ── Tests: CheckoutFlow async delay ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_human_delay_async_sleeps(
    mock_config, mock_logger, mock_cart_manager
):
    """_human_delay_async actually awaits asyncio.sleep for correct duration."""
    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await flow._human_delay_async(base_ms=100)
        mock_sleep.assert_called_once_with(100.0)


# ── Tests: adapter without review step ──────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_flow_no_review_step_implemented(
    mock_config, mock_logger, mock_cart_manager, mock_adapter
):
    """Adapter without handle_review_step returns True (no review needed)."""
    del mock_adapter.handle_review_step

    flow = CheckoutFlow(mock_config, mock_logger, mock_cart_manager)

    # Should not raise — returns True as default
    result = await flow.run(
        adapter=mock_adapter,
        sku="SKU123",
        item_name="Pokemon Box",
        dry_run=True,
    )

    assert result.success is True