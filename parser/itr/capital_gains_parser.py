"""Schedule CG style capital gains report for a financial year (1-Apr to
31-Mar), split into LTCG/STCG.

This is a separate report from Schedule FA (faa3_parser.py) - Indian capital
gains are always reported on a financial-year basis regardless of whichever
--calendar-mode was used for Schedule FA, so the FY boundary here is always
computed as "financial", not read from --calendar-mode.

Only sells (disposals) that fall within the target FY are included - lots
that were merely held (not sold) during the FY are out of scope for this
report. Unlisted foreign equity (every ticker this tool deals with) qualifies
as LTCG when held for more than 24 months; otherwise it's STCG.

Limitation: only sources that track per-disposal quantity/price (currently
just Schwab, via Purchase.disposals) can appear here. ESPP purchases only
record that they were "fully sold as of this date" (Purchase.
last_sale_date_in_millis), not the quantity/price of each sale, so they
can't be included yet - they're skipped with a logged warning.
"""

from datetime import datetime
import typing as t

from utils import date_utils, file_utils, logger, ticker_mapping
from utils.rates import rbi_rates_utils
from models.purchase import Purchase

LTCG_THRESHOLD_MONTHS = 24

LTCG = "LTCG"
STCG = "STCG"


def _months_held(purchase_date_in_millis: int, disposal_date_in_millis: int) -> int:
    purchase_dt = datetime.utcfromtimestamp(purchase_date_in_millis / 1000)
    disposal_dt = datetime.utcfromtimestamp(disposal_date_in_millis / 1000)
    months = (disposal_dt.year - purchase_dt.year) * 12 + (
        disposal_dt.month - purchase_dt.month
    )
    if disposal_dt.day < purchase_dt.day:
        months -= 1
    return months


CAPITAL_GAINS_HEADER = [
    "Ticker",
    "Holding type",
    "Acquisition date",
    "Sale date",
    "Quantity sold",
    "Holding period (months)",
    "Category",
    "Purchase price (native)",
    "Sale price (native)",
    "Currency",
    "Purchase RBI rate",
    "Sale RBI rate",
    "Gain/Loss (native)",
    "Gain/Loss (INR)",
]


def _rows_for_purchase(
    purchase: Purchase, start_time_in_ms: int, end_time_in_ms: int
) -> t.List[tuple]:
    if not purchase.disposals:
        if purchase.last_sale_date_in_millis is not None:
            logger.log(
                f"Skipping {purchase.ticker} lot from {purchase.date['disp_time']} - "
                "sold, but per-sale quantity/price isn't tracked for this source "
                "(e.g. ESPP), so it can't be included in the capital gains report yet."
            )
        return []

    currency_code = ticker_mapping.get_currency(purchase.ticker)
    rows = []
    for disposal in purchase.disposals:
        if not (
            start_time_in_ms
            <= disposal.date["time_in_millis"]
            <= end_time_in_ms
        ):
            continue

        months_held = _months_held(
            purchase.date["time_in_millis"], disposal.date["time_in_millis"]
        )
        category = LTCG if months_held > LTCG_THRESHOLD_MONTHS else STCG

        purchase_rate = rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
            currency_code, purchase.date["time_in_millis"]
        )
        sale_rate = rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
            currency_code, disposal.date["time_in_millis"]
        )
        cost_basis_native = disposal.quantity * purchase.purchase_fmv.price
        proceeds_native = disposal.quantity * disposal.price
        gain_native = proceeds_native - cost_basis_native
        gain_inr = (proceeds_native * sale_rate) - (cost_basis_native * purchase_rate)

        rows.append(
            (
                purchase.ticker,
                purchase.holding_type,
                date_utils.format_time(purchase.date["time_in_millis"], "%Y-%m-%d"),
                date_utils.format_time(disposal.date["time_in_millis"], "%Y-%m-%d"),
                disposal.quantity,
                months_held,
                category,
                purchase.purchase_fmv.price,
                disposal.price,
                currency_code,
                purchase_rate,
                sale_rate,
                round(gain_native, 2),
                round(gain_inr),
            )
        )
    return rows


def _section(label: str, rows: t.List[tuple]) -> t.List[tuple]:
    """A labeled block: a marker row, the rows themselves, and a totals row -
    so STCG and LTCG read as two clearly separated sections in the CSV."""
    filler = ("",) * (len(CAPITAL_GAINS_HEADER) - 1)
    if not rows:
        return [(f"=== {label} (none) ===",) + filler]
    total_native = sum(row[-2] for row in rows)
    total_inr = sum(row[-1] for row in rows)
    return (
        [(f"=== {label} ===",) + filler]
        + rows
        + [(f"{label} Total",) + ("",) * (len(CAPITAL_GAINS_HEADER) - 3) + (round(total_native, 2), round(total_inr))]
    )


def parse(
    purchases: t.List[Purchase],
    assessment_year: int,
    output_folder_abs_path: str,
) -> str:
    start_time_in_ms, end_time_in_ms = date_utils.calendar_range(
        "financial", assessment_year
    )
    all_rows: t.List[tuple] = []
    for purchase in purchases:
        all_rows.extend(_rows_for_purchase(purchase, start_time_in_ms, end_time_in_ms))

    category_index = CAPITAL_GAINS_HEADER.index("Category")
    stcg_rows = [row for row in all_rows if row[category_index] == STCG]
    ltcg_rows = [row for row in all_rows if row[category_index] == LTCG]

    rows = _section(STCG, stcg_rows) + _section(LTCG, ltcg_rows)

    return file_utils.write_csv_to_file(
        output_folder_abs_path,
        "capital_gains.csv",
        CAPITAL_GAINS_HEADER,
        rows,
        True,
        print_path_to_console=True,
    )
