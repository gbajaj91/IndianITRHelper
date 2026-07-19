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
