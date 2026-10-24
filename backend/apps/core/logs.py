"""Просмотр логов (LOG_FILE) в Django-админке: последние записи с фильтром по уровню и тексту."""

import re
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse

# Хвост файла, который читаем: ~2–3 тыс. записей, без чтения всего файла с диска.
TAIL_BYTES = 512 * 1024
LIMITS = (100, 300, 1000)
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
# Запись начинается с "{asctime} {levelname} {name}: …" (LOGGING в settings);
# строки без такого начала (traceback) относятся к предыдущей записи.
RECORD_START = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (?P<level>[A-Z]+) (?P<logger>\S+): "
)


def read_tail(path: Path, size: int = TAIL_BYTES) -> list[str]:
    with path.open("rb") as file:
        file.seek(0, 2)
        start = max(0, file.tell() - size)
        file.seek(start)
        data = file.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    # Первая строка хвоста, скорее всего, обрезана посередине.
    return lines[1:] if start else lines


def parse_records(lines: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in lines:
        match = RECORD_START.match(line)
        if match:
            records.append(
                {
                    "time": match["time"],
                    "level": match["level"],
                    "logger": match["logger"],
                    "message": line[match.end() :],
                }
            )
        elif records:
            records[-1]["message"] += "\n" + line
    return records


def logs_view(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        raise PermissionDenied
    level = request.GET.get("level", "")
    query = request.GET.get("q", "").strip()
    try:
        limit = int(request.GET.get("limit", LIMITS[1]))
    except ValueError:
        limit = LIMITS[1]
    limit = limit if limit in LIMITS else LIMITS[1]

    path: Path | None = settings.LOG_FILE
    records: list[dict[str, str]] = []
    error = ""
    if path is None:
        error = "Логи пишутся только в консоль: задайте LOG_FILE в переменных окружения."
    elif not path.exists():
        error = f"Файл {path.name} ещё не создан — записей пока нет."
    else:
        records = parse_records(read_tail(path))
        if level in LEVELS:
            minimum = LEVELS.index(level)
            records = [r for r in records if r["level"] in LEVELS[minimum:]]
        if query:
            needle = query.casefold()
            records = [r for r in records if needle in f"{r['logger']} {r['message']}".casefold()]
        # Свежие сверху.
        records = records[::-1][:limit]

    context = {
        **admin.site.each_context(request),
        "title": "Логи",
        "records": records,
        "error": error,
        "levels": LEVELS,
        "limits": LIMITS,
        "level": level,
        "query": query,
        "limit": limit,
        "file_name": path.name if path else "",
    }
    return TemplateResponse(request, "admin/logs.html", context)
