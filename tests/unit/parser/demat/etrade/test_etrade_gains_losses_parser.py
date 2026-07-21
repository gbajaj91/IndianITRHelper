import pandas as pd

from parser.demat.etrade import etrade_gains_losses_parser
from utils import date_utils

HEADER = (
    "Record Type,Symbol,Plan Type,Quantity,Date Acquired,"
    "Date Acquired (Wash Sale Toggle = On),Acquisition Cost,"
    "Acquisition Cost Per Share,Ordinary Income Recognized,"
    "Ordinary Income Recognized Per Share,Adjusted Cost Basis,"
    "Adjusted Cost Basis Per Share,Date Sold,Total Proceeds,Proceeds Per Share,"
    "Deferred Loss,Gain/Loss,Gain/Loss (Wash Sale Toggle = On),Adjusted Gain/Loss,"
    "Adjusted Gain (Loss) Per Share,Capital Gains Status,"
    "Wash Sale Adjusted Capital Gains Status,Total Wash Sale Adjustment Amount,"
    "Wash Sale Adjustment Amount Per Share,Total Wash Sale Adjusted Cost Basis,"
    "Wash Sale Adjusted Cost Basis Per Share,Total Wash Sale Adjusted Gain/Loss,"
    "Wash Sale Adjusted Gain/Loss Per Share,Order Type,Covered Status,"
    "Qualified Plan?,Disposition Type,Type,Grant Date,Grant Date FMV,"
    "Discount Amount,Purchase Date,Purchase Date Fair Mkt. Value,Purchase Price,"
    "Grant Number,83(b) Election,Vest Date,Vest Date FMV,Exercise Date,"
    "Exercise Date FMV,Grant Price,Order Number"
)

SUMMARY_ROW = 'Summary,,,124.336,,,,,,,,,,,,,"$31,427.42","$31,427.42","-$1,731.50",,,,,,,,"-$1,731.50",,,,,,,,,,,,,,,,,,,,'
RSU_ROW = (
    "Sell,ADBE,RS,8,04/15/2025,04/15/2025,$0.00,$0.00,\"$2,805.72\",$350.72,"
    "\"$2,805.72\",$350.72,04/24/2025,\"$2,864.64\",$358.08,$0.00,\"$2,864.64\","
    "\"$2,864.64\",$58.92,$7.37,Short,Short,$0.00,$0.00,\"$2,805.72\",$350.72,"
    "$58.92,$7.37,Sell Restricted Stock,,,--,Restricted Stock Unit,01/24/2023,"
    "361.32,0,--,0.0,0,RU383796,N,04/15/2025,15at1900,--,0,0,91763072"
)
ESPP_ROW = (
    "Sell,ADBE,ESPP,10,12/30/2022,12/30/2022,\"$2,860.52\",$286.05,$552.72,"
    "$55.27,\"$3,413.24\",$341.32,05/02/2025,\"$3,811.44\",$381.14,$0.00,"
    "$950.92,$950.92,$398.20,$39.82,Long,Long,$0.00,$0.00,\"$3,413.24\","
    "$341.32,$398.20,$39.82,Sell ESPP,,,Qualifying Disposition,--,07/01/2022,"
    "368.48,55.272,12/30/2022,336.53,286.0505,--,--,--,0at1900,--,0,0,91975900"
)


def sell_row(symbol, plan_type, quantity, date_acquired, date_sold, total_proceeds):
    """A minimal Sell row - only the fields _index_sell_rows actually reads
    are set, the rest left blank."""
    fields = [""] * 47
    fields[0] = "Sell"
    fields[1] = symbol
    fields[2] = plan_type
    fields[3] = str(quantity)
    fields[4] = date_acquired
    fields[12] = date_sold
    fields[13] = total_proceeds
    return ",".join(fields)


def write_gl_csv(tmp_path, rows):
    csv_path = tmp_path / "gl.csv"
    csv_path.write_text("\n".join([HEADER] + rows) + "\n")
    return str(csv_path)


def write_gl_xlsx(tmp_path, rows):
    """Same data as write_gl_csv, but as an actual .xlsx file - ETRADE's
    G&L Expanded report can be downloaded in either format."""
    csv_path = write_gl_csv(tmp_path, rows)
    xlsx_path = tmp_path / "gl.xlsx"
    pd.read_csv(csv_path, encoding="utf-8-sig").to_excel(
        xlsx_path, engine="openpyxl", index=False
    )
    return str(xlsx_path)


def write_benefit_history(tmp_path, rsu_rows=None, espp_rows=None):
    """A minimal BenefitHistory.xlsx with just the columns
    etrade_benefit_history_parser actually reads. Defaults describe the same
    lots as RSU_ROW/ESPP_ROW above: an RSU release of 8 ADBE shares on
    04/15/2025, and an ESPP purchase of 10 ADBE shares on 12/30/2022 that's
    fully sold (Sellable Qty. 0)."""
    xlsx_path = tmp_path / "BenefitHistory.xlsx"
    rsu_df = pd.DataFrame(
        rsu_rows
        or [
            {"Record Type": "Grant", "Symbol": "ADBE", "Event Type": None, "Date": None, "Qty. or Amount": None},
            {"Record Type": "Event", "Symbol": None, "Event Type": "Shares released", "Date": "04/15/2025", "Qty. or Amount": 8.0},
        ]
    )
    espp_df = pd.DataFrame(
        espp_rows
        or [
            {
                "Record Type": "Purchase",
                "Symbol": "ADBE",
                "Purchase Date": "30-DEC-2022",
                "Purchase Date FMV": "$336.53",
                "Purchased Qty.": "10",
                "Sellable Qty.": "0",
            },
        ]
    )
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        espp_df.to_excel(writer, sheet_name="ESPP", index=False)
        rsu_df.to_excel(writer, sheet_name="Restricted Stock", index=False)
    return str(xlsx_path)


def test_trades_come_from_benefit_history_including_unsold_lots(tmp_path):
    # No matching Sell rows at all - both lots should still appear, just with
    # no disposals, since BenefitHistory.xlsx is the source of every trade.
    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_csv(tmp_path, [SUMMARY_ROW])

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    assert len(purchases) == 2
    assert all(p.disposals == [] for p in purchases)


def test_sale_price_and_quantity_come_from_gl_file(tmp_path):
    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_csv(tmp_path, [RSU_ROW, ESPP_ROW])

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    by_holding_type = {p.holding_type: p for p in purchases}
    rsu = by_holding_type["RSU"]
    assert len(rsu.disposals) == 1
    assert rsu.disposals[0].quantity == 8.0
    assert abs(rsu.disposals[0].price - 2864.64 / 8) < 0.0001

    espp = by_holding_type["ESPP"]
    assert len(espp.disposals) == 1
    assert espp.disposals[0].quantity == 10.0
    assert abs(espp.disposals[0].price - 3811.44 / 10) < 0.0001
    # ESPP cost basis still comes from BenefitHistory's Purchase Date FMV.
    assert espp.purchase_fmv.price == 336.53


def test_xlsx_gl_file_parses_the_same_as_csv(tmp_path):
    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_xlsx(tmp_path, [RSU_ROW, ESPP_ROW])

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    by_holding_type = {p.holding_type: p for p in purchases}
    assert by_holding_type["RSU"].disposals[0].quantity == 8.0
    assert by_holding_type["ESPP"].disposals[0].quantity == 10.0


def test_extract_tickers_combines_both_files(tmp_path):
    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_csv(tmp_path, [RSU_ROW, ESPP_ROW])
    assert etrade_gains_losses_parser.extract_tickers(benefit_history_path, gl_path) == {
        "adbe"
    }


def test_espp_fully_sold_with_no_matching_sell_row_is_excluded_and_logged(
    tmp_path, monkeypatch
):
    logged = []
    monkeypatch.setattr(etrade_gains_losses_parser.logger, "log", logged.append)

    # BenefitHistory says the ESPP lot is fully sold (Sellable Qty. 0), but
    # the G&L file has no Sell row for it - its gain can't be computed.
    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_csv(tmp_path, [RSU_ROW])

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    espp = next(p for p in purchases if p.holding_type == "ESPP")
    assert espp.disposals == []
    assert any(
        "fully sold per BenefitHistory.xlsx" in msg and "ADBE" in msg.upper()
        for msg in logged
    )


def test_sell_row_with_no_matching_lot_is_logged(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(etrade_gains_losses_parser.logger, "log", logged.append)

    # BenefitHistory has no ESPP lot at all, but the G&L file has a Sell row
    # for one - it should be logged as unmatched, not silently dropped.
    benefit_history_path = write_benefit_history(
        tmp_path,
        espp_rows=[
            {
                "Record Type": "Purchase",
                "Symbol": "ADBE",
                "Purchase Date": "01-JAN-2020",
                "Purchase Date FMV": "$1.00",
                "Purchased Qty.": "1",
                "Sellable Qty.": "1",
            }
        ],
    )
    gl_path = write_gl_csv(tmp_path, [RSU_ROW, ESPP_ROW])

    etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    assert any("no matching lot was found in BenefitHistory.xlsx" in msg for msg in logged)


def test_duplicate_sell_rows_for_same_disposal_take_the_higher_price(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(etrade_gains_losses_parser.logger, "log", logged.append)

    benefit_history_path = write_benefit_history(tmp_path)
    # Two "duplicate" Sell rows for the exact same lot/sale date/quantity,
    # differing only in the reported proceeds - a higher-priced duplicate.
    higher_proceeds_row = RSU_ROW.replace('"$2,864.64",$358.08', '"$3,000.00",$375.00', 1)
    gl_path = write_gl_csv(tmp_path, [RSU_ROW, higher_proceeds_row])

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    rsu = next(p for p in purchases if p.holding_type == "RSU")
    assert len(rsu.disposals) == 1
    assert rsu.disposals[0].quantity == 8.0
    assert abs(rsu.disposals[0].price - 3000.00 / 8) < 0.0001


def test_sales_split_across_multiple_lots_sharing_the_same_acquisition_date(tmp_path):
    # Two separate RSU grants both released shares on 04/15/2025 - a real
    # BenefitHistory.xlsx scenario. Regression test: matched Sell rows used
    # to all be attributed to whichever lot was encountered first, leaving
    # the other lot(s) with no disposals at all (and thus $0 sale proceeds)
    # even though they were, in fact, sold.
    benefit_history_path = write_benefit_history(
        tmp_path,
        rsu_rows=[
            {"Record Type": "Grant", "Symbol": "ADBE", "Event Type": None, "Date": None, "Qty. or Amount": None},
            {"Record Type": "Event", "Symbol": None, "Event Type": "Shares released", "Date": "04/15/2025", "Qty. or Amount": 5.0},
            {"Record Type": "Grant", "Symbol": "ADBE", "Event Type": None, "Date": None, "Qty. or Amount": None},
            {"Record Type": "Event", "Symbol": None, "Event Type": "Shares released", "Date": "04/15/2025", "Qty. or Amount": 3.0},
        ],
        espp_rows=[],
    )
    # 8 shares total acquired on 04/15/2025 (5 + 3), sold across two separate
    # transactions that don't align 1:1 with either lot: 6 on 04/20, 2 on
    # 04/25.
    gl_path = write_gl_csv(
        tmp_path,
        [
            sell_row("ADBE", "RS", 6, "04/15/2025", "04/20/2025", "$600.00"),
            sell_row("ADBE", "RS", 2, "04/15/2025", "04/25/2025", "$220.00"),
        ],
    )

    purchases = etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )
    rsu_lots = sorted(
        (p for p in purchases if p.holding_type == "RSU"), key=lambda p: p.quantity
    )
    assert [lot.quantity for lot in rsu_lots] == [3.0, 5.0]

    # Every lot ends up fully sold, and every share is accounted for -
    # nothing dropped, nothing double-counted, nothing left stuck on the
    # first lot encountered.
    for lot in rsu_lots:
        assert lot.closing_quantity == 0.0
        assert sum(d.quantity for d in lot.disposals) == lot.quantity

    total_sold = sum(d.quantity for lot in rsu_lots for d in lot.disposals)
    assert total_sold == 8.0
    total_proceeds = sum(
        d.quantity * d.price for lot in rsu_lots for d in lot.disposals
    )
    assert abs(total_proceeds - 820.0) < 0.0001


def test_summary_cross_check_warns_on_mismatch(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(etrade_gains_losses_parser.logger, "log", logged.append)

    benefit_history_path = write_benefit_history(tmp_path)
    gl_path = write_gl_csv(tmp_path, [SUMMARY_ROW, RSU_ROW, ESPP_ROW])

    etrade_gains_losses_parser.parse(
        benefit_history_path, gl_path, str(tmp_path / "out"), None
    )

    assert any("doesn't match the file's own Summary row" in msg for msg in logged)
