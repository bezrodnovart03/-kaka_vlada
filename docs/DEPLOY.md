# Деплой

Два способа:

- **Render.com (бесплатно, без банковской карты)** — для показа: панель, API, админка и Telegram-бот в одном контейнере, сервер во Франкфурте, поэтому Telegram доступен.
- **Свой сервер (VPS)** — весь стек `compose.yaml` плюс HTTPS через Caddy (`compose.prod.yaml`).

> ⚠️ У одного Telegram-бота может работать только один экземпляр. Пока бот запущен на сервере, остановите локальный стек (`docker compose down`), иначе в логах будет `Conflict: terminated by other getUpdates request`, а напоминания придут дважды: у каждого экземпляра своя база.

## Render.com

### Что даёт бесплатный тариф и чем ограничен

| Ограничение | Что значит для проекта |
|---|---|
| Сервис засыпает через 15 минут без входящих запросов | Спящий бот не отвечает. Лечится внешним пингом `/healthz` каждые 5–10 минут (шаг 4). Лимита 750 ч/мес хватает на работу 24/7 |
| 0.1 CPU, 512 МБ RAM | Старт контейнера занимает около 2 минут, в работе приложение потребляет около 190 МБ |
| Бесплатный Postgres удаляется через 30 дней | Для показа на хакатоне этого достаточно |
| Диск временный | Загруженные чеки пропадают при перезапуске или редеплое (ссылки и все данные в БД сохраняются) |
| Исходящий SMTP закрыт | Email-канал не работает. Telegram, webhook и Apprise работают |

### 1. Подготовка

1. Код с `render.yaml`, `deploy/` и `.dockerignore` должен лежать в репозитории на GitHub (подойдёт любая ветка).
2. Бот: токен у [@BotFather](https://t.me/BotFather). Добавьте бота в чат и узнайте id чата: напишите в чат что-нибудь и откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` (у групп id отрицательный, `-100…`).

### 2. Создать сервис

1. Зарегистрируйтесь на <https://render.com> через GitHub. Карту для бесплатного тарифа не просят.
2. **New → Blueprint**, выберите репозиторий и ветку. Render найдёт `render.yaml` и создаст веб-сервис `invoice-keeper` и базу `invoice-keeper-db`.
3. Render спросит значения:
   - `ADMIN_PASSWORD` — пароль администратора панели (логин `admin`);
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

   `SECRET_KEY` Render сгенерирует сам. Адрес сервиса, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` и `PANEL_URL` выставляются автоматически при старте (`deploy/render/start.sh`).
4. **Apply.** Первая сборка занимает 5–10 минут. Панель будет доступна по адресу вида `https://invoice-keeper-xxxx.onrender.com`.

Демо-данные: в сервисе **Environment → `SEED_DEMO` = `1`** → Save (сервис перезапустится). Данные загружаются только в пустую базу.

### 3. Проверка

- `https://<адрес>/` — панель, вход как `admin` / `ADMIN_PASSWORD`.
- `https://<адрес>/admin/` — админка, `https://<адрес>/api/v1/docs` — Swagger.
- В **Logs** должна быть строка `Напоминания запущены…`. Ошибок `TelegramError` быть не должно.

### 4. Чтобы сервис не засыпал

Зарегистрируйтесь на <https://uptimerobot.com> (или <https://cron-job.org>), тоже бесплатно и без карты. Создайте монитор **HTTP(s)** на `https://<адрес>/healthz` с интервалом 5 минут. Эндпоинт отвечает сам nginx, базу он не нагружает.

### Обновление

Каждый push в выбранную ветку Render собирает и выкатывает автоматически. Миграции применяются при старте.

## Свой сервер (VPS)

Нужен Linux-сервер вне РФ (иначе Telegram API недоступен) с Docker и Compose 2.24+, на котором открыты порты 80 и 443.

```bash
git clone <репозиторий> invoice-keeper && cd invoice-keeper
cp backend/.env.example backend/.env    # SECRET_KEY, ADMIN_PASSWORD, TELEGRAM_*
cp deploy/.env.prod.example .env        # DOMAIN, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, PANEL_URL, POSTGRES_PASSWORD
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Если своего домена нет, используйте `<IP-через-дефисы>.sslip.io`, например `203-0-113-7.sslip.io`. Caddy сам получит сертификат Let's Encrypt. Mailpit наружу не открыт, смотреть его можно через туннель: `ssh -L 8025:127.0.0.1:8025 <сервер>` → <http://localhost:8025>.

На сервере с 1 ГБ RAM включите swap на 1–2 ГБ: сборка фронтенда требовательна к памяти.
