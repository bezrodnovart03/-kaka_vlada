"""
Дашборд на главной админки (Unfold DASHBOARD_CALLBACK, шаблон templates/admin/index.html).
https://unfoldadmin.com/docs/configuration/dashboard/
"""

import calendar
import json
from datetime import date, timedelta
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.safestring import SafeString

from apps.core.schemas import local_today

from . import services
from .admin import CURRENCY_SIGNS, money
from .models import Currency, OccurrenceStatus, PaymentOccurrence, RecurringPayment
from .schedule import shift_months

UPCOMING_DAYS = 14
LIST_LIMIT = 8


def overdue_occurrences(today: date) -> QuerySet[PaymentOccurrence]:
    """Неоплаченные периоды активных платежей со сроком раньше сегодня."""
    return PaymentOccurrence.objects.filter(
        status=OccurrenceStatus.UNPAID,
        due_date__lt=today,
        recurring_payment__deleted_at__isnull=True,
    )


def upcoming_occurrences(today: date) -> QuerySet[PaymentOccurrence]:
    return PaymentOccurrence.objects.filter(
        status=OccurrenceStatus.UNPAID,
        due_date__gte=today,
        due_date__lte=today + timedelta(days=UPCOMING_DAYS),
        recurring_payment__deleted_at__isnull=True,
    )


def _month_bounds(today: date) -> tuple[date, date]:
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last_day)


def _payment_link(occurrence: PaymentOccurrence) -> SafeString:
    url = reverse("admin:payments_paymentoccurrence_change", args=[occurrence.pk])
    return format_html(
        '<a href="{}" class="text-primary-600">{}</a>', url, occurrence.recurring_payment.title
    )


def _days_word(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return "день"
    if days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def _when(due_date: date, today: date) -> str:
    days = (due_date - today).days
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {days} {_days_word(days)}"


def _date(value: date) -> str:
    return date_format(value, "j E")


def _totals_table(today: date) -> dict[str, Any]:
    date_from, date_to = _month_bounds(today)
    summary = services.summarize(date_from, date_to, today)
    rows = []
    for totals in summary.totals:
        currency = totals.currency
        rows.append(
            [
                format_html("<strong>{}</strong>", currency),
                money(totals.planned, currency),
                f"{money(totals.paid, currency)} ({totals.count_paid} из {totals.count_planned})",
                money(totals.unpaid, currency),
                format_html(
                    '<span class="{}">{}</span>',
                    "text-red-600" if totals.count_overdue else "",
                    money(totals.overdue, currency),
                ),
            ]
        )
    return {
        "headers": ["Валюта", "План", "Оплачено", "К оплате", "Просрочено"],
        "rows": rows,
    }


def _upcoming_table(today: date) -> dict[str, Any]:
    occurrences = upcoming_occurrences(today).select_related("recurring_payment")
    return {
        "headers": ["Платёж", "Срок", "Сумма"],
        "rows": [
            [
                _payment_link(o),
                f"{_date(o.due_date)} · {_when(o.due_date, today)}",
                money(o.amount, o.currency),
            ]
            for o in occurrences.order_by("due_date", "id")[:LIST_LIMIT]
        ],
    }


def _overdue_table(today: date) -> dict[str, Any]:
    occurrences = overdue_occurrences(today).select_related("recurring_payment")
    return {
        "headers": ["Платёж", "Срок", "Сумма", "Просрочка"],
        "rows": [
            [
                _payment_link(o),
                _date(o.due_date),
                money(o.amount, o.currency),
                format_html(
                    '<span class="text-red-600">{} {}</span>',
                    o.overdue_days,
                    _days_word(o.overdue_days),
                ),
            ]
            for o in occurrences.order_by("due_date", "id")[:LIST_LIMIT]
        ],
    }


# ── диаграммы (unfold/components/chart/bar.html, Chart.js) ──────────────
# https://unfoldadmin.com/docs/components/chart/

CHART_MONTHS_BACK = 6
CHART_MONTHS_AHEAD = 5

# Стиль осей как у Unfold по умолчанию; свои options заменяют его целиком,
# поэтому повторяем нужное и включаем stacked.
_AXIS_COLOR = "#9ca3af"
STACKED_BAR_OPTIONS = {
    "animation": False,
    "responsive": True,
    "maintainAspectRatio": False,
    "plugins": {
        "legend": {
            "align": "end",
            "labels": {
                "boxHeight": 8,
                "boxWidth": 8,
                "color": _AXIS_COLOR,
                "pointStyle": "circle",
                "usePointStyle": True,
            },
        },
        "tooltip": {"mode": "index", "intersect": False},
    },
    "datasets": {"bar": {"borderRadius": 4, "maxBarThickness": 18}},
    "scales": {
        "x": {
            "stacked": True,
            "border": {"width": 0},
            "grid": {"display": False},
            "ticks": {"color": _AXIS_COLOR},
        },
        "y": {
            "stacked": True,
            "beginAtZero": True,
            "border": {"width": 0},
            "grid": {},
            "ticks": {"color": _AXIS_COLOR, "precision": 0},
        },
    },
}


def _chart_months(today: date) -> list[date]:
    """Первые числа месяцев: CHART_MONTHS_BACK назад, текущий и CHART_MONTHS_AHEAD вперёд."""
    first = today.replace(day=1)
    return [
        shift_months(first, offset, 1)
        for offset in range(-CHART_MONTHS_BACK, CHART_MONTHS_AHEAD + 1)
    ]


def _month_label(month: date) -> str:
    return f"{date_format(month, 'M')} {month:%y}"


def _status_chart(today: date, months: list[date]) -> str:
    """Периоды по месяцам срока: вовремя / с опозданием / просрочено / ожидает."""
    buckets = {key: [0] * len(months) for key in ("on_time", "late", "overdue", "pending")}
    index = {(m.year, m.month): i for i, m in enumerate(months)}
    window_end = _month_bounds(months[-1])[1]

    occurrences = PaymentOccurrence.objects.filter(
        due_date__gte=months[0], due_date__lte=window_end
    ).only("due_date", "status", "paid_at")
    for occurrence in occurrences:
        i = index[(occurrence.due_date.year, occurrence.due_date.month)]
        if occurrence.is_paid:
            buckets["late" if occurrence.overdue_days else "on_time"][i] += 1
        elif occurrence.due_date < today:
            buckets["overdue"][i] += 1
        else:
            buckets["pending"][i] += 1

    datasets = [
        ("on_time", "Оплачено вовремя", "var(--color-green-500)"),
        ("late", "Оплачено с опозданием", "var(--color-orange-400)"),
        ("overdue", "Просрочено", "var(--color-red-500)"),
        ("pending", "Ожидает оплаты", "var(--color-base-300)"),
    ]
    return json.dumps(
        {
            "labels": [_month_label(m) for m in months],
            "datasets": [
                {"label": label, "data": buckets[key], "backgroundColor": color}
                for key, label, color in datasets
            ],
        }
    )


def _currency_charts(today: date, months: list[date]) -> list[dict[str, Any]]:
    """План и оплачено по месяцам — отдельная диаграмма на валюту (суммы не складываются)."""
    summaries = [services.summarize(*_month_bounds(m), today) for m in months]
    charts = []
    for currency in Currency.values:
        planned = [float(s.totals_for(currency).planned) for s in summaries]
        paid = [float(s.totals_for(currency).paid) for s in summaries]
        if not any(planned):
            continue
        sign = CURRENCY_SIGNS.get(currency, currency)
        charts.append(
            {
                "currency": currency,
                "data": json.dumps(
                    {
                        "labels": [_month_label(m) for m in months],
                        # Unfold рисует столбцы поверх друг друга (grouped: false), первый
                        # набор — сверху: «оплачено» заливает столбец «плана».
                        "datasets": [
                            {
                                "label": "Оплачено",
                                "data": paid,
                                "backgroundColor": "var(--color-primary-600)",
                                "displayYAxis": True,
                                "suffixYAxis": sign,
                            },
                            {
                                "label": "План",
                                "data": planned,
                                "backgroundColor": "var(--color-base-300)",
                            },
                        ],
                    }
                ),
            }
        )
    return charts


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    today = local_today()
    month_from, month_to = _month_bounds(today)
    month_occurrences = PaymentOccurrence.objects.filter(
        due_date__gte=month_from, due_date__lte=month_to
    )
    occurrences_url = reverse("admin:payments_paymentoccurrence_changelist")
    chart_months = _chart_months(today)

    context.update(
        {
            "today": today,
            "month_title": date_format(today, "F Y").lower(),  # «Итоги за октябрь 2026»
            "kpi": [
                {
                    "title": "Просрочено периодов",
                    "value": overdue_occurrences(today).count(),
                    "danger": True,
                    "href": occurrences_url,
                },
                {
                    "title": f"К оплате в ближайшие {UPCOMING_DAYS} дней",
                    "value": upcoming_occurrences(today).count(),
                    "href": occurrences_url,
                },
                {
                    "title": "Оплачено в этом месяце",
                    "value": (
                        f"{month_occurrences.filter(status=OccurrenceStatus.PAID).count()}"
                        f" из {month_occurrences.count()}"
                    ),
                    "href": occurrences_url,
                },
                {
                    "title": "Активных платежей",
                    "value": RecurringPayment.objects.filter(deleted_at__isnull=True).count(),
                    "href": reverse("admin:payments_recurringpayment_changelist"),
                },
            ],
            "totals_table": _totals_table(today),
            "upcoming_table": _upcoming_table(today),
            "overdue_table": _overdue_table(today),
            "upcoming_days": UPCOMING_DAYS,
            "status_chart": _status_chart(today, chart_months),
            "status_chart_options": json.dumps(STACKED_BAR_OPTIONS),
            "currency_charts": _currency_charts(today, chart_months),
        }
    )
    return context
