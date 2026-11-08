"""Payment pricing and currency handling.

Display strings and verification values are deliberately separate:

* ``amount()`` builds the human-readable text shown by the Mini App.
* ``verification_amount()`` returns the numeric value actually charged.
* ``expected_values()`` reads a stored operation and returns what the bank/SMS
  matcher must compare, so a display currency can never be compared against a
  payment in another currency.

Prices are read in this priority order:
  1. Database overrides (set via admin panel)
  2. Environment variables (PAYMENT_PRICE_WEEKLY, etc.)
  3. Compiled-in defaults
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CURRENCY = "CUP"
DEFAULT_PRICES = {"weekly": 2500.0, "monthly": 7500.0, "annual": 15500.0}
PREMIUM_PLANS = tuple(DEFAULT_PRICES)
_PRICE_ENV = {
    "weekly": "PAYMENT_PRICE_WEEKLY",
    "monthly": "PAYMENT_PRICE_MONTHLY",
    "annual": "PAYMENT_PRICE_ANNUAL",
}

AD_PLAN_PREFIX = "ad_"
AD_PLAN_DAYS = {"ad_daily": 1, "ad_weekly": 7, "ad_monthly": 30, "ad_annual": 365}
AD_DEFAULT_PRICES = {"ad_daily": 750.0, "ad_weekly": 4500.0, "ad_monthly": 9000.0, "ad_annual": 17500.0}
_PRICE_ENV.update({
    "ad_daily": "AD_PRICE_DAILY", "ad_weekly": "AD_PRICE_WEEKLY",
    "ad_monthly": "AD_PRICE_MONTHLY", "ad_annual": "AD_PRICE_ANNUAL",
})
PREMIUM_PLAN_DAYS = {"weekly": 7, "monthly": 30, "annual": 365}
DEFAULT_PRICES_ALL = {**DEFAULT_PRICES, **AD_DEFAULT_PRICES}
VALID_PLANS = tuple(DEFAULT_PRICES_ALL)

# DB override hook — set by main.py at startup to avoid circular imports
_db_price_getter: Optional[Any] = None


def set_db_price_getter(fn) -> None:
    """Register the function that reads price overrides from the database."""
    global _db_price_getter
    _db_price_getter = fn


def is_ad_plan(plan: str) -> bool:
    return (plan or "").strip().lower() in AD_PLAN_DAYS


def plan_days(plan: str) -> int:
    plan = validate_plan(plan)
    return AD_PLAN_DAYS.get(plan) or PREMIUM_PLAN_DAYS[plan]


def validate_plan(plan: str) -> str:
    value = (plan or "").strip().lower()
    if value not in DEFAULT_PRICES_ALL:
        raise ValueError("Plan inválido")
    return value


def payment_currency() -> str:
    raw = (os.getenv("PAYMENT_CURRENCY") or DEFAULT_CURRENCY).strip().upper()
    if len(raw) != 3 or not raw.isalpha():
        logger.warning("PAYMENT_CURRENCY is invalid; falling back to %s", DEFAULT_CURRENCY)
        return DEFAULT_CURRENCY
    return raw


def payment_price(plan: str) -> float:
    """Price for a plan. Checks DB overrides first, then env vars, then defaults."""
    plan = validate_plan(plan)
    # 1) DB override
    if _db_price_getter is not None:
        try:
            db_val = _db_price_getter(plan)
            if db_val is not None:
                return float(db_val)
        except Exception:
            pass
    # 2) Env var
    raw = (os.getenv(_PRICE_ENV[plan]) or "").strip()
    if raw:
        try:
            value = round(float(raw.replace(",", ".")), 2)
            if value > 0:
                return value
        except (TypeError, ValueError):
            logger.warning("Invalid price configuration for %s; using the default", plan)
    # 3) Default
    return DEFAULT_PRICES_ALL[plan]


def format_amount(value: float, currency: str | None = None) -> str:
    currency = (currency or payment_currency()).strip().upper()
    number = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return f"{number} {currency}"


def amount(plan: str, lang: str | None = None) -> str:
    return format_amount(payment_price(plan), payment_currency())


def verification_amount(plan: str) -> float:
    return payment_price(plan)


def expected_values(operation: Mapping[str, Any], currency: str | None = None) -> Tuple[float, str]:
    configured = (currency or payment_currency()).strip().upper()

    def field(name: str, default: Any = None) -> Any:
        try:
            return operation[name]
        except (KeyError, IndexError, TypeError):
            getter = getattr(operation, "get", None)
            return getter(name, default) if callable(getter) else default

    raw_value = field("amount_value")
    raw_currency = field("amount_currency", "") or ""
    raw_currency = str(raw_currency).strip().upper()
    if raw_value is not None:
        try:
            value = round(float(raw_value), 2)
            return value, raw_currency or configured
        except (TypeError, ValueError):
            pass
    display = str(field("amount", "") or "")
    digits = "".join(ch for ch in display if ch.isdigit() or ch == ".")
    try:
        value = round(float(digits), 2)
    except (TypeError, ValueError):
        value = 0.0
    suffix = display.strip().split()[-1].upper() if display.strip() else ""
    legacy_currency = suffix if len(suffix) == 3 and suffix.isalpha() else configured
    return value, legacy_currency


def ad_pricing() -> dict:
    daily = payment_price("ad_daily")
    currency = payment_currency()
    out = {}
    for plan, days in AD_PLAN_DAYS.items():
        price = payment_price(plan)
        baseline = round(daily * days, 2)
        saved = max(0.0, round(baseline - price, 2))
        percent = int(round(saved / baseline * 100)) if baseline > 0 and saved > 0 else 0
        out[plan] = {
            "amount_value": price,
            "amount": format_amount(price, currency),
            "days": days,
            "per_day": format_amount(round(price / days, 2), currency),
            "baseline_value": baseline,
            "saved_value": saved,
            "saved": format_amount(saved, currency) if saved else "",
            "saved_percent": percent,
        }
    return out
