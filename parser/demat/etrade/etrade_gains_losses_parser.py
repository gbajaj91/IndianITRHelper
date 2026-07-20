"""Builds capital-gains-ready Purchase+Disposal objects for ETRADE by
combining two exports:

- BenefitHistory.xlsx is the source of truth for every trade (every RSU
  release, every ESPP purchase) - nothing is skipped, regardless of whether
  it was ever sold. This is what etrade_benefit_history_parser.py already
  parses.
- The Gains & Losses Expanded report (CSV or XLSX, Record Type "Sell" rows)
  is the source of truth for the actual sale: BenefitHistory doesn't record
  a per-sale price for ESPP, and doesn't track sales at all for RSU, so each
  BenefitHistory lot is matched to its Sell row(s) here (by ticker, plan
  type, and acquisition date) to get the real sale quantity/price/date.

Unlike ETRADE's own "Capital Gains Status" (Short/Long) column, which
reflects the US 12-month threshold, we don't use anything from the G&L file
for that determination - capital_gains_parser.py computes LTCG/STCG itself
from the dates, using India's 24-month threshold for unlisted/foreign
equity.

Mismatches between the two files are logged as warnings, not raised - this
is a best-effort reconciliation, not a hard gate:
- A BenefitHistory lot that's fully sold (ESPP) but has no matching Sell row
  can't have its gain computed, so it's excluded with a warning.
- A Sell row with no matching BenefitHistory lot is logged and ignored.
- If more than one Sell row would otherwise represent the same disposal
  (same lot, same sale date, same quantity - e.g. a duplicate export row),
  the higher price is used rather than double-counting the quantity.
"""

import typing as t

from utils.runtime_utils import warn_missing_module
from utils import logger, file_utils, date_utils

warn_missing_module("pandas")
import pandas as pd

DEBUG = False

from models.purchase import Purchase, Disposal
from parser.demat.etrade import etrade_benefit_history_parser

SELL_RECORD_TYPE = "Sell"
SUMMARY_RECORD_TYPE = "Summary"
RSU_PLAN_TYPE = "RS"
ESPP_PLAN_TYPE = "ESPP"

GlSellRowKey = t.Tuple[str, str, int]


def _parse_money(value) -> float:
    return float(str(value).replace("$", "").replace(",", "").strip())


def _read_gl_dataframe(gl_file_path: str) -> pd.DataFrame:
    if gl_file_path.lower().endswith(".xlsx"):
        warn_missing_module("openpyxl")
        return pd.read_excel(gl_file_path, engine="openpyxl")
    return pd.read_csv(gl_file_path, encoding="utf-8-sig")


def _read_sell_rows(gl_file_path: str) -> t.List[dict]:
    df = _read_gl_dataframe(gl_file_path)
    df = df[df["Record Type"] == SELL_RECORD_TYPE]
    return df.to_dict("records")


def extract_tickers(benefit_history_path: str, gl_file_path: str) -> t.Set[str]:
    """Distinct tickers referenced by either file, so callers can refresh
    historic share price/rate data for exactly the tickers needed."""
    tickers = etrade_benefit_history_parser.extract_tickers(benefit_history_path)
    tickers |= {row["Symbol"].strip().lower() for row in _read_sell_rows(gl_file_path)}
    return tickers


def _plan_type_for(holding_type: str) -> str:
    return RSU_PLAN_TYPE if holding_type == "RSU" else ESPP_PLAN_TYPE


def _index_sell_rows(rows: t.List[dict]) -> t.Dict[GlSellRowKey, t.List[dict]]:
    index: t.Dict[GlSellRowKey, t.List[dict]] = {}
    for row in rows:
        ticker = row["Symbol"].strip().lower()
        plan_type = row["Plan Type"]
        date_acquired_ms = date_utils.parse_mm_dd(row["Date Acquired"])["time_in_millis"]
        quantity = float(row["Quantity"])
        key = (ticker, plan_type, date_acquired_ms)
        index.setdefault(key, []).append(
            {
                "quantity": quantity,
                # Derive per-share price from the *total* proceeds, not the
                # rounded "Per Share" column, to avoid drifting a few cents
                # from ETRADE's own reported total.
                "price_per_share": _parse_money(row["Total Proceeds"]) / quantity,
                "date_sold": date_utils.parse_mm_dd(row["Date Sold"]),
            }
        )
    return index


def _dedupe_matches(matches: t.List[dict]) -> t.List[dict]:
    """Collapses Sell rows that represent the exact same disposal (same sale
    date and quantity - e.g. a duplicate export row) into one, keeping the
    higher price rather than double-counting the quantity."""
    by_date_and_qty: t.Dict[t.Tuple[int, float], dict] = {}
    for match in matches:
        dedupe_key = (match["date_sold"]["time_in_millis"], match["quantity"])
        existing = by_date_and_qty.get(dedupe_key)
        if existing is None or match["price_per_share"] > existing["price_per_share"]:
            by_date_and_qty[dedupe_key] = match
    return list(by_date_and_qty.values())


def _attach_disposals(
    purchases: t.List[Purchase], gl_index: t.Dict[GlSellRowKey, t.List[dict]]
) -> None:
    """Matches each BenefitHistory lot to its Sell row(s) in the G&L Expanded
    index (by ticker, plan type, acquisition date), filling in Purchase.
    disposals. Mutates gl_index, popping every key it consumes, so any keys
    left over afterwards are Sell rows that never matched a BenefitHistory
    lot - logged as a mismatch by the caller."""
    for purchase in purchases:
        key = (
            purchase.ticker,
            _plan_type_for(purchase.holding_type),
            purchase.date["time_in_millis"],
        )
        matches = gl_index.pop(key, None)
        if not matches:
            if purchase.holding_type == "ESPP" and purchase.closing_quantity == 0:
                logger.log(
                    f"Cross-check: {purchase.ticker} ESPP lot acquired "
                    f"{purchase.date['disp_time']} is fully sold per "
                    "BenefitHistory.xlsx, but no matching Sell row was found in "
                    "the Gains & Losses Expanded file - its gain can't be "
                    "computed, so it's excluded from the capital gains report."
                )
            continue
        for match in _dedupe_matches(matches):
            purchase.disposals.append(
                Disposal(match["date_sold"], match["quantity"], match["price_per_share"])
            )


def _log_unmatched_sell_rows(gl_index: t.Dict[GlSellRowKey, t.List[dict]]) -> None:
    for (ticker, plan_type, date_acquired_ms), leftover in gl_index.items():
        sold_qty = sum(match["quantity"] for match in leftover)
        logger.log(
            f"Cross-check: the Gains & Losses Expanded file shows {sold_qty} "
            f"{ticker} {plan_type} share(s) sold (acquired "
            f"{date_utils.display_time(date_acquired_ms)}), but no matching lot "
            "was found in BenefitHistory.xlsx."
        )


def _cross_check_summary_total(gl_file_path: str, sell_rows: t.List[dict]) -> None:
    """Sanity-checks our own parsing of the G&L file: its own "Summary" row
    total should match the sum of the individual Sell rows' Adjusted
    Gain/Loss. A full account export should reconcile exactly; an excerpt
    (e.g. just a few rows) won't, which is expected and fine."""
    df = _read_gl_dataframe(gl_file_path)
    summary_rows = df[df["Record Type"] == SUMMARY_RECORD_TYPE]
    if summary_rows.empty:
        return
    summary_total = _parse_money(summary_rows.iloc[0]["Adjusted Gain/Loss"])
    computed_total = sum(_parse_money(row["Adjusted Gain/Loss"]) for row in sell_rows)
    if abs(summary_total - computed_total) > 0.01:
        logger.log(
            f"Cross-check: sum of Sell rows' Adjusted Gain/Loss ({computed_total:.2f}) "
            f"doesn't match the file's own Summary row ({summary_total:.2f}) - "
            "some Sell rows may not have been parsed correctly, or this is only "
            "a partial export of the account's history."
        )


def parse(
    benefit_history_path: str,
    gl_file_path: str,
    output_folder_abs_path: str,
    time_bounds: t.Optional[date_utils.DateBounds],
) -> t.List[Purchase]:
    logger.DEBUG = DEBUG
    purchases = etrade_benefit_history_parser.parse(
        benefit_history_path, output_folder_abs_path, time_bounds
    )

    sell_rows = _read_sell_rows(gl_file_path)
    _cross_check_summary_total(gl_file_path, sell_rows)

    gl_index = _index_sell_rows(sell_rows)
    _attach_disposals(purchases, gl_index)
    _log_unmatched_sell_rows(gl_index)

    purchases.sort(key=lambda purchase: purchase.date["time_in_millis"])
    file_utils.write_to_file(
        output_folder_abs_path,
        "purchases.json",
        purchases,
        True,
    )
    return purchases
