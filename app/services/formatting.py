from decimal import Decimal
from numbers import Real


def format_currency(value: Real | Decimal | None, decimals: int = 0) -> str:
    """Format a monetary value as Indian Rupees with lakh/crore grouping."""
    if value is None:
        value = 0
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError):
        amount = Decimal("0")
    quantizer = Decimal(1).scaleb(-decimals)
    amount = amount.quantize(quantizer)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    rendered = f"{amount:.{decimals}f}"
    integer, _, fraction = rendered.partition(".")
    if len(integer) > 3:
        last_three = integer[-3:]
        remaining = integer[:-3]
        groups = []
        while remaining:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        integer = ",".join(groups + [last_three])
    suffix = f".{fraction}" if decimals else ""
    return f"₹{sign}{integer}{suffix}"


def format_currency_columns(frame, columns: list[str], decimals: int = 0):
    """Return a copy with selected monetary columns rendered as INR strings."""
    formatted = frame.copy()
    for column in columns:
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: format_currency(value, decimals))
    return formatted
