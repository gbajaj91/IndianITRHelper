from dataclasses import dataclass, field
import typing as t
from utils.date_utils import DateObj


@dataclass
class Price:
    price: float
    currency_code: str


@dataclass
class Disposal:
    """A sell event that consumed some (or all) of a Purchase lot."""

    date: DateObj
    quantity: float
    price: float  # per-share sale price, same currency as the lot's purchase_fmv


@dataclass
class Purchase:
    date: DateObj
    purchase_fmv: Price
    quantity: float
    ticker: str
    # Remaining quantity as of the reporting period end, when it differs from
    # `quantity` (the originally acquired amount) because some of it was later
    # sold. None means "unchanged from quantity" (e.g. sources that don't
    # track sells, like etrade).
    closing_quantity: t.Optional[float] = None
    # Sell events that consumed part (or all) of this lot, in chronological
    # order. Empty for sources that don't track sells (e.g. etrade).
    disposals: t.List[Disposal] = field(default_factory=list)
    # What kind of holding this lot is, e.g. "RSU", "ESPP", "Trade" - set by
    # the source parser that created this Purchase.
    holding_type: str = ""
    # Most recent date this lot was (partly or fully) sold, when known but
    # the sale's quantity/price aren't tracked in enough detail to populate
    # `disposals` (e.g. ESPP, where only "fully sold, as of this date" is
    # available). None if not sold, or if the source doesn't track this.
    last_sale_date_in_millis: t.Optional[int] = None
