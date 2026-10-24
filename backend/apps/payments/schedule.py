"""Расписание сроков регулярного платежа."""

import calendar
from collections.abc import Iterator
from datetime import date


def shift_months(start: date, months: int, anchor_day: int) -> date:
    """
    Дата через `months` месяцев от месяца `start` на число `anchor_day`.
    Нет такого числа в месяце — последний день месяца (31 янв → 28/29 фев → 31 мар).
    """
    total = start.year * 12 + (start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def due_dates(first_due_date: date, step_months: int, anchor_day: int) -> Iterator[date]:
    """Последовательность сроков, начиная с `first_due_date`, до конца 9999 года (date.max)."""
    index = 0
    while True:
        try:
            due_date = shift_months(first_due_date, index * step_months, anchor_day)
        except ValueError:
            # Дальше 9999 года дат нет: итоги за декабрь 9999 падали с 500.
            return
        yield due_date
        index += 1
