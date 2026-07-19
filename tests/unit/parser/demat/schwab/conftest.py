"""Fake, network-free ticker_mapping for schwab parser tests.

Real ticker_mapping fetches org info/currency from yfinance over the network
and caches to disk. Tests should never depend on network access, so every
test in this package gets a fake lookup covering just the tickers used in
these fixtures; anything else behaves like an unknown ticker.
"""

import pytest

from models.org import Organization
from utils import ticker_mapping

KNOWN_TICKERS = {"aapl", "pltr", "ring", "mags"}


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
    monkeypatch.setattr(ticker_mapping, "get_currency", _fake_get_currency)
    monkeypatch.setattr(ticker_mapping, "get_org_info", _fake_get_org_info)
