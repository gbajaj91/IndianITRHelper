"""Dynamic, per-ticker org/currency lookup.

No ticker symbols are hardcoded here. Org info (name/address/country/zip) and
currency are fetched from Yahoo Finance (yfinance) the first time a ticker is
seen, then cached to historic_data/ticker_info/<ticker>.json so subsequent
runs don't need network access again.
"""

import json
import os
import typing as t

from utils.runtime_utils import warn_missing_module
from models.org import Organization

script_path = os.path.realpath(os.path.dirname(__file__))
TICKER_INFO_DIR = os.path.join(script_path, os.pardir, "historic_data", "ticker_info")

# TODO: this only covers regions seen so far (all sources supported today -
# etrade, Schwab - are US brokerages). A ticker whose yfinance "region" isn't
# listed here fails fast (see get_org_info) rather than silently guessing;
# add the (country name, ITD numeric code) for that region here when one
# comes up. Keyed by yfinance's "region" (e.g. "US"), not "country", since
# "country" is only populated for individual companies - it's None for ETFs.
# Reference: CBDT/ITD Schedule FA "Country Code" list.
REGION_INFO: t.Dict[str, t.Tuple[str, str]] = {
    "US": ("United States", "2"),
}

_org_info_cache: t.Dict[str, Organization] = {}
_currency_cache: t.Dict[str, str] = {}


def _cache_path(ticker: str) -> str:
    return os.path.join(TICKER_INFO_DIR, f"{ticker.lower()}.json")


def _fetch_ticker_info(ticker: str) -> dict:
    warn_missing_module("yfinance")
    import yfinance as yf

    info = yf.Ticker(ticker.upper()).info
    if not info or "currency" not in info:
        raise AssertionError(f"No data returned from yfinance for ticker '{ticker}'")

    name = info.get("longName") or info.get("shortName") or ticker.upper()
    address = " ".join(
        part
        for part in (info.get("address1"), info.get("city"), info.get("state"))
        if part
    )
    return {
        "name": name,
        "address": address,
        "region": info.get("region"),
        "zip_code": info.get("zip", ""),
        "currency": info["currency"],
    }


def _load_or_fetch(ticker: str) -> dict:
    ticker = ticker.lower()
    path = _cache_path(ticker)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    print(f"Fetching ticker info for {ticker} from yfinance")
    info = _fetch_ticker_info(ticker)
    os.makedirs(TICKER_INFO_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    return info


def get_org_info(ticker: str) -> Organization:
    ticker = ticker.lower()
    if ticker not in _org_info_cache:
        info = _load_or_fetch(ticker)
        region = info["region"]
        region_info = REGION_INFO.get(region)
        assert region_info is not None, (
            f"No ITD Schedule FA country code mapping for region '{region}' "
            f"(ticker '{ticker}'). Add it to REGION_INFO in utils/ticker_mapping.py."
        )
        country_name, country_code = region_info
        _org_info_cache[ticker] = Organization(
            name=info["name"],
            address=info["address"],
            country_name=country_name,
            country_code=country_code,
            zip_code=info["zip_code"],
            nature="Listed",
        )
    return _org_info_cache[ticker]


def get_currency(ticker: str) -> str:
    ticker = ticker.lower()
    if ticker not in _currency_cache:
        info = _load_or_fetch(ticker)
        _currency_cache[ticker] = info["currency"]
    return _currency_cache[ticker]
