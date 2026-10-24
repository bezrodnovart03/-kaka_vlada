# Invoice Keeper

Сервис-напоминалка о регулярных платежах: аренда, подписки, оплата серверов и другие периодические расходы.
Администратор заводит платежи, за 3 дня до срока бот пишет в Telegram-чат, а команда отмечает оплату и следит за просрочками.

Проект сделан для кейса «Invoice Keeper» на хакатоне РнД (уровень Middle).

## Возможности

- **Веб-панель с авторизацией.** Без входа ни панель, ни API не отдают данные.
- **Две роли.**
  - Администратор задаётся через `.env`. Он управляет регулярными платежами и обычными пользователями. Его учётную запись через панель изменить нельзя.
  - Пользователь видит общий список платежей, отмечает оплату и указывает или исправляет фактическую дату оплаты.
  - Права проверяются и в панели, и в API: пользователь на действия администратора получает 403 ещё до разбора тела запроса.
- **Регулярные платежи.** У платежа есть название, сумма, валюта, дата ближайшей оплаты и периодичность (ежемесячно, ежеквартально, ежегодно). Если в месяце нет нужного числа, срок переносится на последний день месяца (31 янв → 28 фев → 31 мар).
- **Периоды (occurrences).** У каждого периода своя дата и своя отметка «Оплачено / Не оплачено». Новый период не стирает прошлые оплаты, а просрочка не останавливает следующие периоды.
- **Статусы и просрочка.**
  - Просрочка начинается со следующего дня после срока. Оплата в день срока считается вовремя.
  - Если отменить отметку об оплате, фактическая дата очищается.
  - Если исправить фактическую дату, просрочка пересчитывается, а срок остаётся прежним.
- **Telegram-напоминания.** Бот пишет минимум за 3 дня до срока: название, сумму, валюту и дату.
  - Дублей нет: период «захватывается» атомарным UPDATE, повторная проверка второе сообщение не отправит. За оплаченный период напоминаний нет.
  - Если платёж добавлен меньше чем за 3 дня до срока, напоминание уходит сразу.
  - Удалённый платёж больше не напоминает.
  - Если Telegram недоступен, отметка снимается, и следующая проверка повторит отправку.
- **Три валюты: RUB, USD, EUR.** Итоги считаются отдельно по каждой валюте, без конвертации.
- **История изменений.** Изменения платежей, оплат и пользователей пишутся в журнал через `django-simple-history` (с автором изменения), смотреть — в Django-админке.
- **Единый часовой пояс** задаётся в `.env`.

### Дополнительно

- **Кнопка «Оплачено» прямо в сообщении бота** — отмечает период оплаченным сегодняшней датой и дописывает в сообщение, кто отметил.
- **Календарь оплат** — периоды на сетке месяца, клик открывает отметку оплаты. Кнопка «📅 Экспорт .ics» скачивает сроки для Google / Apple / Outlook-календаря: оплаченные с ✅, будущие — по расписанию на год вперёд, у неоплаченных — оповещение за 3 дня.
- **Итоги на дату и бюджет на месяц / год** по каждой валюте; будущие сроки считаются по расписанию, даже если периоды ещё не созданы.
- **Email-оповещения через SMTP** — письмо (текст + HTML) каждому получателю отдельно, во вложении `.ics` со сроком. Получатели — список из `.env` и/или email активных пользователей.
- **Webhook на указанный адрес** — JSON-событие `payment.reminder` с подписью HMAC-SHA256 (`X-Invoice-Keeper-Signature: sha256=…`) и ключом идемпотентности `X-Invoice-Keeper-Delivery`.
- **Другие каналы** через [Apprise](https://github.com/caronc/apprise): Discord, Slack, ntfy, Matrix, MS Teams, Pushover и ещё ~100 сервисов — одной строкой URL в `NOTIFY_URLS`.
  - Правила напоминаний одинаковы во всех каналах: за 3 дня, без дублей (в каждом канале своя отметка), оплаченный и удалённый платёж не напоминает, сбой одного канала не мешает остальным и повторяется на следующей проверке. В строке периода видно, в какие каналы ушло напоминание.
- **Чек или ссылка к конкретной оплате** — кнопка «📎» у периода: файл (PDF, PNG, JPEG, WebP, HEIC; тип проверяется по содержимому, до 10 МБ, drag & drop) или ссылка `http(s)`. Файлы отдаются только через API с авторизацией; удалить может автор или администратор.
- **Логи** входа и действий (создание и удаление платежей, отметки оплаты, вложения, управление пользователями, доставка напоминаний) — логгер `audit` в консоль сервера и, если задан `LOG_FILE`, в файл с ротацией (5 МБ × 5). Журнал доставок и вложений — в Django-админке.
- **UX:** фильтры «Просроченные / Предстоящие / Оплаченные», подсветка просрочек, подсказки «через 2 дня», тёмная тема, адаптивная вёрстка.

## Стек

| Часть | Технологии |
|---|---|
| Backend | Python 3.14, Django 6.0, django-ninja (REST API + OpenAPI/Swagger), django-ninja-jwt, django-simple-history, django-unfold (админка), pydantic-settings |
| Frontend | React 18, TypeScript, Vite, react-router |
| Бот | Telegram Bot API (stdlib, без сторонних библиотек) |
| Каналы и файлы | Django email (SMTP), [httpx](https://www.python-httpx.org/) (webhook), [Apprise](https://github.com/caronc/apprise) (другие сервисы), [icalendar](https://icalendar.readthedocs.io/) (`.ics`), [filetype](https://github.com/h2non/filetype.py) (тип файла по содержимому) |
| Качество | ruff (линтер + форматтер), mypy `strict` с плагинами django и pydantic, pre-commit, Django TestCase |
| Пакеты (backend) | [uv](https://docs.astral.sh/uv/) |
| Запуск | Docker Compose: PostgreSQL 17, gunicorn, nginx |

## Структура репозитория

```
.
├── backend/                  # Django + django-ninja API
│   ├── apps/users/           # пользователи, JWT-авторизация, управление пользователями
│   ├── apps/payments/        # регулярные платежи, периоды, итоги, seed_demo
│   ├── apps/notifications/   # Telegram: напоминания, кнопка «Оплачено», run_reminders
│   └── openapi.json          # OpenAPI-спецификация
├── frontend/                 # React SPA (веб-панель)
├── docs/API.md               # контракт API (back ↔ front)
└── README.md
```

## Быстрый старт

### Запуск в Docker (одной командой)

Нужен только Docker с Compose v2.

```bash
cp backend/.env.example backend/.env   # заполнить SECRET_KEY, ADMIN_*, TELEGRAM_*
docker compose up -d --build
```

- Панель — http://localhost:8080, админка — http://localhost:8080/admin/, Swagger — http://localhost:8080/api/v1/docs.
- Демо-данные: `SEED_DEMO=1 docker compose up -d` (только при пустой базе) или `docker compose exec backend python manage.py seed_demo --reset`.
- Логи: `docker compose logs -f backend reminders`. Остановить: `docker compose down`; удалить ещё и данные: `docker compose down -v`.

| Сервис | Что делает |
|---|---|
| `db` | PostgreSQL 17, данные в томе `pgdata` |
| `backend` | Django + gunicorn; при старте `migrate` (админ из `.env`) и `collectstatic` |
| `reminders` | `run_reminders`: напоминания во все каналы и кнопка «Оплачено» в Telegram |
| `frontend` | nginx: React-панель, прокси `/api` и `/admin`, статика админки |
| `mailpit` | SMTP-сервер стека: принимает всю почту приложения, письма видны на http://localhost:8025 и наружу не уходят (хранятся в томе `mailpit`) |

Переменные приложения берутся из `backend/.env`. Compose в контейнерах переопределяет БД (PostgreSQL), SMTP (Mailpit), `DEBUG=False` и пути. Параметры самого Compose задаются в окружении или в файле `.env` рядом с `compose.yaml`:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `APP_PORT` | `8080` | Порт панели на хосте |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `invoice_keeper` | БД; наружу порт не открыт |
| `ALLOWED_HOSTS` | `["localhost","127.0.0.1","backend"]` | Добавьте свой домен |
| `CSRF_TRUSTED_ORIGINS` | `[]` | Для админки за HTTPS-прокси: `["https://example.com"]` |
| `JWT_REFRESH_COOKIE_SECURE` | `false` | `true`, если панель открывается по HTTPS |
| `PANEL_URL` | `http://localhost:8080` | Ссылка на панель в напоминаниях |
| `SEED_DEMO` | `0` | `1` — демо-данные при первом старте |
| `GUNICORN_WORKERS` | `2` | Процессы gunicorn |
| `CLIENT_MAX_BODY_SIZE` | `12m` | Лимит тела запроса в nginx (чеки до `ATTACHMENT_MAX_MB`) |
| `BACKEND_ENV_FILE` | `backend/.env` | Другой env-файл приложения |
| `MAILPIT_PORT` | `8025` | Порт веб-интерфейса почты на хосте |
| `EMAIL_HOST` / `EMAIL_PORT` | `mailpit` / `1025` | SMTP для контейнеров; задайте, чтобы слать через настоящий сервер |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | `false` / `false` | Шифрование SMTP |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | пусто | Логин и пароль SMTP |
| `EMAIL_FROM` | `Invoice Keeper <noreply@invoice-keeper.local>` | Отправитель |

Email-напоминания в Docker работают сразу: почта идёт в Mailpit. Включаются они получателями в `backend/.env`: `REMINDER_EMAIL_TO=["team@example.com"]` и/или `REMINDER_EMAIL_TO_USERS=true` (email активных пользователей). Проверка: `docker compose exec backend python manage.py check_channels` — тестовое письмо появится на http://localhost:8025. Чтобы письма уходили на настоящие ящики, задайте `EMAIL_*` из таблицы, например для Яндекса: `EMAIL_HOST=smtp.yandex.ru`, `EMAIL_PORT=465`, `EMAIL_USE_SSL=true`, логин и пароль приложения.

У контейнеров заданы лимиты CPU и памяти. Процессы работают от непривилегированного пользователя. Чеки лежат в томе `media` и наружу не раздаются — только через API с авторизацией.

### Требования для запуска без Docker

- Python 3.14+ и [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20+ и npm
- Токен Telegram-бота (от [@BotFather](https://t.me/BotFather)) и id чата, куда слать напоминания

### 1. Переменные окружения

```bash
cp backend/.env.example backend/.env
```

Заполните `backend/.env`:

| Переменная | Описание | Пример |
|---|---|---|
| `SECRET_KEY` | Секретный ключ Django и подпись JWT (не короче 32 символов) | `uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `DEBUG` | Режим отладки | `True` |
| `ALLOWED_HOSTS` | Разрешённые хосты (JSON-список) | `["localhost","127.0.0.1"]` |
| `TIME_ZONE` | Единый часовой пояс системы | `Europe/Moscow` |
| `DB_ENGINE` | Движок БД | `django.db.backends.sqlite3` |
| `DB_NAME` | Имя БД (для SQLite — файл в `backend/`) | `db.sqlite3` |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` | Подключение к сетевой БД | — |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | Время жизни access-токена | `30` |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | Время жизни refresh-токена | `7` |
| `JWT_REFRESH_COOKIE_SECURE` | Флаг `Secure` у refresh-cookie (по умолчанию `not DEBUG`) | `false` |
| `ADMIN_USERNAME` | Логин администратора | `admin` |
| `ADMIN_PASSWORD` | Пароль администратора | `change-me` |
| `ADMIN_EMAIL` | Email администратора | — |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | Чат для напоминаний | `-1001234567890` |
| `REMINDER_DAYS_BEFORE` | За сколько дней напоминать | `3` |
| `REMINDER_CHECK_INTERVAL_SECONDS` | Как часто проверять сроки, секунд | `60` |
| `TELEGRAM_PAY_BUTTON` | Кнопка «Оплачено» в сообщении | `true` |
| `PANEL_URL` | Ссылка на панель в напоминании (необязательно) | `http://localhost:5173` |
| `EMAIL_HOST`, `EMAIL_PORT` | SMTP-сервер | `smtp.yandex.ru`, `465` |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Логин и пароль SMTP (для Яндекса/Gmail — пароль приложения) | — |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | STARTTLS (порт 587) или SSL (порт 465), не оба сразу | `true` / `false` |
| `EMAIL_FROM` | Отправитель | `Invoice Keeper <bot@example.com>` |
| `REMINDER_EMAIL_TO` | Получатели напоминаний (JSON-список); пусто — email выключен | `["team@example.com"]` |
| `REMINDER_EMAIL_TO_USERS` | Также слать на email активных пользователей | `false` |
| `WEBHOOK_URL` | Адрес webhook; пусто — выключен | `https://example.com/hooks/invoice` |
| `WEBHOOK_SECRET` | Ключ подписи HMAC-SHA256 (необязательно) | случайная строка |
| `NOTIFY_URLS` | Другие каналы через Apprise (JSON-список URL) | `["ntfy://invoice-keeper"]` |
| `MEDIA_ROOT` | Каталог чеков (относительно `backend/`) | `media` |
| `ATTACHMENT_MAX_MB` | Максимальный размер чека, МБ | `10` |
| `LOG_FILE` | Файл логов с ротацией; пусто — только консоль | `logs/app.log` |

Как узнать `TELEGRAM_CHAT_ID`: добавьте бота в чат, напишите в чат любое сообщение и откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` — id чата в поле `chat.id` (у групп он отрицательный). Без токена и чата всё, кроме отправки сообщений, работает.

> В `.env.example` нет реальных секретов. Не коммитьте `.env`.

### 2. Backend

```bash
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

API будет доступно на http://localhost:8000/api/v1/, Swagger — на http://localhost:8000/api/v1/docs.

Учётная запись администратора создаётся или обновляется из `ADMIN_USERNAME` / `ADMIN_PASSWORD` после каждого `migrate`. Под ней же можно войти в Django-админку: http://localhost:8000/admin/ (там же история изменений).

Все данные хранятся в БД (по умолчанию `backend/db.sqlite3`) и сохраняются после перезапуска.

### 3. Тестовые данные

```bash
uv run python manage.py seed_demo --reset
```

Даты считаются от сегодняшнего дня. Загрузятся:
- аренда в рублях: три прошлых периода оплачены (один — с опозданием на 2 дня), срок позавчера не оплачен (просрочка), следующий период — через месяц;
- сервер в долларах со сроком через 2 дня — напоминание уйдёт при первой проверке;
- подписка в евро и домен в рублях (ежегодно);
- пользователь `user` / `user-pass-123`.

`--reset` удаляет все платежи перед загрузкой.

### 4. Напоминания

Фоновый процесс проверяет сроки и пишет в Telegram-чат и в дополнительные каналы (email, webhook, Apprise), если они заданы в `.env`. Запустите его в отдельном терминале:

```bash
cd backend
uv run python manage.py run_reminders
```

Процесс раз в `REMINDER_CHECK_INTERVAL_SECONDS` создаёт следующие периоды и отправляет напоминания, а между проверками слушает нажатия кнопки «Оплачено». Для cron есть `run_reminders --once`.

Проверить настройку каналов — тестовое сообщение в каждый настроенный канал:

```bash
uv run python manage.py check_channels
```

Для локальной проверки email без настоящего SMTP подойдёт [Mailpit](https://mailpit.axllent.org/) — письма видны на http://localhost:8025:

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
```

В `.env`: `EMAIL_HOST=localhost`, `EMAIL_PORT=1025`, `EMAIL_USE_TLS=false`, `REMINDER_EMAIL_TO=["team@example.com"]`.

Webhook-получатель проверяет подпись так (Python):

```python
expected = "sha256=" + hmac.new(SECRET.encode(), request_body, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, request.headers["X-Invoice-Keeper-Signature"])
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

Панель откроется на http://localhost:5173. Vite проксирует `/api` на `http://127.0.0.1:8000`, поэтому фронт и API работают на одном origin (refresh-cookie `SameSite=Strict`).

Сборка для продакшена: `npm run build` → статические файлы в `frontend/dist/`; nginx отдаёт SPA (`try_files $uri /index.html`) и проксирует `/api` на Django.

## Разработка

Частые команды собраны в [`backend/justfile`](backend/justfile) (нужен [just](https://github.com/casey/just)), список — `just --list`:

```bash
cd backend
just setup
```

`just setup` ставит все зависимости, включая dev-группу, и pre-commit-хуки. Перед коммитом [pre-commit](.pre-commit-config.yaml) прогоняет ruff (линтер и форматтер), mypy (`strict`) и базовые проверки файлов. Вручную: `just check` (ruff, mypy, тесты, `manage.py check`, проверка миграций) и `just pre-commit`.

Без `just`:

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run manage.py test
cd ../frontend && npm run typecheck
```

## API

Все эндпоинты используют префикс `/api/v1`. Полный контракт с примерами — [docs/API.md](docs/API.md).
Спецификация OpenAPI лежит в [`backend/openapi.json`](backend/openapi.json), Swagger — http://localhost:8000/api/v1/docs (кнопка **Authorize** → access-токен из ответа `auth/login`). Перегенерировать: `just openapi`.

### Авторизация

| Метод | Эндпоинт | Назначение | Доступ |
|---|---|---|---|
| POST | `/auth/login` | Вход по логину и паролю: `access` в теле, `refresh` в HttpOnly-cookie | все |
| POST | `/auth/refresh` | Новый `access` по refresh-cookie (cookie ротируется, старый refresh отзывается) | все |
| GET | `/auth/me` | Текущий пользователь | авторизованные |
| POST | `/auth/logout` | Выход: отзыв refresh-токена и удаление cookie | все |

Авторизация через [django-ninja-jwt](https://github.com/eadwinCode/django-ninja-jwt): заголовок `Authorization: Bearer <access>`, refresh-токен — в HttpOnly-cookie.

### Регулярные платежи и оплаты

| Метод | Эндпоинт | Назначение | Доступ |
|---|---|---|---|
| GET | `/recurring-payments` | Список регулярных платежей | все роли |
| POST | `/recurring-payments` | Создание регулярного платежа | админ |
| DELETE | `/recurring-payments/{id}` | Прекращение платежа и напоминаний с сохранением истории | админ |
| GET | `/payment-occurrences` | Список периодов: оплаченные и просроченные | все роли |
| GET | `/payment-occurrences/{id}` | Конкретный период | все роли |
| PATCH | `/payment-occurrences/{id}` | Подтверждение или отмена оплаты, исправление фактической даты | все роли |

### Дополнительные эндпоинты

| Метод | Эндпоинт | Назначение | Доступ |
|---|---|---|---|
| GET | `/payment-occurrences/calendar.ics` | Экспорт сроков в iCalendar (фильтры `currency`, `state`, `due_from`, `due_to`) | все роли |
| GET | `/payment-occurrences/{id}/attachments` | Чеки и ссылки периода | все роли |
| POST | `/payment-occurrences/{id}/attachments/file` | Прикрепить файл (multipart, поле `file`) | все роли |
| POST | `/payment-occurrences/{id}/attachments/link` | Прикрепить ссылку | все роли |
| GET | `/payment-occurrences/{id}/attachments/{attachment_id}/download` | Скачать файл | все роли |
| DELETE | `/payment-occurrences/{id}/attachments/{attachment_id}` | Удалить вложение | автор или админ |

### Итоги, пользователи, документация

| Метод | Эндпоинт | Назначение | Доступ |
|---|---|---|---|
| GET | `/payments/summary` | Итоговые суммы по валютам | все роли |
| GET | `/users` | Список пользователей | админ |
| POST | `/users` | Создание обычного пользователя | админ |
| PATCH | `/users/{id}` | Изменение пользователя | админ |
| DELETE | `/users/{id}` | Удаление пользователя | админ |
| GET | `/docs` | Swagger-документация | все |

## Модель данных

- **RecurringPayment** — регулярный платёж: название, сумма, валюта (`RUB` / `USD` / `EUR`), первый срок и день месяца, периодичность, признак активности. Удаление мягкое: платёж деактивируется, неоплаченные будущие периоды удаляются, история остаётся.
- **PaymentOccurrence** — период платежа: снимок суммы и валюты, срок оплаты, статус (`paid` / `unpaid`), фактическая дата оплаты, кто и когда отметил, когда отправлено напоминание. Уникален по (платёж, срок).
- **PaymentAttachment** — чек (файл) или ссылка, прикреплённые к периоду. Имя файла на диске случайное, исходное хранится отдельно; файл удаляется с диска вместе с записью.
- **ReminderDelivery** — напоминание по периоду, отправленное в email / webhook / Apprise. Уникальна по (период, канал) — это и есть защита от дублей; Telegram отмечается в `PaymentOccurrence.reminder_sent_at`.
- **User** — пользователь Django с ролью (администратор / пользователь).
- Изменения моделей пишутся в historical-таблицы `django-simple-history`.

Периоды создаются заранее на срок напоминания (`REMINDER_DAYS_BEFORE`) плюс всегда есть следующий период — при создании платежа, в фоновом процессе и при чтении списков.

Просрочка не хранится, а вычисляется:
- для неоплаченного периода: сегодня позже срока;
- для оплаченного: фактическая дата позже срока.

## Сценарий демонстрации

Подготовка: `seed_demo --reset`, запущены backend, `run_reminders` и frontend.

1. Войти администратором (`ADMIN_USERNAME` / `ADMIN_PASSWORD` из `.env`).
2. «Регулярные платежи» → «Добавить платёж» со сроком через 1–3 дня.
3. Напоминание приходит в Telegram сразу (до срока меньше 3 дней); «Сервер» из демо-данных приходит при первой проверке.
4. Выйти, войти пользователем `user` / `user-pass-123` — кнопок добавления и удаления и раздела «Пользователи» нет (API отвечает 403). Нажать «Оплачено» у периода или «✅ Оплачено» в Telegram.
5. Вкладка «Просроченные»: аренда со сроком позавчера.
6. Отметить её «Другой датой…» = дата срока — просрочка исчезнет; «Исправить дату» у оплаченного периода пересчитывает просрочку, срок не меняется.
7. Клик по названию платежа: прошлые периоды со своими статусами и следующий период — «Не оплачено».

Дополнительно:

8. «📎» у оплаченного периода аренды — ссылка «Платёжное поручение» из демо-данных; перетащить PDF или фото чека, скачать, удалить.
9. «Календарь» → «📅 Экспорт .ics» → открыть файл: сроки появятся в календаре с оповещением за 3 дня.
10. С настроенным email / webhook — `check_channels`, затем напоминание по «Серверу» приходит во все каналы; в строке периода — «🔔 напомнили … · Telegram, Email, Webhook».
