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
    """Бесконечная последовательность сроков, начиная с `first_due_date`."""
    index = 0
    while True:
        yield shift_months(first_due_date, index * step_months, anchor_day)
        index += 1
