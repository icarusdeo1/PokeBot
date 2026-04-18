"""Tests for shipping autofill module."""

from __future__ import annotations

import pytest

from src.bot.checkout.shipping import (
    ShippingAutofill,
    apply_billing_same_as_shipping,
    build_shipping_form_data,
    get_standard_shipping_field_mapping,
)
from src.shared.models import ShippingInfo


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_shipping() -> ShippingInfo:
    """Sample shipping info for tests."""
    return ShippingInfo(
        name="John Doe",
        address1="123 Main St",
        address2="Apt 4B",
        city="Los Angeles",
        state="CA",
        zip_code="90001",
        phone="555-123-4567",
        email="john@example.com",
    )


@pytest.fixture
def standard_mapping() -> dict[str, str]:
    """Standard field mapping for most retailers."""
    return {
        "name": "shipping-name",
        "address1": "shipping-address1",
        "address2": "shipping-address2",
        "city": "shipping-city",
        "state": "shipping-state",
        "zip_code": "shipping-zip",
        "phone": "shipping-phone",
        "email": "shipping-email",
    }


# ── build_shipping_form_data ──────────────────────────────────────────────────


class TestBuildShippingFormData:
    """Tests for build_shipping_form_data()."""

    def test_maps_all_fields(self, sample_shipping, standard_mapping):
        """All non-empty fields are included in output."""
        result = build_shipping_form_data(sample_shipping, standard_mapping)

        assert result["shipping-name"] == "John Doe"
        assert result["shipping-address1"] == "123 Main St"
        assert result["shipping-address2"] == "Apt 4B"
        assert result["shipping-city"] == "Los Angeles"
        assert result["shipping-state"] == "CA"
        assert result["shipping-zip"] == "90001"
        assert result["shipping-phone"] == "555-123-4567"
        assert result["shipping-email"] == "john@example.com"

    def test_skips_empty_fields(self, standard_mapping):
        """Empty fields in ShippingInfo are not included in output."""
        shipping = ShippingInfo(
            name="Jane Doe",
            address1="456 Oak Ave",
            city="San Francisco",
            state="CA",
            zip_code="94102",
        )
        result = build_shipping_form_data(shipping, standard_mapping)

        assert "shipping-name" in result
        assert "shipping-address2" not in result  # empty
        assert "shipping-phone" not in result  # empty
        assert "shipping-email" not in result  # empty

    def test_custom_field_mapping(self, sample_shipping):
        """Custom retailer field names work correctly."""
        mapping = {
            "name": "ship_fullname",
            "city": "ship_city",
            "zip_code": "ship_zipcode",
        }
        result = build_shipping_form_data(sample_shipping, mapping)

        assert result["ship_fullname"] == "John Doe"
        assert result["ship_city"] == "Los Angeles"
        assert result["ship_zipcode"] == "90001"
        # Fields not in mapping are not included
        assert "shipping-address1" not in result

    def test_empty_shipping_info(self, standard_mapping):
        """Empty ShippingInfo produces empty form data."""
        shipping = ShippingInfo()
        result = build_shipping_form_data(shipping, standard_mapping)
        assert result == {}


# ── apply_billing_same_as_shipping ────────────────────────────────────────────


class TestApplyBillingSameAsShipping:
    """Tests for apply_billing_same_as_shipping()."""

    def test_adds_same_as_shipping_field(self):
        """Adds billing same-as-shipping field to form data."""
        form_data = {"shipping-name": "John Doe", "shipping-city": "LA"}
        billing_mapping = {"same_as_shipping": "billing-same-as-shipping"}

        result = apply_billing_same_as_shipping(form_data, billing_mapping)

        assert result["shipping-name"] == "John Doe"
        assert result["shipping-city"] == "LA"
        assert result["billing-same-as-shipping"] == "true"

    def test_does_not_mutate_original(self):
        """Original form data dict is not modified."""
        form_data = {"shipping-name": "John Doe"}
        billing_mapping = {"same_as_shipping": "billing-same"}

        result = apply_billing_same_as_shipping(form_data, billing_mapping)

        assert "billing-same" not in form_data
        assert result["billing-same"] == "true"

    def test_missing_same_as_shipping_key(self):
        """If billing mapping has no same_as_shipping key, returns copy."""
        form_data = {"shipping-name": "John Doe"}
        billing_mapping = {"other_field": "other"}

        result = apply_billing_same_as_shipping(form_data, billing_mapping)

        assert result == {"shipping-name": "John Doe"}


# ── ShippingAutofill ───────────────────────────────────────────────────────────


class TestShippingAutofill:
    """Tests for ShippingAutofill class."""

    def test_build_form_data_with_billing_same(self, sample_shipping):
        """Billing same-as-shipping is applied when enabled."""
        autofill = ShippingAutofill(sample_shipping, billing_same_as_shipping=True)
        mapping = {
            "name": "name",
            "city": "city",
            "zip_code": "zip",
        }
        billing_mapping = {"same_as_shipping": "billing-same"}

        result = autofill.build_form_data(mapping, billing_mapping)

        assert result["name"] == "John Doe"
        assert result["billing-same"] == "true"

    def test_build_form_data_without_billing_same(self, sample_shipping):
        """Billing same-as-shipping is not applied when disabled."""
        autofill = ShippingAutofill(sample_shipping, billing_same_as_shipping=False)
        mapping = {
            "name": "name",
            "city": "city",
        }
        billing_mapping = {"same_as_shipping": "billing-same"}

        result = autofill.build_form_data(mapping, billing_mapping)

        assert result["name"] == "John Doe"
        assert "billing-same" not in result

    def test_billing_same_without_billing_mapping(self, sample_shipping):
        """If no billing_mapping provided, only shipping fields are included."""
        autofill = ShippingAutofill(sample_shipping, billing_same_as_shipping=True)
        mapping = {
            "name": "name",
            "city": "city",
        }

        result = autofill.build_form_data(mapping)

        assert result["name"] == "John Doe"
        assert result["city"] == "Los Angeles"

    def test_properties(self, sample_shipping):
        """shipping_info and billing_same_as_shipping properties work."""
        autofill = ShippingAutofill(sample_shipping, billing_same_as_shipping=True)

        assert autofill.shipping_info == sample_shipping
        assert autofill.billing_same_as_shipping is True


# ── get_standard_shipping_field_mapping ────────────────────────────────────────


class TestGetStandardShippingFieldMapping:
    """Tests for get_standard_shipping_field_mapping()."""

    def test_returns_all_fields(self):
        """Standard mapping includes all expected fields."""
        mapping = get_standard_shipping_field_mapping()

        assert mapping["name"] == "shipping-name"
        assert mapping["address1"] == "shipping-address1"
        assert mapping["address2"] == "shipping-address2"
        assert mapping["city"] == "shipping-city"
        assert mapping["state"] == "shipping-state"
        assert mapping["zip_code"] == "shipping-zip"
        assert mapping["phone"] == "shipping-phone"
        assert mapping["email"] == "shipping-email"
