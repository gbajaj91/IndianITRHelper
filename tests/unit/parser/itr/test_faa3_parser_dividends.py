from utils import date_utils
from models.purchase import Purchase, Price
from models.dividend import DividendEvent
from parser.itr import faa3_parser


def _mk_purchase(purchase_date, ticker="adbe", qty=1, price=100.0):
    return Purchase(
        date_utils.parse_named_mon(purchase_date),
        Price(price, "USD"),
        quantity=qty,
        ticker=ticker,
    )


def _mk_dividend(date_str, ticker, amount):
    return DividendEvent(date_utils.parse_named_mon(date_str), ticker, amount, "USD")


def test_dividend_income_replaces_hardcoded_zero():
    purchases = [_mk_purchase("15-MAR-2025", qty=2)]
    dividends = [_mk_dividend("30-JUN-2025", "adbe", 4.50)]

    fa_entries, _ = faa3_parser.parse_org_purchases(
        "adbe", "calendar", purchases, 2026, dividends
    )

    assert len(fa_entries) == 1
    assert fa_entries[0].dividend_income > 0


def test_dividend_outside_calendar_year_is_excluded():
    purchases = [_mk_purchase("15-MAR-2025", qty=2)]
    # Calendar period for AY 2026 is 1-Jan-2025 to 31-Dec-2025.
    dividends = [_mk_dividend("15-FEB-2026", "adbe", 4.50)]

    fa_entries, _ = faa3_parser.parse_org_purchases(
        "adbe", "calendar", purchases, 2026, dividends
    )

    assert fa_entries[0].dividend_income == 0


def test_dividend_income_only_set_on_first_entry_not_every_row():
    purchases = [
        _mk_purchase("15-MAR-2025", qty=2),
        _mk_purchase("15-JUN-2025", qty=3),
    ]
    dividends = [_mk_dividend("30-JUN-2025", "adbe", 4.50)]

    fa_entries, _ = faa3_parser.parse_org_purchases(
        "adbe", "calendar", purchases, 2026, dividends
    )

    assert len(fa_entries) == 2
    assert fa_entries[0].dividend_income > 0
    assert fa_entries[1].dividend_income == 0


def test_no_dividends_defaults_to_zero():
    purchases = [_mk_purchase("15-MAR-2025", qty=2)]
    fa_entries, _ = faa3_parser.parse_org_purchases("adbe", "calendar", purchases, 2026)
    assert fa_entries[0].dividend_income == 0


def test_dividend_only_ticker_still_gets_reported(tmp_path):
    # gs has dividend income but no purchase at all in this file - it must
    # not be silently dropped from fa_entries.csv.
    purchases = [_mk_purchase("15-MAR-2025", ticker="adbe", qty=2)]
    dividends = [_mk_dividend("30-JUN-2025", "gs", 4.50)]

    all_fa_entries = faa3_parser.parse(
        "calendar", purchases, 2026, str(tmp_path), dividends
    )

    by_ticker = {entry.purchase.ticker: entry for entry in all_fa_entries}
    assert "gs" in by_ticker
    assert by_ticker["gs"].dividend_income > 0
    assert by_ticker["gs"].purchase.quantity == 0
    assert "No purchase record" in by_ticker["gs"].comment


def test_dividend_only_ticker_outside_period_is_omitted(tmp_path):
    purchases = [_mk_purchase("15-MAR-2025", ticker="adbe", qty=2)]
    # Outside the AY 2026 calendar period (1-Jan-2025 to 31-Dec-2025).
    dividends = [_mk_dividend("15-FEB-2026", "gs", 4.50)]

    all_fa_entries = faa3_parser.parse(
        "calendar", purchases, 2026, str(tmp_path), dividends
    )

    tickers = {entry.purchase.ticker for entry in all_fa_entries}
    assert "gs" not in tickers
