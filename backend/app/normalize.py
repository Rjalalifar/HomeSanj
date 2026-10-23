"""Lossless unit normalization for rental listings and supported query examples."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك', '01234567890123456789یک')


def normalize_text(value: str) -> str:
    text = unicodedata.normalize('NFKC', str(value)).translate(DIGITS)
    return ' '.join(text.replace('\u200c', ' ').replace('\u200f', '').split())


def parse_money(value, unit: str = 'toman') -> int | None:
    if value is None or str(value).strip() in ('', 'null', 'None', 'نامشخص'):
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not money')
    text = normalize_text(str(value)).lower().replace('٬', '').replace(',', '').replace('٫', '.')
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(میلیارد|میلیون|هزار)?\s*(تومان|ریال|toman|rial)?\s*', text)
    if not match:
        raise ValueError('Unrecognized monetary value')
    number, magnitude, explicit_unit = match.groups()
    scale = {None: 1, 'هزار': 1000, 'میلیون': 10**6, 'میلیارد': 10**9}[magnitude]
    currency = explicit_unit or unit
    if currency not in ('rial', 'ریال', 'toman', 'تومان'):
        raise ValueError('Unknown currency')
    amount = Decimal(number) * scale / (10 if currency in ('rial', 'ریال') else 1)
    if amount != amount.to_integral_value():
        raise ValueError('Money must resolve to integer toman without rounding')
    if amount > 9_000_000_000_000_000:
        raise ValueError('Money exceeds supported range')
    return int(amount)


def parse_number(value, integer=False):
    if value is None or str(value).strip() in ('', 'null', 'نامشخص'):
        return None
    try:
        number = Decimal(normalize_text(str(value)).replace('٫', '.').replace(',', '').replace('٬', ''))
    except InvalidOperation as exc:
        raise ValueError('Unrecognized number') from exc
    if not number.is_finite() or number < 0 or (integer and number != number.to_integral_value()):
        raise ValueError('Invalid nonnegative number')
    return int(number) if integer else float(number)


def parse_bool(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return value
    text = normalize_text(str(value)).lower()
    if text in ('true', '1', 'بله', 'دارد'):
        return True
    if text in ('false', '0', 'خیر', 'ندارد'):
        return False
    if text in ('null', 'نامشخص'):
        return None
    raise ValueError('Unrecognized boolean')
