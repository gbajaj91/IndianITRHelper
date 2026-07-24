import pytest

from parser.demat.schwab import schwab_transaction_parser


HEADER = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount,,,,,,"


def write_csv(tmp_path, rows):
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text("\n".join([HEADER] + rows) + "\n")
    return str(csv_path)


def test_single_buy_is_parsed(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Buy,AAPL,APPLE INC,1,$258.00 ,,($258.00),,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase.ticker == "aapl"
    assert purchase.quantity == 1
    assert purchase.purchase_fmv.price == 258.00
    assert purchase.purchase_fmv.currency_code == "USD"
    assert purchase.date["orig_disp_time"] == "10/3/25"


def test_non_buy_sell_actions_are_ignored(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/30/25,Credit Interest,,SCHWAB1 INT 09/29-10/29,,,,$0.05 ,,,,,,",
            "10/9/25,Wire Received,,WIRED FUNDS RECEIVED,,,,\"$3,300.00 \",,,,,,",
            "10/3/25,Buy,AAPL,APPLE INC,1,$258.00 ,,($258.00),,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    assert purchases[0].ticker == "aapl"


def test_sell_fully_consumes_oldest_lot_fifo(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/9/25,Buy,AAPL,APPLE INC,1,$256.50 ,,($256.50),,,,,,",
            "10/3/25,Buy,AAPL,APPLE INC,1,$258.00 ,,($258.00),,,,,,",
            "11/4/25,Sell,AAPL,APPLE INC,1,$193.50 ,,$193.50 ,,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    # the 10/3 lot (oldest) is fully consumed by the sell, but is still
    # reported (with closing_quantity=0) rather than dropped. The 10/9 lot
    # is untouched.
    assert len(purchases) == 2
    by_date = {p.date["orig_disp_time"]: p for p in purchases}
    assert by_date["10/3/25"].quantity == 1
    assert by_date["10/3/25"].closing_quantity == 0
    assert by_date["10/9/25"].quantity == 1
    assert by_date["10/9/25"].closing_quantity == 1


def test_sell_partially_reduces_lot_and_spans_multiple_lots(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/13/25,Buy,MAGS,LISTED FNDS RONDHL MGNFCNT ETF,5,$64.10 ,,($320.50),,,,,,",
            "10/14/25,Buy,MAGS,LISTED FNDS RONDHL MGNFCNT ETF,5,$63.22 ,,($316.10),,,,,,",
            "10/29/25,Sell,MAGS,LISTED FNDS RONDHL MGNFCNT ETF,7,$69.10 ,,\"$1,036.50 \",,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 2
    by_date = {p.date["orig_disp_time"]: p for p in purchases}
    assert by_date["10/13/25"].quantity == 5
    assert by_date["10/13/25"].closing_quantity == 0
    assert by_date["10/14/25"].quantity == 5
    assert by_date["10/14/25"].closing_quantity == 3


def test_ticker_fully_sold_out_is_not_dropped(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/10/25,Buy,PLTR,PALANTIR TECHNOLOGIES INC,1,$180.00 ,,($180.00),,,,,,",
            "11/4/25,Sell,PLTR,PALANTIR TECHNOLOGIES INC,1,$193.50 ,,$193.50 ,,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    assert purchases[0].ticker == "pltr"
    assert purchases[0].quantity == 1
    assert purchases[0].closing_quantity == 0


def test_stock_plan_activity_is_treated_as_rsu_acquisition(tmp_path):
    # Shares deposited from an equity award plan (e.g. RSU vesting) have no
    # Price column at all - cost basis must come from the market closing
    # price on the deposit date instead, same as ETRADE RSU releases.
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Stock Plan Activity,AAPL,APPLE INC,2,,,,,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase.holding_type == "RSU"
    assert purchase.quantity == 2
    assert purchase.purchase_fmv.price == 258.0199890136719


def test_stock_plan_activity_shares_can_later_be_sold(tmp_path):
    # Regression test: Stock Plan Activity deposits used to be silently
    # dropped entirely, so a later Sell of those same shares had no lot to
    # consume and crashed with "More shares sold than bought" - even though
    # the shares genuinely were acquired, just via a transfer rather than a
    # Buy.
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Stock Plan Activity,AAPL,APPLE INC,2,,,,,,,,,",
            "11/4/25,Sell,AAPL,APPLE INC,2,$193.50 ,,$387.00 ,,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase.closing_quantity == 0
    assert len(purchase.disposals) == 1
    assert purchase.disposals[0].quantity == 2


def test_reinvest_shares_is_treated_as_acquisition(tmp_path):
    # Dividend reinvestment ("Reinvest Shares") buys additional (usually
    # fractional) shares and has a real Price column, unlike Stock Plan
    # Activity - it should be treated just like a regular Buy.
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Reinvest Shares,AAPL,APPLE INC,0.05,$258.00 ,,($12.90),,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase.holding_type == "Trade"
    assert purchase.quantity == 0.05
    assert purchase.purchase_fmv.price == 258.00


def test_reinvested_shares_can_later_be_sold(tmp_path):
    # Regression test: Reinvest Shares rows used to be silently dropped, so
    # a Sell that included previously-reinvested fractional shares had no
    # lot to consume and crashed with "More shares sold than bought" - e.g.
    # a Buy of 9 whole shares plus small Reinvest Shares fractions adding up
    # to 9.0271, then a Sell of exactly 9.0271.
    csv_path = write_csv(
        tmp_path,
        [
            "4/23/25,Buy,AAPL,APPLE INC,9,$251.70 ,,($2265.30),,,,,,",
            "7/10/25,Reinvest Shares,AAPL,APPLE INC,0.0271,$265.15 ,,($7.19),,,,,,",
            "3/30/26,Sell,AAPL,APPLE INC,9.0271,$185.00 ,,\"$1,670.01\",,,,,,",
        ],
    )
    purchases = schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)

    assert len(purchases) == 2
    assert sum(p.closing_quantity for p in purchases) == 0
    assert sum(d.quantity for p in purchases for d in p.disposals) == 9.0271


def test_oversell_raises_clear_error(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Buy,AAPL,APPLE INC,1,$258.00 ,,($258.00),,,,,,",
            "11/4/25,Sell,AAPL,APPLE INC,5,$193.50 ,,$967.50 ,,,,,,",
        ],
    )
    with pytest.raises(AssertionError) as error:
        schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)
    assert "More shares sold than bought for 'aapl'" in str(error.value)


def test_missing_ticker_mapping_fails_fast(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Buy,ZZZZ,UNKNOWN TICKER INC,1,$10.00 ,,($10.00),,,,,,",
        ],
    )
    with pytest.raises(AssertionError) as error:
        schwab_transaction_parser.parse(csv_path, str(tmp_path / "out"), None)
    assert "Could not resolve ticker info for" in str(error.value)
    assert "zzzz" in str(error.value)


def test_time_bounds_excludes_out_of_range_transactions(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            "10/3/25,Buy,AAPL,APPLE INC,1,$258.00 ,,($258.00),,,,,,",
            "1/3/26,Buy,AAPL,APPLE INC,1,$260.00 ,,($260.00),,,,,,",
        ],
    )
    from utils import date_utils

    end_of_2025 = date_utils.parse_m_d_yy("12/31/25")["time_in_millis"]
    purchases = schwab_transaction_parser.parse(
        csv_path, str(tmp_path / "out"), (None, end_of_2025)
    )

    assert len(purchases) == 1
    assert purchases[0].date["orig_disp_time"] == "10/3/25"


DIVIDEND_ROWS = [
    "3/30/26,NRA Tax Adj,GS,GOLDMAN SACHS GROUP INC,,,,($1.13),,,,,,",
    "3/30/26,Qualified Div,GS,GOLDMAN SACHS GROUP INC,,,,$4.50 ,,,,,,",
    "3/26/26,NRA Tax Adj,V,VISA INC CLASS A,,,,($0.17),,,,,,",
    "3/26/26,Qualified Div,V,VISA INC CLASS A,,,,$0.67 ,,,,,,",
    "12/31/25,NRA Tax Adj,QQQ,INVSC QQQ TRUST SRS 1 ETF,,,,($0.80),,,,,,",
    "12/31/25,Cash Dividend,QQQ,INVSC QQQ TRUST SRS 1 ETF,,,,$3.18 ,,,,,,",
    "12/30/25,NRA Tax Adj,,SCHWAB1 INT 11/26-12/29,,,,($0.02),,,,,,",
    "12/30/25,Credit Interest,,SCHWAB1 INT 11/26-12/29,,,,$0.15 ,,,,,,",
]


def test_parse_dividends_separates_dividends_and_tax(tmp_path):
    csv_path = write_csv(tmp_path, DIVIDEND_ROWS)
    dividends, tax_withheld = schwab_transaction_parser.parse_dividends(csv_path)

    assert {(d.ticker, d.amount) for d in dividends} == {
        ("gs", 4.50),
        ("v", 0.67),
        ("qqq", 3.18),
    }
    assert {(t.ticker, t.amount) for t in tax_withheld} == {
        ("gs", 1.13),
        ("v", 0.17),
        ("qqq", 0.80),
    }


def test_parse_dividends_excludes_interest_tax_adjustment(tmp_path):
    # The NRA Tax Adj row with a blank Symbol is against interest, not a
    # dividend - it must not show up as tax withheld for any ticker.
    csv_path = write_csv(tmp_path, DIVIDEND_ROWS)
    _, tax_withheld = schwab_transaction_parser.parse_dividends(csv_path)

    assert all(t.ticker for t in tax_withheld)
    assert len(tax_withheld) == 3


def test_extract_tickers_includes_dividend_only_tickers(tmp_path):
    csv_path = write_csv(tmp_path, DIVIDEND_ROWS)
    tickers = schwab_transaction_parser.extract_tickers(csv_path)
    assert tickers == {"gs", "v", "qqq"}
