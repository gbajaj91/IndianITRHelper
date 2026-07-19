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


def test_no_events_produces_empty_report(tmp_path):
    dividend_income_parser.parse([], [], 2026, str(tmp_path))
    assert _read_rows(tmp_path) == []
