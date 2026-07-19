"""Dividend income report for a financial year (1-Apr to 31-Mar), for
Schedule OS / foreign tax credit (Schedule TR/FSI) purposes.

Like capital_gains_parser.py, this is always financial-year scoped regardless
of --calendar-mode, since that flag only governs the Schedule FA report.

Dividend and tax-withholding events aren't matched to each other by date -
a tax withholding posting isn't guaranteed to land on the same date as the
dividend it applies to (see schwab_transaction_parser.parse_dividends) - so
this report aggregates both per ticker over the whole financial year rather
than trying to pair up individual payments.
"""

import typing as t

from utils import date_utils, file_utils
from utils.rates import rbi_rates_utils
from models.dividend import DividendEvent

DIVIDEND_INCOME_HEADER = [
    "Ticker",
    "Currency",
    "Gross dividend (native)",
    "Tax withheld (native)",
    "USD conversion rate",
    "Gross dividend (INR)",
    "Tax withheld (INR)",
    "Net dividend (INR)",
]


def _in_period(event: DividendEvent, start_time_in_ms: int, end_time_in_ms: int) -> bool:
    return start_time_in_ms <= event.date["time_in_millis"] <= end_time_in_ms


def _to_inr(event: DividendEvent) -> float:
    return event.amount * rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
        event.currency, event.date["time_in_millis"]
    )


def parse(
    dividends: t.List[DividendEvent],
    tax_withheld: t.List[DividendEvent],
    assessment_year: int,
    output_folder_abs_path: str,
) -> str:
    start_time_in_ms, end_time_in_ms = date_utils.calendar_range(
        "financial", assessment_year
    )
    dividends_in_period = [
        d for d in dividends if _in_period(d, start_time_in_ms, end_time_in_ms)
    ]
    tax_in_period = [
        t_ for t_ in tax_withheld if _in_period(t_, start_time_in_ms, end_time_in_ms)
    ]

    tickers = sorted(
        {d.ticker for d in dividends_in_period} | {t_.ticker for t_ in tax_in_period}
    )

    rows = []
    for ticker in tickers:
        ticker_dividends = [d for d in dividends_in_period if d.ticker == ticker]
        ticker_tax = [t_ for t_ in tax_in_period if t_.ticker == ticker]
        currency = ticker_dividends[0].currency if ticker_dividends else ticker_tax[0].currency

        gross_native = sum(d.amount for d in ticker_dividends)
        tax_native = sum(t_.amount for t_ in ticker_tax)
        gross_inr = sum(_to_inr(d) for d in ticker_dividends)
        tax_inr = sum(_to_inr(t_) for t_ in ticker_tax)

        # A ticker can have multiple dividend payments on different dates,
        # each at its own RBI rate - this is the effective (amount-weighted)
        # rate that reproduces the INR total from the native total, i.e.
        # inr/native. With a single payment it's just that payment's actual
        # rate. Tax withheld still uses each event's own actual rate
        # internally (tax_inr above), just not shown as a separate column.
        dividend_rate = gross_inr / gross_native if gross_native else 0

        rows.append(
            (
                ticker,
                currency,
                round(gross_native, 2),
                round(tax_native, 2),
                round(dividend_rate, 4),
                round(gross_inr),
                round(tax_inr),
                round(gross_inr - tax_inr),
            )
        )

    return file_utils.write_csv_to_file(
        output_folder_abs_path,
        "dividend_income.csv",
        DIVIDEND_INCOME_HEADER,
        rows,
        True,
        print_path_to_console=True,
    )
