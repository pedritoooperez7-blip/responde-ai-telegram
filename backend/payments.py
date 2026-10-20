"""Payment pricing and currency handling.

Display strings and verification values are deliberately separate:

* ``amount()`` builds the human-readable text shown by the Mini App.
* ``verification_amount()`` returns the numeric value actually transferred.
* ``expected_values()`` reads a stored operation and returns what the bank/SMS
  matcher must compare, so a display currency can never be compared against a
  payment in another currency.

The commercial currency and prices come from the environment. Defaults match the
values that were already hard-coded for Spanish users. The owner must confirm
whether English users should see a converted USD price; without an explicit
exchange rate this module never converts or invents rates.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CURRENCY = "CUP"
DEFAULT_PRICES = {"weekly": 2500.0, "annual": 15500.0}
VALID_PLANS = tuple(DEFAULT_PRICES)
_PRICE_ENV = {"weekly": "PAYMENT_PRICE_WEEKLY", "annual": "PAYMENT_PRICE_ANNUAL"}


def validate_plan(plan: str) -> str:
    value = (plan or "").strip().lower()
    if value not in DEFAULT_PRICES:
        raise ValueError("Plan inválido")
    return value


def payment_currency() -> str:
    """Commercial currency used to create and verify payments (default CUP)."""
    raw = (os.getenv("PAYMENT_CURRENCY") or DEFAULT_CURRENCY).strip().upper()
    if len(raw) != 3 or not raw.isalpha():
        logger.warning("PAYMENT_CURRENCY is invalid; falling back to %s", DEFAULT_CURRENCY)
        return DEFAULT_CURRENCY
    return raw


def payment_price(plan: str) -> float:
    """Configured price for a plan, in ``payment_currency()``."""
    plan = validate_plan(plan)
    raw = (os.getenv(_PRICE_ENV[plan]) or "").strip()
    if not raw:
        return DEFAULT_PRICES[plan]
    try:
        value = round(float(raw.replace(",", ".")), 2)
    except (TypeError, ValueError):
        logger.warning("Invalid price configuration for %s; using the default", plan)
        return DEFAULT_PRICES[plan]
    if value <= 0:
        logger.warning("Non-positive price configuration for %s; using the default", plan)
        return DEFAULT_PRICES[plan]
    return value


def format_amount(value: float, currency: str | None = None) -> str:
    currency = (currency or payment_currency()).strip().upper()
    number = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return f"{number} {currency}"


def amount(plan: str, lang: str | None = None) -> str:
    """Human-readable amount.

    ``lang`` is accepted for backwards compatibility but no longer changes the
    currency: showing USD while charging CUP made payments impossible to match.
    """
    return format_amount(payment_price(plan), payment_currency())


def verification_amount(plan: str) -> float:
    """Numeric amount that a real payment must match, in ``payment_currency()``."""
    return payment_price(plan)


def expected_values(operation: Mapping[str, Any], currency: str | None = None) -> Tuple[float, str]:
    """Return (amount, currency) to compare for a stored payment operation.

    New rows carry ``amount_value`` and ``amount_currency``. Legacy rows only have
    the display string, so the numeric part and its suffix are parsed without
    converting anything.
    """
    configured = (currency or payment_currency()).upper()
    raw_value = operation.get("amount_value") if hasattr(operation, "get") else None
    raw_currency = (operation.get("amount_currency") if hasattr(operation, "get") else "") or ""
    raw_currency = str(raw_currency).strip().upper()
    if raw_value is not None:
        try:
            value = round(float(raw_value), 2)
            return value, raw_currency or configured
        except (TypeError, ValueError):
            pass
    display = str((operation.get("amount") if hasattr(operation, "get") else "") or "")
    digits = "".join(ch for ch in display if ch.isdigit() or ch == ".")
    try:
        value = round(float(digits), 2)
    except (TypeError, ValueError):
        value = 0.0
    suffix = display.strip().split()[-1].upper() if display.strip() else ""
    legacy_currency = suffix if len(suffix) == 3 and suffix.isalpha() else configured
    return value, legacy_currency
