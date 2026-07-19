from dataclasses import dataclass

from utils.date_utils import DateObj


@dataclass
class DividendEvent:
    """A single cash event tied to a ticker holding, not any specific lot -
    either a dividend payment received, or the tax withheld against one.
    `amount` is always a positive magnitude in the holding's native currency.
    """

    date: DateObj
    ticker: str
    amount: float
    currency: str
