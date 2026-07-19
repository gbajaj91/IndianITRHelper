import csv

from utils import date_utils
from models.dividend import DividendEvent
from parser.itr import dividend_income_parser


def _mk(date_str, ticker, amount, currency="USD"):
    return DividendEvent(date_utils.parse_named_mon(date_str), ticker, amount, currency)


def _read_rows(output_folder):
    with open(f"{output_folder}/dividend_income.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_aggregates_gross_and_tax_per_ticker(tmp_path):
    dividends = [
        _mk("30-JUN-2025", "gs", 4.50),
        _mk("30-SEP-2025", "gs", 4.50),
    ]
    tax_withheld = [
        _mk("30-JUN-2025", "gs", 1.13),
        _mk("30-SEP-2025", "gs", 1.13),
    ]
    dividend_income_parser.parse(dividends, tax_withheld, 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["Ticker"] == "gs"
    assert float(rows[0]["Gross dividend (native)"]) == 9.0
    assert float(rows[0]["Tax withheld (native)"]) == 2.26


def test_dividend_and_tax_not_required_to_share_a_date(tmp_path):
    # Tax posted a day after the dividend - still attributed to the same
    # ticker's totals since matching is by ticker only, not date.
    dividends = [_mk("30-JUN-2025", "v", 0.67)]
    tax_withheld = [_mk("01-JUL-2025", "v", 0.17)]
    dividend_income_parser.parse(dividends, tax_withheld, 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert float(rows[0]["Gross dividend (native)"]) == 0.67
    assert float(rows[0]["Tax withheld (native)"]) == 0.17


def test_only_events_within_fy_are_included(tmp_path):
    # FY for AY 2026 is 1-Apr-2025 to 31-Mar-2026.
    dividends = [
        _mk("15-FEB-2025", "qqq", 3.18),  # before FY start - excluded
        _mk("31-DEC-2025", "qqq", 3.18),  # within FY - included
    ]
    dividend_income_parser.parse(dividends, [], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert float(rows[0]["Gross dividend (native)"]) == 3.18


def test_single_payment_rate_matches_the_actual_conversion_rate(tmp_path):
    dividend = _mk("30-JUN-2025", "gs", 4.50)
    dividend_income_parser.parse([dividend], [], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    expected_rate = dividend_income_parser._to_inr(dividend) / dividend.amount
    assert abs(float(rows[0]["USD conversion rate"]) - expected_rate) < 0.0001


def test_multiple_payments_produce_a_weighted_average_rate(tmp_path):
    # Two payments on different dates likely have different conversion rates
    # - the reported rate is the effective one that reproduces the INR total
    # from the native total (gross_inr / gross_native), not any single
    # payment's own rate.
    dividends = [
        _mk("30-JUN-2025", "gs", 4.50),
        _mk("31-DEC-2025", "gs", 4.50),
    ]
    dividend_income_parser.parse(dividends, [], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    gross_native = float(rows[0]["Gross dividend (native)"])
    gross_inr = float(rows[0]["Gross dividend (INR)"])
    reported_rate = float(rows[0]["USD conversion rate"])
    assert abs(gross_native * reported_rate - gross_inr) < 1


def test_tax_withheld_inr_still_uses_its_own_actual_rate(tmp_path):
    # There's no separate displayed rate column for tax, but its INR value
    # must still be computed using its own event's actual conversion rate,
    # not the dividend's rate.
    tax = _mk("30-JUN-2025", "gs", 1.13)
    dividend_income_parser.parse([], [tax], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    expected_tax_inr = round(dividend_income_parser._to_inr(tax))
    assert float(rows[0]["Tax withheld (INR)"]) == expected_tax_inr


def test_no_events_produces_empty_report(tmp_path):
    dividend_income_parser.parse([], [], 2026, str(tmp_path))
    assert _read_rows(tmp_path) == []
