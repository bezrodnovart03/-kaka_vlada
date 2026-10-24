# План: дополнительные возможности (ветка `future-test`)

> **Статус: все этапы выполнены и проверены.** 103 теста (было 78), ruff, mypy strict,
> pre-commit, `npm run build`; живой прогон: письмо через SMTP (Mailpit) с `.ics`, webhook
> с проверкой HMAC-подписи на локальном приёмнике, Apprise; UI вложений и экспорт `.ics`
> в браузере, включая мобильную ширину. Schemathesis по всем эндпоинтам без ошибок; он же нашёл
> две ошибки (500 на id больше int64 и на битом multipart) — исправлены, на них есть тесты.

Кейс (стр. 16) называет девять дополнительных возможностей. Состояние на старте ветки:

| Возможность | Было | Что делаем |
|---|---|---|
| Календарь оплат | есть (`CalendarPage`) | + экспорт `.ics` для Google/Apple/Outlook-календаря |
| Email-оповещения через SMTP | нет | канал `email` |
| Webhook на указанный адрес | нет | канал `webhook` (JSON + HMAC-подпись) |
| Другие каналы | нет | канал `apprise`: Discord, Slack, ntfy, Matrix, MS Teams и ещё ~100 сервисов одной строкой URL |
| Логи авторизации и действий | только консоль | + ротация в файл `LOG_FILE`, логи доставки по каналам |
| Кнопка «Оплачено» в Telegram | есть | — |
| Бюджет на месяц и год | есть | — |
| Чек или ссылка к оплате | нет | вложения периода: файл (PDF/изображение) или ссылка |
| Проработанный UX/UI | есть | UI для вложений, кнопка экспорта календаря, каналы в строке периода |

## Этапы

Каждый этап закрывается проверкой: `manage.py test`, `ruff check`, `ruff format --check`,
`mypy` (strict), `makemigrations --check`; для фронта — `npm run build`; в конце — живая
проверка в браузере и регенерация `openapi.json`.

### 1. Каналы напоминаний (email, webhook, apprise)

- Настройки в `.env` (pydantic-settings): `EMAIL_*`, `REMINDER_EMAIL_TO`, `REMINDER_EMAIL_TO_USERS`,
  `WEBHOOK_URL`, `WEBHOOK_SECRET`, `NOTIFY_URLS`.
- Модель `ReminderDelivery(occurrence, channel, sent_at)` с уникальностью `(occurrence, channel)`:
  без дублей в каждом канале отдельно. Захват — INSERT (второй процесс получит IntegrityError),
  при ошибке отправки запись удаляется и следующая проверка повторит. Telegram продолжает
  работать на `reminder_sent_at`, как раньше.
- Email: HTML + текст, во вложении `.ics` с событием на срок оплаты (библиотека `icalendar`).
- Webhook: `httpx`, JSON-событие `payment.reminder`, заголовок `X-Invoice-Keeper-Signature`
  (HMAC-SHA256 тела по `WEBHOOK_SECRET`).
- Apprise (`apprise`): список URL сервисов, сообщение в Markdown.
- Напоминание «сразу», если платёж создан позже чем за 3 дня, работает для всех каналов.
- `manage.py check_channels` — тестовое сообщение во все настроенные каналы.
- API: в периоде поле `reminders` — по каким каналам и когда ушло напоминание.
- Тесты: доставка в каждый канал, отсутствие дублей, повтор после ошибки, оплаченный и
  удалённый платежи не напоминают, подпись webhook.

### 2. Чек или ссылка к конкретной оплате

- Модель `PaymentAttachment(occurrence, kind=file|link, file, url, name, content_type, size,
  uploaded_by, created_at)`; файл удаляется с диска вместе с записью.
- Эндпоинты (у пользователя и админа):
  - `GET    /api/v1/payment-occurrences/{id}/attachments`
  - `POST   /api/v1/payment-occurrences/{id}/attachments/file` (multipart)
  - `POST   /api/v1/payment-occurrences/{id}/attachments/link`
  - `GET    /api/v1/payment-occurrences/{id}/attachments/{attachment_id}/download`
  - `DELETE /api/v1/payment-occurrences/{id}/attachments/{attachment_id}` (автор или админ)
- Проверки: размер (`ATTACHMENT_MAX_MB`), тип по содержимому (библиотека `filetype`:
  PDF, PNG, JPEG, WebP, HEIC), ссылки только `http(s)`. Файлы не раздаются статикой —
  только через эндпоинт с авторизацией.
- В периоде поле `attachments_count`; аудит-лог загрузок и удалений; админка.
- Тесты: права, валидация, скачивание, удаление файла с диска.

### 3. Экспорт календаря

- `GET /api/v1/payment-occurrences/calendar.ics` — периоды в формате iCalendar
  (фильтры как у списка), событие на весь день срока с напоминанием за 3 дня.

### 4. Логи в файл

- `LOG_FILE` (необязательно): `RotatingFileHandler`, 5 МБ × 5 файлов, логгеры `audit` и `apps`.

### 5. Фронтенд

- Диалог «Вложения» у периода: список, загрузка файла (drag & drop), ссылка, скачивание, удаление.
- В строке периода: 📎 N и каналы, в которые ушло напоминание.
- Кнопка «Скачать .ics» на странице календаря.

### 6. Документация и итоговая проверка

- `README.md`, `docs/API.md`, `.env.example`, регенерация `openapi.json`.
- `seed_demo`: ссылка-чек у оплаченного периода.
- Полный прогон проверок, Schemathesis по новым эндпоинтам, проверка в браузере.
