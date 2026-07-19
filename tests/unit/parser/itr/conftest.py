"""Fake, network-free ticker_mapping for itr parser tests.

Real ticker_mapping fetches org info/currency from yfinance over the network
and caches to disk. Tests should never depend on network access.
"""

import pytest

from models.org import Organization
from utils import ticker_mapping


def _fake_get_currency(ticker: str) -> str:
    return "USD"


def _fake_get_org_info(ticker: str) -> Organization:
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
