from parser.demat.etrade import etrade_benefit_history_parser
from utils import date_utils
import pandas as pd

from tests.unit.parser.demat.etrade.conftest import create_espp_mock

def test_espp_parsing_with_no_purchase(
    benefit_history_excel_file_with_no_purchase_espp: pd.ExcelFile,
):
    espp_purchase = etrade_benefit_history_parser.parse_espp(
        benefit_history_excel_file_with_no_purchase_espp, None
    )
    assert len(espp_purchase) == 0


def test_espp_parsing_row_with_no_purchase():
    espp_purchase = etrade_benefit_history_parser.parse_espp_row(
        pd.Series(
            {
                "Record Type": "Some random type",
            }
        )
    )
    assert espp_purchase is None


def test_espp_parsing_row_with_valid_purchase():
    espp_purchase = etrade_benefit_history_parser.parse_espp_row(
        pd.Series(
            {
                "Record Type": "Purchase",
                "Symbol": "ADBE",
                "Purchase Date": "30-JUN-2020",
                "Purchased Qty.": "2",
                "Sellable Qty.": "2",
                "Purchase Date FMV": "$435.31",
            }
        )
    )
    assert espp_purchase is not None
    assert espp_purchase.quantity == 2.0
    assert espp_purchase.closing_quantity == 2.0


def test_espp_parsing_row_with_fully_sold_purchase():
    # Purchased Qty. is the amount originally bought; Sellable Qty. can have
    # since dropped to 0 if all of it was sold - quantity must still reflect
    # the original purchase, not the now-empty sellable balance.
    espp_purchase = etrade_benefit_history_parser.parse_espp_row(
        pd.Series(
            {
                "Record Type": "Purchase",
                "Symbol": "ADBE",
                "Purchase Date": "30-JUN-2016",
                "Purchased Qty.": "5",
                "Sellable Qty.": "0",
                "Purchase Date FMV": "$100.00",
            }
        )
    )
    assert espp_purchase is not None
    assert espp_purchase.quantity == 5.0
    assert espp_purchase.closing_quantity == 0.0


def test_espp_fully_sold_purchase_records_last_sale_date():
    # Sellable Qty. is 0 - the last Sale event's date is recorded on the
    # Purchase so faa3_parser (which knows the reporting period) can decide
    # whether it's reportable. parse_espp itself doesn't exclude anything.
    espp_sheet = create_espp_mock(
        {
            "Record Type": ["Purchase", "Event"],
            "Symbol": ["ADBE", ""],
            "Purchase Date": ["30-JUN-2016", ""],
            "Purchased Qty.": ["5", None],
            "Sellable Qty.": ["0", None],
            "Event Type": [None, "Sale"],
            "Date": [None, "07/01/2020"],
            "Qty. or Amount": [None, 5],
            "Purchase Date FMV": ["$100.00", None],
        }
    )
    purchases = etrade_benefit_history_parser.parse_espp(espp_sheet, None)
    assert len(purchases) == 1
    assert purchases[0].quantity == 5.0
    assert purchases[0].closing_quantity == 0.0
    assert purchases[0].last_sale_date_in_millis == date_utils.parse_mm_dd(
        "07/01/2020"
    )["time_in_millis"]


def test_espp_partially_held_purchase_has_no_last_sale_date():
    # Sellable Qty. > 0 - still (partly) held, so last_sale_date_in_millis is
    # irrelevant and left unset even if a Sale event happened.
    espp_sheet = create_espp_mock(
        {
            "Record Type": ["Purchase", "Event"],
            "Symbol": ["ADBE", ""],
            "Purchase Date": ["30-JUN-2016", ""],
            "Purchased Qty.": ["5", None],
            "Sellable Qty.": ["2", None],
            "Event Type": [None, "Sale"],
            "Date": [None, "07/01/2020"],
            "Qty. or Amount": [None, 3],
            "Purchase Date FMV": ["$100.00", None],
        }
    )
    purchases = etrade_benefit_history_parser.parse_espp(espp_sheet, None)
    assert len(purchases) == 1
    assert purchases[0].quantity == 5.0
    assert purchases[0].closing_quantity == 2.0
    assert purchases[0].last_sale_date_in_millis is None


def test_espp_parsing_with_only_released_shares(
    benefit_history_excel_file_with_vested_and_released_espp: pd.ExcelFile,
):
    espp_purchases = etrade_benefit_history_parser.parse_espp(
        benefit_history_excel_file_with_vested_and_released_espp, None
    )
    assert len(espp_purchases) == 1
    espp_purchase = espp_purchases[0]
    assert espp_purchase.quantity == 2
    assert espp_purchase.purchase_fmv.currency_code == "USD"
    assert espp_purchase.purchase_fmv.price == 435.31
    assert espp_purchase.ticker == "adbe"
    assert espp_purchase.date == {
        "disp_time": "30-Jun-2020",
        "orig_disp_time": "30-JUN-2020",
        "time_in_millis": 1593475200000,
    }
