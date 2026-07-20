import csv

from utils import date_utils, ticker_mapping
from models.purchase import Purchase, Price, Disposal
from parser.itr import capital_gains_parser


def _mk_purchase(purchase_date, ticker="adbe", price=100.0, disposals=None):
    return Purchase(
        date_utils.parse_named_mon(purchase_date),
        Price(price, "USD"),
        quantity=sum(d.quantity for d in disposals) if disposals else 0,
        ticker=ticker,
        disposals=disposals or [],
    )


def _mk_disposal(sale_date, quantity, price):
    return Disposal(date_utils.parse_named_mon(sale_date), quantity, price)


def _read_all_rows(output_folder):
    with open(f"{output_folder}/capital_gains.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_rows(output_folder):
    """Only genuine data rows - excludes the "=== STCG ===" style section
    markers and "STCG Total" subtotal rows."""
    return [
        row
        for row in _read_all_rows(output_folder)
        if row["Category"] in ("STCG", "LTCG")
    ]


def test_ltcg_when_held_more_than_24_months(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    purchase = _mk_purchase(
        "15-JAN-2023",
        price=100.0,
        disposals=[_mk_disposal("20-JAN-2026", 5, 150.0)],
    )
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["Category"] == "LTCG"
    assert int(rows[0]["Holding period (months)"]) == 36
    assert float(rows[0]["Gain/Loss (native)"]) == 250.0  # 5 * (150-100)


def test_stcg_when_held_24_months_or_less(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    purchase = _mk_purchase(
        "15-JUN-2025",
        price=100.0,
        disposals=[_mk_disposal("20-JAN-2026", 5, 150.0)],
    )
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["Category"] == "STCG"
    assert int(rows[0]["Holding period (months)"]) == 7


def test_sale_outside_fy_is_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    # FY for AY 2026 is 1-Apr-2025 to 31-Mar-2026; this sale is before it starts.
    purchase = _mk_purchase(
        "15-JAN-2023",
        price=100.0,
        disposals=[_mk_disposal("15-FEB-2025", 5, 150.0)],
    )
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 0


def test_only_disposals_within_fy_are_included(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    purchase = _mk_purchase(
        "15-JAN-2023",
        price=100.0,
        disposals=[
            _mk_disposal("15-FEB-2025", 2, 150.0),  # before FY start - excluded
            _mk_disposal("20-JAN-2026", 3, 160.0),  # within FY - included
        ],
    )
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["Sale date"] == "2026-01-20"
    assert float(rows[0]["Quantity sold"]) == 3.0


def test_stcg_and_ltcg_are_split_into_separate_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    stcg_purchase = _mk_purchase(
        "15-JUN-2025",
        ticker="aapl",
        price=100.0,
        disposals=[_mk_disposal("20-JAN-2026", 2, 150.0)],
    )
    ltcg_purchase = _mk_purchase(
        "15-JAN-2023",
        ticker="adbe",
        price=100.0,
        disposals=[_mk_disposal("20-JAN-2026", 5, 150.0)],
    )
    capital_gains_parser.parse([stcg_purchase, ltcg_purchase], 2026, str(tmp_path))

    all_rows = _read_all_rows(tmp_path)
    tickers_in_order = [row["Ticker"] for row in all_rows]

    stcg_marker_idx = tickers_in_order.index("=== STCG ===")
    stcg_total_idx = tickers_in_order.index("STCG Total")
    ltcg_marker_idx = tickers_in_order.index("=== LTCG ===")
    ltcg_total_idx = tickers_in_order.index("LTCG Total")

    # STCG section (marker, data, total) comes entirely before LTCG's.
    assert stcg_marker_idx < stcg_total_idx < ltcg_marker_idx < ltcg_total_idx
    assert tickers_in_order[stcg_marker_idx + 1] == "aapl"
    assert tickers_in_order[ltcg_marker_idx + 1] == "adbe"

    stcg_total_row = all_rows[stcg_total_idx]
    assert float(stcg_total_row["Gain/Loss (native)"]) == 100.0  # 2 * (150-100)
    ltcg_total_row = all_rows[ltcg_total_idx]
    assert float(ltcg_total_row["Gain/Loss (native)"]) == 250.0  # 5 * (150-100)


def test_total_purchase_and_sale_values_reconcile_to_the_gain(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    purchase = _mk_purchase(
        "15-JUN-2025",
        price=100.0,
        disposals=[_mk_disposal("20-JAN-2026", 5, 150.0)],
    )
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    row = rows[0]
    assert float(row["Total purchase value (native)"]) == 500.0  # 5 * 100
    assert float(row["Total sale value (native)"]) == 750.0  # 5 * 150

    native_gain = float(row["Total sale value (native)"]) - float(
        row["Total purchase value (native)"]
    )
    assert native_gain == float(row["Gain/Loss (native)"])

    inr_gain = round(
        float(row["Total sale value (INR)"]) - float(row["Total purchase value (INR)"])
    )
    assert inr_gain == round(float(row["Gain/Loss (INR)"]))


def test_espp_without_disposal_detail_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(ticker_mapping, "get_currency", lambda ticker: "USD")
    purchase = Purchase(
        date_utils.parse_named_mon("15-JAN-2023"),
        Price(100.0, "USD"),
        quantity=5,
        ticker="adbe",
        holding_type="ESPP",
        closing_quantity=0,
    )
    purchase.last_sale_date_in_millis = date_utils.parse_named_mon("20-JAN-2026")[
        "time_in_millis"
    ]
    capital_gains_parser.parse([purchase], 2026, str(tmp_path))

    rows = _read_rows(tmp_path)
    assert len(rows) == 0
