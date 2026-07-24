import operator
import itertools
import typing as t
from collections import deque

from utils.runtime_utils import warn_missing_module
from utils import logger, file_utils, date_utils, share_data_utils, ticker_mapping

warn_missing_module("pandas")
import pandas as pd

DEBUG = False

from models.purchase import Purchase, Price, Disposal
from models.dividend import DividendEvent

BUY_ACTION = "Buy"
SELL_ACTION = "Sell"
# Shares deposited into the account directly from an equity award plan (e.g.
# RSU vesting) - no Price column is given, so cost basis is derived from the
# market closing price on the deposit date, same as ETRADE RSU releases.
STOCK_PLAN_ACTIVITY_ACTION = "Stock Plan Activity"
# Dividends automatically used to buy more (usually fractional) shares - has
# a real Price column, same as a regular Buy.
REINVEST_ACTION = "Reinvest Shares"
ACQUISITION_ACTIONS = (BUY_ACTION, STOCK_PLAN_ACTIVITY_ACTION, REINVEST_ACTION)
# Matches "Qualified Div", "Cash Dividend", "Special Dividend", "Non-Qualified
# Div", etc. - Schwab's dividend-type Actions all contain "Div".
DIVIDEND_ACTION_MARKER = "Div"
# Tax withheld for non-resident-alien accounts. Also appears against interest
# (blank Symbol) - only rows with a Symbol are dividend tax withholding.
TAX_ACTION = "NRA Tax Adj"
# Fractional shares (dividend reinvestment, etc.) accumulate floating-point
# drift across repeated subtraction - a lot considered "fully consumed" can
# be left with e.g. 1e-16 "remaining" instead of exactly 0. Comparisons that
# decide whether a lot is exhausted / a sell is fully matched use this
# tolerance instead of comparing to 0 directly.
QUANTITY_EPSILON = 1e-6


class _Lot:
    def __init__(
        self, date: date_utils.DateObj, price: float, quantity: float, holding_type: str
    ):
        self.date = date
        self.price = price
        self.original_quantity = quantity
        self.holding_type = holding_type
        # Remaining quantity, drawn down as later sells consume this lot via FIFO.
        self.remaining_quantity = quantity
        # Sell events that consumed part (or all) of this lot, in order.
        self.disposals: t.List[Disposal] = []


def _parse_price(value: str) -> float:
    return float(str(value).replace("$", "").replace(",", "").strip())


def _parse_amount(value: str) -> float:
    """Parses the "Amount" column, which unlike "Price" can be negative,
    written in parens e.g. "($1.13)". Returns the signed value."""
    text = str(value).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        return -float(text[1:-1])
    return float(text)


def _read_transactions(input_file_abs_path: str) -> t.List[dict]:
    df = pd.read_csv(input_file_abs_path)
    df = df[df["Action"].isin([*ACQUISITION_ACTIONS, SELL_ACTION])]
    rows = df.to_dict("records")
    rows.sort(key=lambda row: date_utils.parse_m_d_yy(row["Date"])["time_in_millis"])
    return rows


def _read_dividend_rows(input_file_abs_path: str) -> t.List[dict]:
    df = pd.read_csv(input_file_abs_path)
    is_dividend = df["Action"].str.contains(DIVIDEND_ACTION_MARKER, na=False)
    # Symbol is blank for NRA Tax Adj against interest - only tax rows tied to
    # an actual ticker are dividend tax withholding.
    is_dividend_tax = (df["Action"] == TAX_ACTION) & df["Symbol"].notna()
    df = df[is_dividend | is_dividend_tax]
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
        if row["Action"] in ACQUISITION_ACTIONS:
            if row["Action"] == STOCK_PLAN_ACTIVITY_ACTION:
                # No Price column for these - use the market closing price on
                # the deposit date, same as ETRADE RSU vest-date FMV.
                price = share_data_utils.get_fmv(ticker, date_obj["time_in_millis"])
                holding_type = "RSU"
            else:
                price = _parse_price(row["Price"])
                holding_type = "Trade"
            lot = _Lot(date_obj, price, quantity, holding_type)
            lots.append(lot)
            all_lots.setdefault(ticker, []).append(lot)
            continue

        sale_price = _parse_price(row["Price"])
        remaining_to_sell = quantity
        while remaining_to_sell > QUANTITY_EPSILON:
            assert lots, (
                f"More shares sold than bought for '{ticker}' as of {date_obj['disp_time']} - "
                + "your export may not cover the full transaction history for this ticker"
            )
            oldest = lots[0]
            consumed = min(oldest.remaining_quantity, remaining_to_sell)
            oldest.remaining_quantity -= consumed
            oldest.disposals.append(Disposal(date_obj, consumed, sale_price))
            remaining_to_sell -= consumed
            if oldest.remaining_quantity <= QUANTITY_EPSILON:
                # Clamp away any floating-point residue (e.g. 7.9e-16) left
                # over from repeated fractional-share subtraction, rather
                # than reporting a lot as having a dust-sized closing balance.
                oldest.remaining_quantity = 0.0
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
                    holding_type=lot.holding_type,
                )
            )
    return purchases


def extract_tickers(input_file_abs_path: str) -> t.Set[str]:
    """Distinct tickers referenced by Buy/Sell/dividend/tax rows, so callers
    can refresh historic share price/rate data for exactly the tickers this
    file needs."""
    rows = _read_transactions(input_file_abs_path)
    dividend_rows = _read_dividend_rows(input_file_abs_path)
    return {row["Symbol"].strip().lower() for row in rows} | {
        row["Symbol"].strip().lower() for row in dividend_rows
    }


def parse_dividends(
    input_file_abs_path: str,
) -> t.Tuple[t.List[DividendEvent], t.List[DividendEvent]]:
    """Returns (dividends, tax_withheld) - both are per-ticker cash events,
    not tied to any specific lot. Matched to each other only by ticker (not
    date), since a tax withholding posting isn't guaranteed to land on the
    same date as the dividend it applies to."""
    rows = _read_dividend_rows(input_file_abs_path)
    dividends: t.List[DividendEvent] = []
    tax_withheld: t.List[DividendEvent] = []
    for row in rows:
        ticker = row["Symbol"].strip().lower()
        date_obj = date_utils.parse_m_d_yy(row["Date"])
        amount = _parse_amount(row["Amount"])
        currency = ticker_mapping.get_currency(ticker)
        event = DividendEvent(date_obj, ticker, abs(amount), currency)
        if row["Action"] == TAX_ACTION:
            tax_withheld.append(event)
        else:
            dividends.append(event)
    return dividends, tax_withheld


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
