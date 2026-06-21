"""Template helpers for the market templates."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

# Non-breaking space, so a long sum is never split across lines.
_NBSP = " "


@register.filter
def money(value):
    """Format a money amount as ``12 111 111`` (thin spaces, no trailing .00)."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    if amount == amount.to_integral_value():
        text = f"{int(amount):,}"
    else:
        text = f"{amount:,.2f}"
    return text.replace(",", _NBSP)
