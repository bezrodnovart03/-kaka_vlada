# Invoice Keeper — API-контракт (back ↔ front)

Источник: спецификация «Invoice Keeper — спецификация DTO и ERD» от 2026-10-23. Авторизация переведена с сессий Django на JWT (access в памяти, refresh в HttpOnly-cookie) — 2026-10-24.
Бэкенд — django-ninja, фронт — React SPA. Источник правды — Pydantic-схемы; TS-типы генерируются из OpenAPI (`openapi-typescript`) в `frontend/src/api/types.ts`.

Во всех примерах «сегодня» = `2026-10-23`, `TIME_ZONE = Europe/Moscow`.

---

## Содержание

1. [Общие правила](#1-общие-правила)
2. [Формат ошибок](#2-формат-ошибок)
3. [Авторизация](#3-авторизация)
4. [Регулярные платежи](#4-регулярные-платежи)
5. [Периоды оплаты](#5-периоды-оплаты)
6. [Итоги по валютам](#6-итоги-по-валютам)
7. [Пользователи](#7-пользователи)
8. [Матрица прав](#8-матрица-прав)
9. [TypeScript-типы целиком](#9-typescript-типы-целиком)

---

## 1. Общие правила

| Тема | Правило |
|---|---|
| Базовый URL | `/api/v1` |
| Swagger | `GET /api/v1/docs` |
| OpenAPI | `GET /api/v1/openapi.json` (копия в репо — `openapi.yml`) |
| Формат | `Content-Type: application/json; charset=utf-8` |
| Авторизация | JWT ([django-ninja-jwt](https://github.com/eadwinCode/django-ninja-jwt)): заголовок `Authorization: Bearer <access>` во всех запросах, кроме `auth/login`, `auth/refresh`, `auth/logout` и `docs` |
| Токены | `access` — 30 мин, `refresh` — 7 дней (`JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS`). Refresh одноразовый: при обновлении старый отзывается (ротация + blacklist) |
| `access` на фронте | Приходит в теле ответа, хранится **только в памяти** (переменная в `apiClient`). Не класть в `localStorage` / `sessionStorage` |
| `refresh` | Только в cookie, фронт его не видит и не отправляет вручную (см. ниже) |
| Cookie `refresh_token` | `HttpOnly; SameSite=Strict; Path=/api/v1/auth/; Max-Age=<срок refresh>`; `Secure` — когда `JWT_REFRESH_COOKIE_SECURE=true` (по умолчанию `= not DEBUG`). Ставят `auth/login` и `auth/refresh`, удаляет `auth/logout` |
| Защита от CSRF | Cookie уходит только на `/api/v1/auth/*` и только same-site. Дополнительно `auth/refresh` и `auth/logout` требуют заголовок `X-Requested-With: XMLHttpRequest` — без него 403 `csrf_failed` |
| `fetch` на фронте | Для `auth/login`, `auth/refresh`, `auth/logout` — `credentials: 'same-origin'` (значение по умолчанию; главное — не `'omit'`) |
| Один домен | Фронт и API обязаны быть на одном origin: в dev — proxy Vite (`/api` → `http://localhost:8000`), в проде — nginx отдаёт SPA и проксирует `/api`. CORS не настраивается |
| Имена полей | `snake_case` и в JSON, и в TS — без маппинга |
| `date` | `"2026-10-23"` |
| `datetime` | ISO 8601 со смещением: `"2026-10-23T20:18:00+03:00"` |
| Деньги | Строка-decimal с 2 знаками: `"85000.00"`. Float нигде не используется. На фронте форматировать через `Intl.NumberFormat('ru-RU', {style: 'currency', currency})`, арифметику не делать — итоги считает бэкенд |
| Валюты | `RUB`, `USD`, `EUR`. Суммы разных валют не складываются, конвертации нет |
| ID | целые числа |
| Пустые строки | `first_name`, `last_name`, `email` у пользователя — `""`, не `null` |
| Вычисляемые поля | `is_overdue`, `overdue_days`, `next_occurrence`, `today` — считает бэкенд, фронт не пересчитывает |

### Пагинация

Все списки принимают query `page` (с 1) и `page_size` (по умолчанию 50, максимум 200) и отвечают так:

```json
{
  "items": [ ... ],
  "count": 137
}
```

### Перечисления

| Тип | Значения |
|---|---|
| `Role` | `admin`, `user` |
| `Currency` | `RUB`, `USD`, `EUR` |
| `Period` | `monthly` (обязательно), `quarterly`, `yearly` (опционально) |
| `OccurrenceStatus` | `unpaid`, `paid` |
| `OccurrenceState` (только фильтр) | `unpaid`, `paid`, `overdue`, `upcoming` |

---

## 2. Формат ошибок

Все 4xx возвращают `ErrorOut`. Стандартный 422 ninja тоже приводится к этому виду.

```json
{
  "code": "validation_error",
  "detail": "Проверьте поля формы",
  "fields": {
    "amount": ["Сумма должна быть больше 0"],
    "first_due_date": ["Обязательное поле"]
  }
}
```

| Поле | Тип | Описание |
|---|---|---|
| `code` | `ErrorCode` | машинный код |
| `detail` | string | текст для показа пользователю |
| `fields` | `Record<string, string[]> \| null` | ошибки по полям формы (только 422) |

### Коды ошибок

| HTTP | `code` | Когда |
|---|---|---|
| 401 | `unauthorized` | нет заголовка `Authorization`, access-токен просрочен/невалиден, пользователь заблокирован или удалён |
| 401 | `invalid_credentials` | неверный логин/пароль |
| 401 | `token_invalid` | cookie `refresh_token` нет, токен просрочен, невалиден, уже отозван или пользователь заблокирован (`auth/refresh`) |
| 403 | `forbidden` | недостаточно прав (не админ) |
| 403 | `csrf_failed` | нет заголовка `X-Requested-With: XMLHttpRequest` (`auth/refresh`, `auth/logout`) |
| 403 | `env_admin_immutable` | попытка изменить/удалить админа из `.env` |
| 403 | `cannot_delete_self` | админ удаляет сам себя |
| 404 | `not_found` | объект не найден |
| 409 | `conflict` | общий конфликт уникальности |
| 409 | `username_taken` | логин уже занят |
| 409 | `already_deleted` | платёж уже удалён |
| 409 | `occurrence_not_paid` | исправление `paid_at` у неоплаченного периода |
| 422 | `validation_error` | ошибка валидации |

### Поведение `apiClient` на фронте

- **401 `unauthorized`** → один раз вызвать `POST /auth/refresh`, сохранить новый `access` и повторить исходный запрос. Параллельные запросы ждут один общий refresh-промис (несколько refresh одновременно нельзя — первый отзовёт токен, остальные получат 401). Если refresh не удался → очистить `access` и редирект на страницу входа
- **401 `token_invalid`** (от `auth/refresh`) → повторить refresh **один раз** через ~300 мс (cookie общая для всех вкладок: другая вкладка могла только что её обновить); снова 401 → очистить `access`, редирект на страницу входа
- **403** → тост «Недостаточно прав»
- **422** → разложить `ErrorOut.fields` по полям формы

---

## 3. Авторизация

Без валидного access-токена все эндпоинты, кроме `auth/login`, `auth/refresh`, `auth/logout` и `docs`, отвечают **401 `unauthorized`**.

**Поток на фронте:**
1. При старте приложения — `POST /auth/refresh` (без тела; если пользователь входил раньше, браузер сам приложит cookie). 200 → сохранить `access` → `GET /auth/me`. 401 → показать форму входа.
2. Вход: `POST /auth/login` → сохранить `access` → `GET /auth/me`.
3. Каждый запрос — с `Authorization: Bearer <access>`; истёкший access обновляется по правилам [`apiClient`](#поведение-apiclient-на-фронте).
4. Выход: `POST /auth/logout`, затем очистить `access` независимо от ответа.
5. `MeOut.role` управляет видимостью кнопок «Добавить платёж», «Удалить» и раздела «Пользователи» (только UX, права проверяет бэкенд).

**Когда токены перестают действовать:**

| Событие | `refresh` (cookie) | `access` |
|---|---|---|
| `auth/logout` | отозван, cookie удалена | действует до истечения (≤ 30 мин), фронт забывает его сам |
| `auth/refresh` | старый отозван, в cookie новый | старый действует до истечения |
| Блокировка (`is_active: false`) или удаление пользователя | не обновится (401) | сразу 401 — пользователь проверяется на каждом запросе |
| Смена пароля админом | все отозваны | действует до истечения (≤ 30 мин) |

Swagger (`/docs`): кнопка **Authorize** → вставить `access` без префикса `Bearer`. `auth/refresh` из Swagger вызвать нельзя (нет заголовка `X-Requested-With`) — для отладки использовать `curl` или фронт.

### 3.1 `POST /api/v1/auth/login`


**Тело запроса — `LoginIn`:**
```json
{
  "username": "oscar",
  "password": "s3cret-pass"
}
```

| Поле | Тип | Обязательно | Ограничения |
|---|---|---|---|
| `username` | string | да | 1–150 символов |
| `password` | string | да | 1–128 символов |

**Ответ `200 OK` — `AccessOut`**, ставит cookie с refresh-токеном:
```json
{ "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```
```
Set-Cookie: refresh_token=eyJ...; HttpOnly; SameSite=Strict; Path=/api/v1/auth/; Max-Age=604800[; Secure]
```

Обновляет `last_login` пользователя. `X-Requested-With` не требуется: cookie здесь не читается, а подделать вход в чужой аккаунт без пароля нельзя. Заблокированный пользователь (`is_active: false`) получает тот же 401, что и при неверном пароле.

**Ошибки:**
```json
// 401
{ "code": "invalid_credentials", "detail": "Неверный логин или пароль", "fields": null }
```
422 — пустые поля.

### 3.2 `POST /api/v1/auth/refresh`

**Заголовки:** `X-Requested-With: XMLHttpRequest`. `Authorization` не нужен — access к этому моменту обычно уже истёк. Тела нет: refresh берётся из cookie `refresh_token`.

**Ответ `200 OK` — `AccessOut`** + новый `Set-Cookie: refresh_token=...` (как в login). Прежний refresh отзывается — повторно его использовать нельзя.

**Ошибки** (при 401 cookie удаляется: `Set-Cookie: refresh_token=; Max-Age=0; Path=/api/v1/auth/`):
```json
// 401 — cookie нет, токен просрочен, невалиден или уже отозван
{ "code": "token_invalid", "detail": "Токен недействителен или просрочен", "fields": null }

// 401 — пользователь заблокирован или удалён
{ "code": "token_invalid", "detail": "Пользователь не найден", "fields": null }

// 403 — нет X-Requested-With
{ "code": "csrf_failed", "detail": "Запрос отклонён", "fields": null }
```

### 3.3 `GET /api/v1/auth/me`

**Ответ `200 OK` — `MeOut`:**
```json
{
  "id": 1,
  "username": "oscar",
  "first_name": "Оскар",
  "last_name": "",
  "email": "oscar@example.com",
  "role": "admin",
  "is_env_admin": true
}
```

**Ошибки:**
```json
// 401
{ "code": "unauthorized", "detail": "Требуется вход", "fields": null }
```

### 3.4 `POST /api/v1/auth/logout`

**Заголовки:** `X-Requested-With: XMLHttpRequest`. `Authorization` не нужен (выход должен работать и с истёкшим access). Тела нет.

**Ответ `204 No Content`** — refresh из cookie отзывается (если он валиден), cookie удаляется:
```
Set-Cookie: refresh_token=; Max-Age=0; Path=/api/v1/auth/
```
Идемпотентно: без cookie или с уже отозванным токеном — тоже 204. Access-токен stateless и действует до истечения, поэтому фронт забывает его сам.

**Ошибки:**
```json
// 403 — нет X-Requested-With
{ "code": "csrf_failed", "detail": "Запрос отклонён", "fields": null }
```

---

## 4. Регулярные платежи

Регулярный платёж — **шаблон**. Статус оплаты и даты живут на его **периодах** (раздел 5). Создание сразу порождает первый период; если до срока ≤ 3 дней — напоминание в Telegram уходит сразу.

### 4.1 `GET /api/v1/recurring-payments`

**Кто:** все.

**Query — `RecurringPaymentFilter` + пагинация:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `currency` | `Currency` | — | фильтр по валюте |
| `search` | string | — | поиск по названию (`icontains`) |
| `include_inactive` | bool | `false` | показывать удалённые платежи (история) |
| `page` | int | 1 | |
| `page_size` | int | 50 | максимум 200 |

**Пример:**
```
GET /api/v1/recurring-payments?currency=RUB&search=аренда&page=1&page_size=50
```

**Ответ `200 OK` — `Paginated<RecurringPaymentOut>`:**
```json
{
  "items": [
    {
      "id": 12,
      "title": "Аренда офиса",
      "amount": "85000.00",
      "currency": "RUB",
      "period": "monthly",
      "anchor_day": 26,
      "first_due_date": "2026-01-26",
      "comment": "Договор №14/25",
      "is_active": true,
      "deleted_at": null,
      "created_by": { "id": 1, "username": "oscar" },
      "created_at": "2026-01-10T12:04:31+03:00",
      "next_occurrence": {
        "id": 341,
        "due_date": "2026-09-26",
        "status": "unpaid",
        "paid_at": null,
        "is_overdue": true
      },
      "overdue_count": 1
    }
  ],
  "count": 1
}
```

| Поле | Описание |
|---|---|
| `anchor_day` | день месяца из `first_due_date`, ставит бэкенд |
| `is_active` | `false`, если платёж удалён (`deleted_at` заполнен) |
| `next_occurrence` | ближайший **неоплаченный** период (может быть просроченным), `null` — если таких нет |
| `overdue_count` | количество неоплаченных периодов со сроком раньше сегодня |

**Ошибки:** 422 (неверный параметр фильтра).

### 4.2 `POST /api/v1/recurring-payments`

**Кто:** только админ.

**Тело запроса — `RecurringPaymentIn`:**
```json
{
  "title": "Аренда офиса",
  "amount": "85000.00",
  "currency": "RUB",
  "first_due_date": "2026-10-26",
  "period": "monthly",
  "comment": "Договор №14/25"
}
```

| Поле | Тип | Обязательно | Ограничения |
|---|---|---|---|
| `title` | string | да | до 120 символов |
| `amount` | Money (string) | да | > 0, до 12 цифр, 2 знака после точки |
| `currency` | `Currency` | да | |
| `first_due_date` | ISODate | да | не раньше чем 12 месяцев назад |
| `period` | `Period` | нет | по умолчанию `monthly` |
| `comment` | string \| null | нет | |

Поля `anchor_day`, `created_by`, `deleted_at` клиент **не присылает** — их ставит бэкенд.

**Ответ `201 Created` — `RecurringPaymentOut`:**
```json
{
  "id": 13,
  "title": "Аренда офиса",
  "amount": "85000.00",
  "currency": "RUB",
  "period": "monthly",
  "anchor_day": 26,
  "first_due_date": "2026-10-26",
  "comment": "Договор №14/25",
  "is_active": true,
  "deleted_at": null,
  "created_by": { "id": 1, "username": "oscar" },
  "created_at": "2026-10-23T20:18:00+03:00",
  "next_occurrence": {
    "id": 402,
    "due_date": "2026-10-26",
    "status": "unpaid",
    "paid_at": null,
    "is_overdue": false
  },
  "overdue_count": 0
}
```

**Ошибки:**
```json
// 403
{ "code": "forbidden", "detail": "Недостаточно прав", "fields": null }

// 422
{
  "code": "validation_error",
  "detail": "Проверьте поля формы",
  "fields": { "amount": ["Сумма должна быть больше 0"] }
}
```

### 4.3 `DELETE /api/v1/recurring-payments/{id}`

**Кто:** только админ.
Тела нет.

**Пример:** `DELETE /api/v1/recurring-payments/13`

**Ответ `204 No Content`.**

Мягкое удаление:
- ставится `deleted_at`;
- удаляются только неоплаченные будущие периоды (срок позже сегодня) вместе с их напоминаниями;
- прошлые и оплаченные периоды остаются в истории;
- напоминания по платежу прекращаются.

**Ошибки:**
```json
// 403
{ "code": "forbidden", "detail": "Недостаточно прав", "fields": null }

// 404
{ "code": "not_found", "detail": "Платёж не найден", "fields": null }

// 409 — повторное удаление
{ "code": "already_deleted", "detail": "Платёж уже удалён", "fields": null }
```

---

## 5. Периоды оплаты

Период (`PaymentOccurrence`) — единица учёта: свой срок, свой статус и фактическая дата оплаты. Отметить / отменить / исправить оплату могут **и админ, и пользователь**. `due_date` через API не меняется никогда.

### 5.1 `GET /api/v1/payment-occurrences`

**Кто:** все.

**Query — `OccurrenceFilter` + пагинация:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `recurring_payment_id` | int | — | периоды конкретного платежа |
| `currency` | `Currency` | — | |
| `state` | `OccurrenceState` | — | см. ниже |
| `due_from` | ISODate | — | `due_date >= due_from` |
| `due_to` | ISODate | — | `due_date <= due_to` |
| `ordering` | `due_date` \| `-due_date` | `due_date` | сортировка |
| `page`, `page_size` | int | 1, 50 | |

Значения `state`:

| `state` | Что попадает |
|---|---|
| `paid` | оплаченные |
| `unpaid` | все неоплаченные |
| `overdue` | неоплаченные со сроком раньше сегодня |
| `upcoming` | неоплаченные со сроком сегодня или позже |

**Пример:**
```
GET /api/v1/payment-occurrences?state=overdue&ordering=due_date&page=1
```

**Ответ `200 OK` — `Paginated<PaymentOccurrenceOut>`:**
```json
{
  "items": [
    {
      "id": 341,
      "recurring_payment": { "id": 12, "title": "Аренда офиса", "is_active": true },
      "amount": "85000.00",
      "currency": "RUB",
      "due_date": "2026-09-26",
      "status": "unpaid",
      "paid_at": null,
      "is_overdue": true,
      "overdue_days": 27,
      "marked_by": null,
      "marked_at": null,
      "reminder_sent_at": "2026-09-23T09:00:12+03:00"
    }
  ],
  "count": 1
}
```

| Поле | Описание |
|---|---|
| `amount`, `currency` | снимок на момент создания периода — не меняется, если шаблон поменяли |
| `is_overdue` | не оплачен: `сегодня > due_date`; оплачен: `paid_at > due_date`. Оплата в день срока — вовремя |
| `overdue_days` | `max(0, (paid_at или сегодня) − due_date)` |
| `marked_by` | кто последним менял статус; `null`, если никто или пользователь удалён |
| `reminder_sent_at` | когда ушло напоминание в Telegram, `null` — не отправлялось |

**Ошибки:** 422.

### 5.2 `GET /api/v1/payment-occurrences/{id}`

**Кто:** все.

**Ответ `200 OK` — `PaymentOccurrenceOut`** (как элемент списка выше).

**Ошибки:**
```json
// 404
{ "code": "not_found", "detail": "Период не найден", "fields": null }
```

### 5.3 `PATCH /api/v1/payment-occurrences/{id}`

**Кто:** все.

**Тело запроса — `PaymentOccurrencePatchIn`**, один из трёх вариантов:

**а) Отметить оплаченным сегодня**
```json
{ "status": "paid" }
```
→ `paid_at` = сегодня в `TIME_ZONE`.

**б) Отметить оплаченным конкретной датой**
```json
{ "status": "paid", "paid_at": "2026-10-20" }
```
→ 422, если `paid_at` позже сегодня.

**в) Отменить оплату**
```json
{ "status": "unpaid" }
```
→ `paid_at` = `null`, просрочка снова считается от сегодня.

**г) Исправить дату уже оплаченного периода**
```json
{ "paid_at": "2026-09-25" }
```
→ просрочка пересчитывается. 409 `occurrence_not_paid`, если период не оплачен.

**Невалидно (422):** `{}` и `{ "status": "unpaid", "paid_at": "..." }`.

Каждое изменение записывает `marked_by` = текущий пользователь, `marked_at` = сейчас.

**Ответ `200 OK` — `PaymentOccurrenceOut`:**
```json
{
  "id": 341,
  "recurring_payment": { "id": 12, "title": "Аренда офиса", "is_active": true },
  "amount": "85000.00",
  "currency": "RUB",
  "due_date": "2026-09-26",
  "status": "paid",
  "paid_at": "2026-10-23",
  "is_overdue": true,
  "overdue_days": 27,
  "marked_by": { "id": 2, "username": "anna" },
  "marked_at": "2026-10-23T20:31:05+03:00",
  "reminder_sent_at": "2026-09-23T09:00:12+03:00"
}
```

**Ошибки:**
```json
// 404
{ "code": "not_found", "detail": "Период не найден", "fields": null }

// 409
{ "code": "occurrence_not_paid", "detail": "Период не оплачен — нечего исправлять", "fields": null }

// 422
{
  "code": "validation_error",
  "detail": "Проверьте поля формы",
  "fields": { "paid_at": ["Дата оплаты не может быть в будущем"] }
}
```

---

## 6. Итоги по валютам

### 6.1 `GET /api/v1/payments/summary`

**Кто:** все.

**Query — `SummaryQuery`:**

| Параметр | Тип | По умолчанию |
|---|---|---|
| `date_from` | ISODate | 1-е число текущего месяца |
| `date_to` | ISODate | последний день текущего месяца |

Считаются периоды со сроком внутри диапазона; удалённые платежи учитываются по сохранённой истории.
Тот же эндпоинт закрывает «Итоги на дату» и «Бюджет на месяц / год» — фронт просто передаёт нужный диапазон.

**Пример:**
```
GET /api/v1/payments/summary?date_from=2026-10-01&date_to=2026-10-31
```

**Ответ `200 OK` — `SummaryOut`.** Всегда три строки в порядке RUB, USD, EUR, даже нулевые:
```json
{
  "date_from": "2026-10-01",
  "date_to": "2026-10-31",
  "today": "2026-10-23",
  "totals": [
    {
      "currency": "RUB",
      "planned": "142500.00",
      "paid": "57500.00",
      "unpaid": "85000.00",
      "overdue": "0.00",
      "count_planned": 3,
      "count_paid": 2,
      "count_overdue": 0
    },
    {
      "currency": "USD",
      "planned": "49.00",
      "paid": "0.00",
      "unpaid": "49.00",
      "overdue": "49.00",
      "count_planned": 1,
      "count_paid": 0,
      "count_overdue": 1
    },
    {
      "currency": "EUR",
      "planned": "0.00",
      "paid": "0.00",
      "unpaid": "0.00",
      "overdue": "0.00",
      "count_planned": 0,
      "count_paid": 0,
      "count_overdue": 0
    }
  ]
}
```

| Поле | Описание |
|---|---|
| `today` | «сегодня» сервера — фронт не считает дату сам |
| `planned` | все периоды со сроком в диапазоне |
| `paid` | из них оплачено |
| `unpaid` | из них не оплачено |
| `overdue` | не оплачено и срок прошёл |

**Ошибки:**
```json
// 422 — date_from позже date_to или диапазон длиннее 366 дней
{
  "code": "validation_error",
  "detail": "Диапазон не должен превышать 366 дней",
  "fields": { "date_to": ["Диапазон не должен превышать 366 дней"] }
}
```

---

## 7. Пользователи

**Все эндпоинты — только для админа** (пользователь получает 403 `forbidden`).
Через API создаются только обычные пользователи (`role` всегда `user`, поля `role` во входных DTO нет).
Админ из `.env` (`is_env_admin: true`) виден в списке, но любые `PATCH` / `DELETE` на него → 403 `env_admin_immutable`.

### 7.1 `GET /api/v1/users`

**Query:** `page`, `page_size`.

**Ответ `200 OK` — `Paginated<UserOut>`:**
```json
{
  "items": [
    {
      "id": 1,
      "username": "oscar",
      "first_name": "Оскар",
      "last_name": "",
      "email": "oscar@example.com",
      "role": "admin",
      "is_env_admin": true,
      "is_active": true,
      "last_login": "2026-10-23T19:55:02+03:00",
      "date_joined": "2026-01-01T10:00:00+03:00"
    },
    {
      "id": 2,
      "username": "anna",
      "first_name": "Анна",
      "last_name": "Петрова",
      "email": "",
      "role": "user",
      "is_env_admin": false,
      "is_active": true,
      "last_login": null,
      "date_joined": "2026-10-20T14:12:44+03:00"
    }
  ],
  "count": 2
}
```

`last_login: null` — пользователь ни разу не входил.
`password`, `is_staff`, `is_superuser`, `groups`, `user_permissions` не отдаются никогда.

**Ошибки:** 403.

### 7.2 `POST /api/v1/users`


**Тело запроса — `UserCreateIn`:**
```json
{
  "username": "anna",
  "password": "min8chars",
  "email": "anna@example.com",
  "first_name": "Анна",
  "last_name": "Петрова"
}
```

| Поле | Тип | Обязательно | Ограничения |
|---|---|---|---|
| `username` | string | да | до 150, буквы/цифры и `@.+-_`, уникальный |
| `password` | string | да | 8–128 символов |
| `email` | string | нет | |
| `first_name` | string | нет | |
| `last_name` | string | нет | |

**Ответ `201 Created` — `UserOut`:**
```json
{
  "id": 2,
  "username": "anna",
  "first_name": "Анна",
  "last_name": "Петрова",
  "email": "anna@example.com",
  "role": "user",
  "is_env_admin": false,
  "is_active": true,
  "last_login": null,
  "date_joined": "2026-10-23T20:40:00+03:00"
}
```

**Ошибки:**
```json
// 403
{ "code": "forbidden", "detail": "Недостаточно прав", "fields": null }

// 409
{ "code": "username_taken", "detail": "Логин уже занят", "fields": { "username": ["Логин уже занят"] } }

// 422
{ "code": "validation_error", "detail": "Проверьте поля формы", "fields": { "password": ["Минимум 8 символов"] } }
```

### 7.3 `PATCH /api/v1/users/{id}`


**Тело запроса — `UserPatchIn`**, все поля необязательные, меняются только присланные:
```json
{
  "first_name": "Анна",
  "is_active": false
}
```

| Поле | Тип | Описание |
|---|---|---|
| `username` | string | уникальный |
| `password` | string | 8–128; смена пароля отзывает все refresh-токены пользователя (выданные access действуют до истечения) |
| `email` | string | |
| `first_name` | string | |
| `last_name` | string | |
| `is_active` | bool | `false` — блокировка входа без удаления |

**Ответ `200 OK` — `UserOut`.**

**Ошибки:**
```json
// 403 — не админ
{ "code": "forbidden", "detail": "Недостаточно прав", "fields": null }

// 403 — попытка изменить админа из .env
{ "code": "env_admin_immutable", "detail": "Администратора из .env нельзя изменить", "fields": null }

// 404
{ "code": "not_found", "detail": "Пользователь не найден", "fields": null }

// 409
{ "code": "username_taken", "detail": "Логин уже занят", "fields": { "username": ["Логин уже занят"] } }
```
422 — ошибка валидации.

### 7.4 `DELETE /api/v1/users/{id}`

Тела нет.

**Ответ `204 No Content`.**
Токены пользователя перестают работать сразу (401 на любом запросе); в его отметках об оплате `marked_by` становится `null`, сами отметки остаются.

**Ошибки:**
```json
// 403
{ "code": "env_admin_immutable", "detail": "Администратора из .env нельзя удалить", "fields": null }

// 403
{ "code": "cannot_delete_self", "detail": "Нельзя удалить самого себя", "fields": null }

// 404
{ "code": "not_found", "detail": "Пользователь не найден", "fields": null }
```

---

## 8. Матрица прав

Все пути — под `/api/v1`. Без валидного access-токена всё, кроме `auth/login`, `auth/refresh`, `auth/logout` и Swagger, → 401 `unauthorized`.

| Метод и путь | Админ | Пользователь | Ответ 2xx | Ошибки (кроме 401) |
|---|---|---|---|---|
| `POST /auth/login` | да | да | 200 `AccessOut` + cookie | 401 `invalid_credentials`, 422 |
| `POST /auth/refresh` | да | да | 200 `AccessOut` + cookie | 401 `token_invalid`, 403 `csrf_failed` |
| `GET /auth/me` | да | да | 200 `MeOut` | — |
| `POST /auth/logout` | да | да | 204, cookie удалена | 403 `csrf_failed` |
| `GET /recurring-payments` | да | да | 200 `Paginated<RecurringPaymentOut>` | 422 |
| `POST /recurring-payments` | да | **нет** | 201 `RecurringPaymentOut` | 403, 422 |
| `DELETE /recurring-payments/{id}` | да | **нет** | 204 | 403, 404, 409 `already_deleted` |
| `GET /payment-occurrences` | да | да | 200 `Paginated<PaymentOccurrenceOut>` | 422 |
| `GET /payment-occurrences/{id}` | да | да | 200 `PaymentOccurrenceOut` | 404 |
| `PATCH /payment-occurrences/{id}` | да | да | 200 `PaymentOccurrenceOut` | 404, 409 `occurrence_not_paid`, 422 |
| `GET /payments/summary` | да | да | 200 `SummaryOut` | 422 |
| `GET /users` | да | **нет** | 200 `Paginated<UserOut>` | 403 |
| `POST /users` | да | **нет** | 201 `UserOut` | 403, 409 `username_taken`, 422 |
| `PATCH /users/{id}` | да | **нет** | 200 `UserOut` | 403, 403 `env_admin_immutable`, 404, 409, 422 |
| `DELETE /users/{id}` | да | **нет** | 204 | 403, 403 `env_admin_immutable` / `cannot_delete_self`, 404 |
| `GET /docs` | да | да | Swagger UI | — |

---

## 9. TypeScript-типы целиком

```ts
// frontend/src/api/types.ts

// ── общие ──────────────────────────────────────────────
export type ISODate = string;      // '2026-10-23'
export type ISODateTime = string;  // '2026-10-23T20:18:00+03:00'
export type Money = string;        // '85000.00'

export type Role = 'admin' | 'user';
export type Currency = 'RUB' | 'USD' | 'EUR';
export type Period = 'monthly' | 'quarterly' | 'yearly';
export type OccurrenceStatus = 'unpaid' | 'paid';
export type OccurrenceState = 'unpaid' | 'paid' | 'overdue' | 'upcoming';

export interface UserBrief { id: number; username: string; }

export type ErrorCode =
  | 'unauthorized' | 'invalid_credentials' | 'token_invalid' | 'forbidden' | 'csrf_failed'
  | 'not_found' | 'validation_error' | 'conflict'
  | 'env_admin_immutable' | 'cannot_delete_self'
  | 'username_taken' | 'already_deleted' | 'occurrence_not_paid';

export interface ErrorOut {
  code: ErrorCode;
  detail: string;
  fields?: Record<string, string[]> | null;
}

export interface Paginated<T> { items: T[]; count: number; }
export interface PageQuery { page?: number; page_size?: number; }

// ── авторизация ────────────────────────────────────────
export interface LoginIn { username: string; password: string; }
// refresh-токен живёт только в HttpOnly-cookie и в TS не фигурирует
export interface AccessOut { access: string; }

export interface MeOut {
  id: number;
  username: string;
  first_name: string;   // '' если не задано
  last_name: string;
  email: string;
  role: Role;
  is_env_admin: boolean;
}

// ── регулярные платежи ─────────────────────────────────
export interface RecurringPaymentIn {
  title: string;
  amount: Money;
  currency: Currency;
  first_due_date: ISODate;
  period?: Period;          // по умолчанию 'monthly'
  comment?: string | null;
}

export interface OccurrenceBrief {
  id: number;
  due_date: ISODate;
  status: OccurrenceStatus;
  paid_at: ISODate | null;
  is_overdue: boolean;
}

export interface RecurringPaymentOut {
  id: number;
  title: string;
  amount: Money;
  currency: Currency;
  period: Period;
  anchor_day: number;
  first_due_date: ISODate;
  comment: string | null;
  is_active: boolean;
  deleted_at: ISODateTime | null;
  created_by: UserBrief;
  created_at: ISODateTime;
  next_occurrence: OccurrenceBrief | null;
  overdue_count: number;
}

export interface RecurringPaymentFilter extends PageQuery {
  currency?: Currency;
  search?: string;
  include_inactive?: boolean;
}

// ── периоды оплаты ─────────────────────────────────────
export interface RecurringPaymentBrief { id: number; title: string; is_active: boolean; }

export interface PaymentOccurrenceOut {
  id: number;
  recurring_payment: RecurringPaymentBrief;
  amount: Money;
  currency: Currency;
  due_date: ISODate;
  status: OccurrenceStatus;
  paid_at: ISODate | null;
  is_overdue: boolean;
  overdue_days: number;
  marked_by: UserBrief | null;
  marked_at: ISODateTime | null;
  reminder_sent_at: ISODateTime | null;
}

export type PaymentOccurrencePatchIn =
  | { status: 'paid'; paid_at?: ISODate }   // отметить; без paid_at = сегодня
  | { status: 'unpaid' }                     // отменить; paid_at очищается
  | { paid_at: ISODate };                    // исправить дату уже оплаченного

export interface OccurrenceFilter extends PageQuery {
  recurring_payment_id?: number;
  currency?: Currency;
  state?: OccurrenceState;
  due_from?: ISODate;
  due_to?: ISODate;
  ordering?: 'due_date' | '-due_date';
}

// ── итоги ──────────────────────────────────────────────
export interface SummaryQuery { date_from?: ISODate; date_to?: ISODate; }

export interface CurrencyTotals {
  currency: Currency;
  planned: Money;
  paid: Money;
  unpaid: Money;
  overdue: Money;
  count_planned: number;
  count_paid: number;
  count_overdue: number;
}

export interface SummaryOut {
  date_from: ISODate;
  date_to: ISODate;
  today: ISODate;
  totals: CurrencyTotals[];  // всегда RUB, USD, EUR
}

// ── пользователи ───────────────────────────────────────
export interface UserOut {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
  is_env_admin: boolean;
  is_active: boolean;
  last_login: ISODateTime | null;
  date_joined: ISODateTime;
}

export interface UserCreateIn {
  username: string;
  password: string;
  email?: string;
  first_name?: string;
  last_name?: string;
}

export interface UserPatchIn {
  username?: string;
  password?: string;    // отзывает refresh-токены пользователя
  email?: string;
  first_name?: string;
  last_name?: string;
  is_active?: boolean;  // false — блокировка без удаления
}
```
