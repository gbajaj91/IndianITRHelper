#!/usr/bin/env python3
import argparse
import os
import sys

import time
from datetime import date, timedelta

from parser.demat.etrade import etrade_benefit_history_parser
from utils import logger, date_utils, ticker_mapping
from parser.demat.etrade import etrade_holdings_bystatus_parser
from parser.demat.schwab import schwab_transaction_parser
from parser.itr import faa3_parser, capital_gains_parser, dividend_income_parser
from refresh_historic_data import refresh, DEFAULT_START
import refresh_rbi_rates

# arguments defaults
script_path = os.path.realpath(os.path.dirname(__file__))
DEFAULT_OUTPUT_FOLDER_NAME = "output"
default_output_folder_abs_path = os.path.join(script_path, DEFAULT_OUTPUT_FOLDER_NAME)
DEFAULT_SOURCE_MODE = "etrade_benefit_history"
DEFAULT_CALENDER_MODE = "calendar"
DEFAULT_REPORT = "fa"
SHARE_PRICE_REFRESH_THROTTLE_SECONDS = 24 * 60 * 60


def main():
    parser = argparse.ArgumentParser(
        description="This is a Python module to generate Indian ITR schedule FA under section A3 automatically"
    )
    parser.add_argument(
        "-o",
        "--output",
        action="store",
        type=str,
        default=default_output_folder_abs_path,
        dest="output_folder",
        help=f"Specify the absolute path of the absolute path of output folder for JSON data, default = {default_output_folder_abs_path}",
    )
    parser.add_argument(
        "-i",
        "--input",
        action="store",
        dest="input_excel_file",
        help="Specify the absolute path for the input file: benefit history(BenefitHistory.xlsx) "
        "Excel file for etrade source modes, or the transactions CSV export for schwab_transactions",
        required=True,
    )
    parser.add_argument(
        "-m",
        "--source-mode",
        action="store",
        default=DEFAULT_SOURCE_MODE,
        dest="source_mode",
        choices=[f"{DEFAULT_SOURCE_MODE}", "etrade_holdings_bystatus", "schwab_transactions"],
        help=f"Specify the source mode, default = {DEFAULT_SOURCE_MODE}",
    )
    parser.add_argument(
        "-cal",
        "--calendar-mode",
        action="store",
        type=str,
        default=DEFAULT_CALENDER_MODE,
        dest="calendar_mode",
        choices=[f"{DEFAULT_CALENDER_MODE}", "financial"],
        help=f"Specify the calendar period for consideration, default = {DEFAULT_CALENDER_MODE}",
    )
    parser.add_argument(
        "-r",
        "--report",
        action="store",
        default=DEFAULT_REPORT,
        dest="report",
        choices=[DEFAULT_REPORT, "capital_gains", "dividend_income"],
        help="Specify the report to generate: 'fa' for Schedule FA section A3 "
        "(fa_entries.csv/transactions.csv), 'capital_gains' for an LTCG/STCG "
        "capital gains report scoped to the financial year (capital_gains.csv), or "
        "'dividend_income' for gross dividends/tax withheld per ticker scoped to the "
        f"financial year (dividend_income.csv), default = {DEFAULT_REPORT}",
    )
    parser.add_argument(
        "-ay",
        "--assessment-year",
        action="store",
        dest="assessment_year",
        type=int,
        required=True,
        help="Current year of assessment year. For AY 2019-2020, input will be 2019. Input will be of type integer",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="debug",
        default=False,
        help="Enable the debug logs",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        dest="skip_refresh",
        default=False,
        help="Skip refreshing historic share prices from Yahoo Finance and use the "
        "bundled historic_data CSVs instead (useful when offline)",
    )

    args = parser.parse_args()

    # Namespace output by source and report type so e.g. an "fa" run for
    # schwab_transactions doesn't overwrite/mix with a "capital_gains" run,
    # or with an etrade run against a different broker's data.
    output_folder_abs_path = os.path.join(
        args.output_folder, args.source_mode, args.report
    )

    logger.DEBUG = args.debug
    etrade_benefit_history_parser.DEBUG = args.debug
    etrade_holdings_bystatus_parser.DEBUG = args.debug
    schwab_transaction_parser.DEBUG = args.debug

    if args.source_mode == "etrade_holdings_bystatus":
        tickers = etrade_holdings_bystatus_parser.extract_tickers(args.input_excel_file)
    elif args.source_mode == "schwab_transactions":
        tickers = schwab_transaction_parser.extract_tickers(args.input_excel_file)
    else:
        tickers = etrade_benefit_history_parser.extract_tickers(args.input_excel_file)

    # Refresh before parsing: RSU rows resolve their FMV from the share price CSV
    # during parsing, so the historic data must be up to date beforehand.
    if not args.skip_refresh:
        refresh_historic_data(tickers)

    # Capital gains and dividend income are always reported on a
    # financial-year basis in India, independent of --calendar-mode (which
    # only governs the Schedule FA report) - so the parsing-stage cutoff
    # must follow the report being generated, not the (possibly irrelevant)
    # --calendar-mode flag.
    parsing_calendar_mode = (
        "financial"
        if args.report in ("capital_gains", "dividend_income")
        else args.calendar_mode
    )

    dividends, tax_withheld = [], []
    if args.source_mode == "schwab_transactions":
        dividends, tax_withheld = schwab_transaction_parser.parse_dividends(
            args.input_excel_file
        )

    if args.source_mode == "etrade_holdings_bystatus":
        purchases = etrade_holdings_bystatus_parser.parse(
            args.input_excel_file, output_folder_abs_path
        )
    elif args.source_mode == "schwab_transactions":
        purchases = schwab_transaction_parser.parse(
            args.input_excel_file,
            output_folder_abs_path,
            time_bounds=(
                None,
                date_utils.calendar_range(parsing_calendar_mode, args.assessment_year)[
                    1
                ],
            ),
        )
    else:
        purchases = etrade_benefit_history_parser.parse(
            args.input_excel_file,
            output_folder_abs_path,
            time_bounds=(
                None,
                date_utils.calendar_range(parsing_calendar_mode, args.assessment_year)[
                    1
                ],
            ),
        )

    if args.report == "capital_gains":
        capital_gains_parser.parse(
            purchases, args.assessment_year, output_folder_abs_path
        )
    elif args.report == "dividend_income":
        dividend_income_parser.parse(
            dividends, tax_withheld, args.assessment_year, output_folder_abs_path
        )
    else:
        faa3_parser.parse(
            args.calendar_mode,
            purchases,
            args.assessment_year,
            output_folder_abs_path,
            dividends=dividends,
        )


def _share_data_path(ticker: str) -> str:
    return os.path.join(script_path, "historic_data", "shares", ticker.lower(), "data.csv")


def _refreshed_recently(path: str, max_age_seconds: int) -> bool:
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_seconds


def refresh_historic_data(tickers):
    """Best-effort refresh of historic share prices and RBI/FBIL reference rates
    for every ticker found in the input file. Failures (missing dependency, no
    network) are logged and ignored so the run falls back to bundled/cached
    historic_data."""
    end = (date.today() + timedelta(days=1)).isoformat()
    tickers = sorted(tickers)
    for ticker in tickers:
        data_path = _share_data_path(ticker)
        if _refreshed_recently(data_path, SHARE_PRICE_REFRESH_THROTTLE_SECONDS):
            logger.log(
                f"Skipping share price refresh for {ticker}; {data_path} was "
                "refreshed within the last 24 hours."
            )
            continue
        try:
            refresh(ticker, DEFAULT_START, end)
        except SystemExit as err:
            logger.log(
                f"Skipping share price refresh for {ticker} ({err}); using bundled "
                "historic data. Pass --skip-refresh to suppress this."
            )
        except Exception as err:
            logger.log(
                f"Could not refresh share prices for {ticker} ({err}); "
                "using bundled historic data."
            )

    currencies = set()
    for ticker in tickers:
        try:
            currencies.add(ticker_mapping.get_currency(ticker))
        except Exception as err:
            logger.log(
                f"Could not determine currency for {ticker} ({err}); "
                "skipping its reference rate refresh."
            )
    currencies = sorted(currencies)
    if currencies:
        try:
            refresh_rbi_rates.refresh(
                currencies, refresh_rbi_rates.DEFAULT_START, date.today().isoformat()
            )
        except SystemExit as err:
            logger.log(
                f"Skipping reference rate refresh ({err}); using bundled rates. "
                "Pass --skip-refresh to suppress this."
            )
        except Exception as err:
            logger.log(
                f"Could not refresh reference rates ({err}); using bundled rates."
            )


if __name__ == "__main__":
    try:
        main()
        logger.log("On your left!")
    except KeyboardInterrupt:
        logger.log("Interrupt requested... exiting")
    sys.exit(0)
