import typing as t
from itertools import groupby
import operator

from utils import date_utils, share_data_utils, file_utils, ticker_mapping
from utils.rates import rbi_rates_utils
from models.purchase import Purchase, Price
from models.itr.faa3 import FAA3


def parse_org_purchases(
    ticker: str,
    calendar_mode: str,
    purchases: t.List[Purchase],
    assessment_year: int,
) -> t.Tuple[t.List[FAA3], t.List[FAA3]]:
    start_time_in_ms, end_time_in_ms = date_utils.calendar_range(
        calendar_mode, assessment_year
    )
    org = ticker_mapping.get_org_info(ticker)
    currency_code = ticker_mapping.get_currency(ticker)

    def is_not_reportable(purchase: Purchase) -> bool:
        # Fully sold, and that sale happened before this reporting period
        # even started - it was never held at any point during the period,
        # so it must not contribute to this year's Schedule FA.
        return (
            purchase.closing_quantity == 0
            and purchase.last_sale_date_in_millis is not None
            and purchase.last_sale_date_in_millis < start_time_in_ms
        )

    before_purchases = list(
        filter(
            lambda purchase: purchase.date["time_in_millis"] < start_time_in_ms
            and not is_not_reportable(purchase),
            purchases,
        )
    )
    after_purchases = list(
        filter(
            lambda purchase: purchase.date["time_in_millis"] >= start_time_in_ms
            and purchase.date["time_in_millis"] <= end_time_in_ms
            and not is_not_reportable(purchase),
            purchases,
        )
    )
    # for a in before_purchases:
    #     t = a.date["disp_time"]
    #     print(f"a = {a.quantity} on da = {t}")

    def closing_quantity(purchase: Purchase) -> float:
        return (
            purchase.closing_quantity
            if purchase.closing_quantity is not None
            else purchase.quantity
        )

    def disposals_in_period(purchase: Purchase):
        return (
            disposal
            for disposal in purchase.disposals
            if start_time_in_ms <= disposal.date["time_in_millis"] <= end_time_in_ms
        )

    def sale_proceeds_in_inr(purchase: Purchase) -> float:
        return sum(
            disposal.quantity
            * disposal.price
            * rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
                currency_code, disposal.date["time_in_millis"]
            )
            for disposal in disposals_in_period(purchase)
        )

    def sale_proceeds_native(purchase: Purchase) -> float:
        return sum(
            disposal.quantity * disposal.price
            for disposal in disposals_in_period(purchase)
        )

    def quantity_sold_in_period(purchase: Purchase) -> float:
        return sum(disposal.quantity for disposal in disposals_in_period(purchase))

    previous_sum = sum(map(lambda purchase: purchase.quantity, before_purchases))
    previous_closing_sum = sum(map(closing_quantity, before_purchases))
    print(
        f"{ticker}: Previous period(before {date_utils.display_time(start_time_in_ms)}) total share = {previous_sum}"
    )

    after_sum = sum(map(lambda purchase: purchase.quantity, after_purchases))
    print(
        f"{ticker}: This period(from {date_utils.display_time(start_time_in_ms)} to {date_utils.display_time(end_time_in_ms)}) total share = {after_sum}"
    )

    closing_rbi_rate = rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
        currency_code, end_time_in_ms
    )
    closing_share_price = share_data_utils.get_closing_price(ticker, end_time_in_ms)
    closing_inr_price = closing_share_price * closing_rbi_rate
    print(
        f"{ticker}: Closing price(INR) = {closing_inr_price}, closing_share_price({currency_code}) = {closing_share_price} closing_rbi_rate(INR) = {closing_rbi_rate}"
    )

    def build_entry(purchase: Purchase) -> FAA3:
        if is_not_reportable(purchase):
            return FAA3(
                org,
                purchase=purchase,
                peak_price=0,
                purchase_price=0,
                closing_price=0,
                sale_proceeds=0,
                purchase_rate=0,
                peak_share_price=0,
                peak_date_in_millis=None,
                peak_rate=0,
                closing_share_price=closing_share_price,
                closing_rate=closing_rbi_rate,
                quantity_sold=0,
                sale_proceeds_native=0,
                comment=(
                    "Sale before start of calendar year - not reported for this period"
                ),
            )

        purchase_rate = rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
            currency_code, purchase.date["time_in_millis"]
        )
        # Peak is always bounded to the reporting period itself, even for a lot
        # acquired years ago - "peak value during the period" means during
        # start_time_in_ms..end_time_in_ms, not since acquisition.
        peak = share_data_utils.get_peak_price_in_inr(
            ticker,
            max(purchase.date["time_in_millis"], start_time_in_ms),
            end_time_in_ms,
        )
        comment = (
            "Sold on/after start of calendar year - reported"
            if purchase.closing_quantity == 0
            and purchase.last_sale_date_in_millis is not None
            else ""
        )
        return FAA3(
            org,
            purchase=purchase,
            peak_price=purchase.quantity * peak["fmv"] * peak["inr_rate"],
            purchase_price=purchase.quantity * purchase.purchase_fmv.price * purchase_rate,
            closing_price=closing_quantity(purchase) * closing_inr_price,
            sale_proceeds=sale_proceeds_in_inr(purchase),
            purchase_rate=purchase_rate,
            peak_share_price=peak["fmv"],
            peak_date_in_millis=peak["entry_time_in_millis"],
            peak_rate=peak["inr_rate"],
            closing_share_price=closing_share_price,
            closing_rate=closing_rbi_rate,
            quantity_sold=quantity_sold_in_period(purchase),
            sale_proceeds_native=sale_proceeds_native(purchase),
            comment=comment,
        )

    # Full, un-clubbed breakdown - one row per actual transaction, each with
    # its own real acquisition date/price - regardless of whether it falls
    # before or during the reporting period. Used for transactions.csv only.
    detailed_entries = [build_entry(purchase) for purchase in purchases]

    # fa_entries.csv keeps its existing convention instead: individual
    # in-period purchases, but prior-period holdings clubbed into a single
    # opening-balance row valued at the period-start FMV. Unchanged from
    # before - this is the upload-ready Schedule FA format.
    fa_entries: t.List[FAA3] = []
    before_purchases_last_date = f"31-Dec-{assessment_year - 2}"
    before_purchase_date = date_utils.parse_named_mon(before_purchases_last_date)
    fmv_price_on_start = share_data_utils.get_fmv(
        ticker, before_purchase_date["time_in_millis"]
    )
    print(
        f"{ticker}: Queried FMV on {before_purchases_last_date} is {fmv_price_on_start}. This is used for accumulated sum for previous purchases"
    )
    if previous_sum != 0:
        previous_purchase_rate = rbi_rates_utils.get_rate_for_prev_mon_for_time_in_ms(
            currency_code, start_time_in_ms
        )
        previous_peak = share_data_utils.get_peak_price_in_inr(
            ticker, start_time_in_ms, end_time_in_ms
        )
        fa_entries.append(
            FAA3(
                org,
                purchase=Purchase(
                    before_purchase_date,
                    Price(
                        fmv_price_on_start,
                        currency_code,
                    ),
                    quantity=previous_sum,
                    ticker=ticker,
                    closing_quantity=previous_closing_sum,
                ),
                purchase_price=previous_sum * fmv_price_on_start * previous_purchase_rate,
                peak_price=previous_sum * previous_peak["fmv"] * previous_peak["inr_rate"],
                closing_price=previous_closing_sum * closing_inr_price,
                sale_proceeds=sum(map(sale_proceeds_in_inr, before_purchases)),
                purchase_rate=previous_purchase_rate,
                peak_share_price=previous_peak["fmv"],
                peak_date_in_millis=previous_peak["entry_time_in_millis"],
                peak_rate=previous_peak["inr_rate"],
                closing_share_price=closing_share_price,
                closing_rate=closing_rbi_rate,
                quantity_sold=sum(map(quantity_sold_in_period, before_purchases)),
                sale_proceeds_native=sum(map(sale_proceeds_native, before_purchases)),
            )
        )

    for purchase in after_purchases:
        fa_entries.append(build_entry(purchase))

    return fa_entries, detailed_entries


FA_ENTRIES_HEADER = [
    "Country/Region name",
    "Country Name and Code",
    "Name of entity",
    "Address of entity",
    "ZIP Code",
    "Nature of entity",
    "Date of acquiring the interest",
    "Initial value of the investment",
    "Peak value of investment during the Period",
    "Closing balance",
    "Total gross amount paid/credited with respect to the holding during the period",
    "Total gross proceeds from sale or redemption of investment during the period",
]


def _fa_entry_row(entry: FAA3) -> tuple:
    return (
        entry.org.country_name,
        entry.org.country_code,
        entry.org.name,
        entry.org.address,
        entry.org.zip_code,
        entry.org.nature,
        # ref https://www.reddit.com/r/IndiaTax/comments/1mhbi0w/a3_template_commonerrorscsv_row_skip_any_idea/
        date_utils.format_time(entry.purchase.date["time_in_millis"], "%Y-%m-%d"),
        round(entry.purchase_price),
        round(entry.peak_price),
        round(entry.closing_price),
        0,
        round(entry.sale_proceeds),
    )


TRANSACTIONS_HEADER = [
    "Ticker",
    "Holding type",
    "Date of acquiring interest",
    "Original quantity",
    "Closing quantity",
    "Quantity sold",
    "Purchase price (native)",
    "Currency",
    "Purchase RBI rate",
    "Peak share price (native)",
    "Peak date",
    "Peak RBI rate",
    "Closing share price (native)",
    "Closing RBI rate",
    "Initial value of investment (INR)",
    "Peak value of investment (INR)",
    "Closing balance (INR)",
    "Sale proceeds (native)",
    "Sale proceeds (INR)",
    "Gain/Loss (native)",
    "Gain/Loss (INR)",
    "Comment",
]


def _transaction_row(entry: FAA3) -> tuple:
    purchase = entry.purchase
    closing_quantity = (
        purchase.closing_quantity
        if purchase.closing_quantity is not None
        else purchase.quantity
    )
    cost_basis_native = entry.quantity_sold * purchase.purchase_fmv.price
    cost_basis_inr = cost_basis_native * entry.purchase_rate
    peak_date_str = (
        date_utils.format_time(entry.peak_date_in_millis, "%Y-%m-%d")
        if entry.peak_date_in_millis is not None
        else ""
    )
    return (
        purchase.ticker,
        purchase.holding_type,
        date_utils.format_time(purchase.date["time_in_millis"], "%Y-%m-%d"),
        purchase.quantity,
        closing_quantity,
        purchase.quantity - closing_quantity,
        purchase.purchase_fmv.price,
        purchase.purchase_fmv.currency_code,
        entry.purchase_rate,
        entry.peak_share_price,
        peak_date_str,
        entry.peak_rate,
        entry.closing_share_price,
        entry.closing_rate,
        round(entry.purchase_price),
        round(entry.peak_price),
        round(entry.closing_price),
        round(entry.sale_proceeds_native, 2),
        round(entry.sale_proceeds),
        round(entry.sale_proceeds_native - cost_basis_native, 2),
        round(entry.sale_proceeds - cost_basis_inr),
        entry.comment,
    )


def parse(
    calendar_mode: str,
    purchases: t.List[Purchase],
    assessment_year: int,
    output_folder_abs_path: str,
):
    ticker_attr = operator.attrgetter("ticker")
    grouped_list = groupby(sorted(purchases, key=ticker_attr), ticker_attr)

    all_fa_entries: t.List[FAA3] = []
    all_detailed_entries: t.List[FAA3] = []
    for ticker, each_org_purchases in grouped_list:
        fa_entries, detailed_entries = parse_org_purchases(
            ticker,
            calendar_mode,
            list(each_org_purchases),
            assessment_year,
        )
        all_fa_entries.extend(fa_entries)
        all_detailed_entries.extend(detailed_entries)

    file_utils.write_to_file(
        output_folder_abs_path,
        "raw_fa_entries.json",
        all_fa_entries,
        True,
    )

    file_utils.write_csv_to_file(
        output_folder_abs_path,
        "transactions.csv",
        TRANSACTIONS_HEADER,
        map(_transaction_row, all_detailed_entries),
        True,
        print_path_to_console=True,
    )

    file_utils.write_csv_to_file(
        output_folder_abs_path,
        "fa_entries.csv",
        FA_ENTRIES_HEADER,
        map(_fa_entry_row, all_fa_entries),
        True,
        print_path_to_console=True,
    )
    return all_fa_entries
