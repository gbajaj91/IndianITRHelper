"""
conftest.py for common fixture for etrade

This file contains the etrade related common fixtures using conftest.py
See [conftest.py](https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files)
"""

import pandas as pd
from unittest.mock import MagicMock

import pytest
from parser.demat.etrade import etrade_benefit_history_parser
from models.org import Organization
from utils import ticker_mapping

KNOWN_TICKERS = {"adbe"}


def _fake_get_currency(ticker: str) -> str:
    ticker = ticker.lower()
    if ticker not in KNOWN_TICKERS:
        raise AssertionError(f"No data returned from yfinance for ticker '{ticker}'")
    return "USD"


def _fake_get_org_info(ticker: str) -> Organization:
    ticker = ticker.lower()
    if ticker not in KNOWN_TICKERS:
        raise AssertionError(f"No data returned from yfinance for ticker '{ticker}'")
    return Organization(
        name=f"{ticker.upper()} Inc.",
        address="1 Test Street",
        country_name="United States",
        country_code="2",
        zip_code="00000",
        nature="Listed",
    )


@pytest.fixture(autouse=True)
def fake_ticker_mapping(monkeypatch):
    # ticker_mapping fetches from yfinance over the network and caches to
    # disk - tests must never depend on network access.
    monkeypatch.setattr(ticker_mapping, "get_currency", _fake_get_currency)
    monkeypatch.setattr(ticker_mapping, "get_org_info", _fake_get_org_info)


@pytest.fixture(name="benefit_history_excel_file_with_no_purchase_espp")
def fixture_benefit_history_excel_file_with_no_purchase_espp():
    return create_espp_mock(
        {
            "Record Type": [],
            "Symbol": [],
            "Event Type": [],
        }
    )


@pytest.fixture(name="benefit_history_excel_file_with_vested_and_released_espp")
def fixture_benefit_history_excel_file_with_vested_and_released_espp():
    return create_espp_mock(
        {
            "Record Type": ["Purchase", "Event", "Event"],
            "Symbol": ["ADBE", "", ""],
            "Purchase Date": ["30-JUN-2020", "", ""],
            "Purchased Qty.": ["2", None, None],
            "Sellable Qty.": ["2", None, None],
            "Event Type": [None, "Deposit", "Withdrawal"],
            "Date": [None, "07/01/2020", "07/02/2020"],
            "Qty. or Amount": [None, 0.5, 0.5],
            "Purchase Date FMV": ["$435.31", None, None],
        }
    )


def create_espp_mock(data_frame_obj) -> MagicMock:
    mock_excel_file = MagicMock(spec=pd.ExcelFile)
    mock_excel_file.parse.return_value = pd.DataFrame(data_frame_obj)
    mock_excel_file.sheet_names = [etrade_benefit_history_parser.ESPP_SHEET_NAME]
    return mock_excel_file


@pytest.fixture(name="benefit_history_excel_file_with_vested_rsu")
def fixture_benefit_history_excel_file_with_vested_rsu():
    return create_rsu_mock(
        {
            "Record Type": ["Grant", "Event"],
            "Symbol": ["ADBE", None],
            "Event Type": [None, "Shares vested"],
        }
    )


@pytest.fixture(name="benefit_history_excel_file_with_vested_and_released_rsu")
def fixture_benefit_history_excel_file_with_vested_and_released_rsu():
    return create_rsu_mock(
        {
            "Record Type": ["Grant", "Event", "Event"],
            "Symbol": ["ADBE", "", ""],
            "Event Type": ["", "Shares vested", "Shares released"],
            "Date": ["", "10/15/2023", "10/15/2023"],
            "Qty. or Amount": [None, 0.5, 0.5],
        }
    )


def create_rsu_mock(data_frame_obj) -> MagicMock:
    return create_benefit_history_mock(
        {etrade_benefit_history_parser.RSU_SHEET_NAME: data_frame_obj}
    )


@pytest.fixture(name="benefit_history_excel_file_with_espp_and_rsu")
def fixture_benefit_history_excel_file_with_espp_and_rsu():
    return create_rsu_mock(
        {
            "Record Type": ["Grant", "Event", "Event"],
            "Symbol": ["ADBE", "", ""],
            "Event Type": ["", "Shares vested", "Shares released"],
            "Date": ["", "10/15/2023", "10/15/2023"],
            "Qty. or Amount": [None, 0.5, 0.5],
        }
    )


def create_benefit_history_mock(data_frame_dict: dict) -> MagicMock:
    mock_excel_file = MagicMock(spec=pd.ExcelFile)

    def parse(sheet_name: str, skiprows: int, header: int):
        print(f"called with skiprows = {skiprows} and header = {header}")
        return pd.DataFrame(data_frame_dict[sheet_name])

    mock_excel_file.parse = parse
    mock_excel_file.sheet_names = data_frame_dict.keys()
    return mock_excel_file
