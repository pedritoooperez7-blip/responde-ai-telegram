"""Offline tests for payment amount/currency separation (no web framework)."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import payments


class AmountFormattingTests(unittest.TestCase):
    def test_defaults_are_cup_for_every_language(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.amount("weekly", "es"), "2500 CUP")
            self.assertEqual(payments.amount("annual", "es"), "15500 CUP")
            # English text must not switch the currency used for verification.
            self.assertEqual(payments.amount("weekly", "en"), "2500 CUP")
            self.assertEqual(payments.amount("annual", "en"), "15500 CUP")

    def test_configured_currency_and_prices_are_used(self):
        env = {"PAYMENT_CURRENCY": "usd", "PAYMENT_PRICE_WEEKLY": "9,99", "PAYMENT_PRICE_ANNUAL": "29.99"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(payments.payment_currency(), "USD")
            self.assertEqual(payments.verification_amount("weekly"), 9.99)
            self.assertEqual(payments.amount("weekly", "es"), "9.99 USD")
            self.assertEqual(payments.amount("annual", "en"), "29.99 USD")

    def test_invalid_configuration_falls_back_to_defaults(self):
        env = {"PAYMENT_CURRENCY": "EUROS", "PAYMENT_PRICE_WEEKLY": "abc", "PAYMENT_PRICE_ANNUAL": "-5"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(payments.payment_currency(), "CUP")
            self.assertEqual(payments.payment_price("weekly"), 2500.0)
            self.assertEqual(payments.payment_price("annual"), 15500.0)

    def test_unknown_plan_is_rejected(self):
        with self.assertRaises(ValueError):
            payments.payment_price("foobar")
        with self.assertRaises(ValueError):
            payments.verification_amount("not-a-plan")


class StoredOperationTests(unittest.TestCase):
    def test_new_rows_use_numeric_value_and_currency(self):
        row = {"amount": "2500 CUP", "amount_value": 2500.0, "amount_currency": "CUP"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.expected_values(row), (2500.0, "CUP"))

    def test_legacy_usd_row_is_detected_as_usd(self):
        row = {"amount": "8.99 USD", "amount_value": None, "amount_currency": None}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.expected_values(row), (8.99, "USD"))

    def test_legacy_cup_row_is_detected_as_cup(self):
        row = {"amount": "2500 CUP", "amount_value": None, "amount_currency": None}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.expected_values(row), (2500.0, "CUP"))

    def test_missing_amount_fields_use_configured_defaults(self):
        row = {"amount": None, "amount_value": None, "amount_currency": None}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.expected_values(row), (2500.0, "CUP"))
