"""Shipping address autofill for checkout flows.

Per PRD Section 9.3 (CO-1, CO-3) and 10.3 (Security).
"""

from __future__ import annotations

from typing import Any

from src.shared.models import ShippingInfo


# ── Field Mapping Helpers ───────────────────────────────────────────────────────


def build_shipping_form_data(
    shipping: ShippingInfo,
    field_mapping: dict[str, str],
) -> dict[str, Any]:
    """Build a retailer-specific shipping form payload from ShippingInfo.

    Maps ShippingInfo field names to retailer-specific form field names
    using the provided field_mapping dict.

    Args:
        shipping: The ShippingInfo object with address details.
        field_mapping: Dict mapping ShippingInfo field names to retailer
            form field names. E.g. {"name": "shipping-name", "zip_code": "zip"}.

    Returns:
        A dict of form field names → values suitable for POST submission.

    Example:
        field_mapping = {
            "name": "shipping-name",
            "address1": "address-line1",
            "address2": "address-line2",
            "city": "city",
            "state": "state",
            "zip_code": "zip",
            "phone": "phone",
            "email": "email",
        }
        data = build_shipping_form_data(shipping_info, field_mapping)
    """
    result: dict[str, Any] = {}

    for info_field, form_field in field_mapping.items():
        value = getattr(shipping, info_field, "")
        if value:  # Skip empty values
            result[form_field] = value

    return result


def get_standard_shipping_field_mapping() -> dict[str, str]:
    """Return the standard/common shipping field mapping used by most retailers.

    Note: ShippingInfo fields are: name, address1, address2, city, state,
    zip_code, phone, email.

    Returns:
        A mapping from ShippingInfo field names to common form field names.
    """
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


def apply_billing_same_as_shipping(
    form_data: dict[str, Any],
    billing_field_mapping: dict[str, str],
) -> dict[str, Any]:
    """Mark billing address as same as shipping in form data.

    Most retailers have a "billing address same as shipping" checkbox.
    This function sets the appropriate field to indicate same-as-shipping.

    Args:
        form_data: The shipping form data dict (will be copied, not mutated).
        billing_field_mapping: Dict mapping billing fields. Should contain
            a "same_as_shipping" key pointing to the retailer form field
            for the billing=same-as-shipping checkbox.

    Returns:
        A new dict with billing same-as-shipping field added.
    """
    result = dict(form_data)
    same_field = billing_field_mapping.get("same_as_shipping")
    if same_field:
        result[same_field] = "true"
    return result


# ── ShippingAutofill ───────────────────────────────────────────────────────────


class ShippingAutofill:
    """Handles shipping address autofill during checkout.

    Takes a ShippingInfo config object and applies it to a retailer's
    shipping form. Supports billing same-as-shipping option.

    Per PRD Section 9.3 (CO-1, CO-3).
    """

    def __init__(
        self,
        shipping_info: ShippingInfo,
        billing_same_as_shipping: bool = True,
    ) -> None:
        """Initialize the shipping autofill handler.

        Args:
            shipping_info: The shipping address from config.
            billing_same_as_shipping: If True, billing address form will
                be pre-filled to match shipping address.
        """
        self._shipping = shipping_info
        self._billing_same_as_shipping = billing_same_as_shipping

    def build_form_data(
        self,
        field_mapping: dict[str, str],
        billing_field_mapping: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build the full shipping form data including billing same-as-shipping.

        Args:
            field_mapping: Shipping field name mapping.
            billing_field_mapping: Optional billing field mapping. If provided
                and billing_same_as_shipping is True, includes billing same-as-shipping.

        Returns:
            Complete form data dict for shipping step of checkout.
        """
        data = build_shipping_form_data(self._shipping, field_mapping)

        if self._billing_same_as_shipping and billing_field_mapping:
            data = apply_billing_same_as_shipping(data, billing_field_mapping)

        return data

    @property
    def shipping_info(self) -> ShippingInfo:
        """Return the ShippingInfo object."""
        return self._shipping

    @property
    def billing_same_as_shipping(self) -> bool:
        """Return whether billing is set to same as shipping."""
        return self._billing_same_as_shipping


__all__ = [
    "ShippingAutofill",
    "build_shipping_form_data",
    "get_standard_shipping_field_mapping",
    "apply_billing_same_as_shipping",
]
