"""Общее оформление напоминаний для всех каналов."""

from datetime import date
from decimal import Decimal

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€"}


def format_money(amount: Decimal, currency: str) -> str:
    whole, _, cents = f"{amount:,.2f}".partition(".")
    return f"{whole.replace(',', ' ')},{cents} {CURRENCY_SIGNS.get(currency, '')} {currency}"


def format_due(due_date: date, today: date) -> str:
    days = (due_date - today).days
    when = {0: "сегодня", 1: "завтра"}.get(days)
    if when is None:
        when = f"через {days} дн." if days > 0 else f"просрочено на {-days} дн."
    return f"{due_date:%d.%m.%Y} ({when})"
