from utils import date_utils
from models.purchase import Purchase, Price
from parser.itr import faa3_parser


def _mk_purchase(purchase_date, ticker="adbe", qty=1, price=100.0):
    return Purchase(
        date_utils.parse_named_mon(purchase_date),
        Price(price, "USD"),
        quantity=qty,
        ticker=ticker,
    )


def test_purchase_acquired_after_period_end_does_not_crash():
    # Calendar period for AY 2026 is 1-Jan-2025 to 31-Dec-2025. A lot
    # acquired after that (e.g. a periodic ESPP purchase that already
    # happened, but past the reporting period) wasn't held at any point
    # during the period, so there's no peak/closing value to compute for it -
    # this must not crash get_peak_price_in_inr with an inverted date range.
    purchases = [
        _mk_purchase("15-MAR-2025", qty=2),
        _mk_purchase("30-JUN-2026", qty=3),
    ]

    fa_entries, detailed_entries = faa3_parser.parse_org_purchases(
        "adbe", "calendar", purchases, 2026
    )

    future_entry = next(
        entry
        for entry in detailed_entries
        if entry.purchase.date["time_in_millis"]
        == date_utils.parse_named_mon("30-JUN-2026")["time_in_millis"]
    )
    assert future_entry.peak_price == 0
    assert future_entry.purchase_price == 0
    assert "Acquired after end of period" in future_entry.comment

    # And it must not appear in fa_entries.csv's in-period rows either.
    assert all(
        entry.purchase.date["time_in_millis"]
        != date_utils.parse_named_mon("30-JUN-2026")["time_in_millis"]
        for entry in fa_entries
    )
