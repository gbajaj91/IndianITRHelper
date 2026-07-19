from dataclasses import dataclass
import typing as t
from models.org import Organization
from models.purchase import Purchase


@dataclass
class FAA3:
    org: Organization
    purchase: Purchase
    purchase_price: float
    peak_price: float
    closing_price: float
    # Gross proceeds (in INR) from sells of this holding that fall within the
    # reporting period. 0 for sources that don't track sells (e.g. etrade).
    sale_proceeds: float = 0
    # Underlying components behind purchase_price/peak_price/closing_price,
    # kept around purely so the transactions (workings) sheet can show its
    # math for validation. Not used in the fa_entries upload format.
    purchase_rate: float = 0
    peak_share_price: float = 0
    peak_date_in_millis: t.Optional[int] = None
    peak_rate: float = 0
    closing_share_price: float = 0
    closing_rate: float = 0
    # Quantity sold, and gross sale proceeds in the sale's native currency
    # (unconverted), within the reporting period. Used with purchase_rate to
    # compute realized gain/loss in both native currency and INR.
    quantity_sold: float = 0
    sale_proceeds_native: float = 0
    # Explains why a value was zeroed out (not reportable this period) or
    # why it's included despite being fully sold. Blank when not applicable.
    comment: str = ""
