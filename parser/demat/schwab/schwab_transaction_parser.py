import operator
import itertools
import typing as t
from collections import deque

from utils.runtime_utils import warn_missing_module
from utils import logger, file_utils, date_utils, ticker_mapping

warn_missing_module("pandas")
import pandas as pd

DEBUG = False

from models.purchase import Purchase, Price, Disposal

BUY_ACTION = "Buy"
SELL_ACTION = "Sell"


class _Lot:
    def __init__(self, date: date_utils.DateObj, price: float, quantity: float):
        self.date = date
        self.price = price
        self.original_quantity = quantity
        # Remaining quantity, drawn down as later sells consume this lot via FIFO.
        self.remaining_quantity = quantity
        # Sell events that consumed part (or all) of this lot, in order.
        self.disposals: t.List[Disposal] = []


def _parse_price(value: str) -> float:
    return float(str(value).replace("$", "").replace(",", "").strip())


def _read_transactions(input_file_abs_path: str) -> t.List[dict]:
    df = pd.read_csv(input_file_abs_path)
    df = df[df["Action"].isin([BUY_ACTION, SELL_ACTION])]
    rows = df.to_dict("records")
    rows.sort(key=lambda row: date_utils.parse_m_d_yy(row["Date"])["time_in_millis"])
    return rows


def _validate_ticker_mapping(tickers: t.Set[str]):
    errors = []
    for ticker in sorted(tickers):
        try:
            ticker_mapping.get_org_info(ticker)
            ticker_mapping.get_currency(ticker)
        except Exception as err:
            errors.append(f"{ticker}: {err}")
    assert not errors, "Could not resolve ticker info for:\n" + "\n".join(errors)


def _net_fifo(
    rows: t.List[dict], time_bounds: t.Optional[date_utils.DateBounds]
) -> t.List[Purchase]:
    # `open_lots` only holds lots still available to absorb further sells (FIFO
    # queue, exhausted lots popped off). `all_lots` keeps every lot ever bought
    # for a ticker, including fully-sold ones, so a ticker that nets to zero
    # still gets reported (with closing_quantity=0) instead of disappearing.
    open_lots: t.Dict[str, t.Deque[_Lot]] = {}
    all_lots: t.Dict[str, t.List[_Lot]] = {}
    for row in rows:
        ticker = row["Symbol"].strip().lower()
        date_obj = date_utils.parse_m_d_yy(row["Date"])
        if not date_utils.is_in_bounds(date_obj["time_in_millis"], time_bounds):
            continue

        quantity = float(row["Quantity"])
        lots = open_lots.setdefault(ticker, deque())
        if row["Action"] == BUY_ACTION:
            lot = _Lot(date_obj, _parse_price(row["Price"]), quantity)
            lots.append(lot)
            all_lots.setdefault(ticker, []).append(lot)
            continue

        sale_price = _parse_price(row["Price"])
        remaining_to_sell = quantity
        while remaining_to_sell > 0:
            assert lots, (
                f"More shares sold than bought for '{ticker}' as of {date_obj['disp_time']} - "
                + "your export may not cover the full transaction history for this ticker"
            )
            oldest = lots[0]
            consumed = min(oldest.remaining_quantity, remaining_to_sell)
            oldest.remaining_quantity -= consumed
            oldest.disposals.append(Disposal(date_obj, consumed, sale_price))
            remaining_to_sell -= consumed
            if oldest.remaining_quantity <= 0:
                lots.popleft()

    purchases: t.List[Purchase] = []
    for ticker, lots in all_lots.items():
        for lot in lots:
            purchases.append(
                Purchase(
                    date=lot.date,
                    purchase_fmv=Price(lot.price, ticker_mapping.get_currency(ticker)),
                    quantity=lot.original_quantity,
                    ticker=ticker,
                    closing_quantity=lot.remaining_quantity,
                    disposals=lot.disposals,
                    holding_type="Trade",
                )
            )
    return purchases


def extract_tickers(input_file_abs_path: str) -> t.Set[str]:
    """Distinct tickers referenced by Buy/Sell rows, so callers can refresh
    historic share price/rate data for exactly the tickers this file needs."""
    rows = _read_transactions(input_file_abs_path)
    return {row["Symbol"].strip().lower() for row in rows}


def parse(
    input_file_abs_path: str,
    output_folder_abs_path: str,
    time_bounds: t.Optional[date_utils.DateBounds],
) -> t.List[Purchase]:
    logger.DEBUG = DEBUG
    rows = _read_transactions(input_file_abs_path)

    tickers = {row["Symbol"].strip().lower() for row in rows}
    _validate_ticker_mapping(tickers)

    purchases = _net_fifo(rows, time_bounds)
    purchases.sort(key=lambda purchase: purchase.date["time_in_millis"])

    file_utils.write_to_file(
        output_folder_abs_path,
        "purchases.json",
        purchases,
        True,
    )

    ticker_shares_map: t.Dict[str, list[Purchase]] = {}
    for ticker, ticker_purchases in itertools.groupby(
        sorted(purchases, key=operator.attrgetter("ticker")),
        key=operator.attrgetter("ticker"),
    ):
        ticker_shares_map[ticker] = list(ticker_purchases)
        print(
            f"{ticker}: Total shares currently held "
            + f"= {sum(map(lambda x:x.closing_quantity, ticker_shares_map[ticker]))}"
        )
    return purchases
