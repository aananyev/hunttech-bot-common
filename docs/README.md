# HuntTech Bot Common

Версия: 0.3.0

Единая библиотека для всех Telegram-ботов HuntTech.
Содержит общие компоненты: AI-клиент, БД, управление пользователями, файлы, безопасность, Telegram-утилиты.

---

## Установка

```bash
pip install hunttech-bot-common
# или из репозитория:
pip install -e /path/to/hunttech-bot-common
```

---

## Модули

| Модуль | Назначение |
|--------|------------|
| `ai` | AI-клиент для LLM (OpenAI-совместимые API) |
| `config` | Настройки приложения (AppSettings, BotSettings) |
| `database` | PostgreSQL — пул, репозиторий, UOW, миграции |
| `files` | Файловые утилиты (safe_join, validate_extension) |
| `logging` | Логирование |
| `security` | Безопасность (sanitize, validate_url, mask_secret) |
| `telegram` | Telegram-утилиты (escape_html, CommandDef, help) |
| `users` | **Управление пользователями (ключевой модуль)** |
| `utils` | Общие утилиты (async_retry, chunk_list, format_datetime) |
| `services` | Сервисы (db_config_service) |
| `email` | **Email: конфигурация, проверка SMTP/IMAP, валидация** |
| `exceptions` | Иерархия исключений |

---

## `users` — Управление пользователями

**Центральный модуль.** Каждый HuntTech-бот использует свою базу пользователей (`access_{bot_name}.json`).
Доступ предоставляется администратором **per-bot**, а не глобально.

### Архитектура

```
users/
├── access.py        # AccessManager — JSON-база пользователей
├── base.py          # UserRecord — структура пользователя
├── middleware.py     # aiogram middleware для доступа
├── ptb.py           # PTBUserHandlers — готовые handlers для python-telegram-bot
├── settings.py      # UserSettingsManager — настройки пользователей
└── telegram.py      # aiogram handlers (start, request, approve)
```

### AccessManager

```python
from hunttech_bot_common.users import AccessManager

am = AccessManager(
    data_path="data/access.json",
    master_admin_id=272980897,  # Telegram ID главного админа
    bot_name="My Bot",
)

# Проверка доступа
am.is_allowed(user_id)        # bool
am.is_admin(user_id)          # bool

# Управление
am.add_user(user_id=123, username="ivan", added_by=admin_id)
am.remove_user(user_id=123)
am.ban_user(user_id=123)
am.unban_user(user_id=123)

# Запросы доступа
result = am.request_access(user_id=456, username="petr", first_name="Пётр")
am.approve_request(user_id=456, approved_by=admin_id)
am.deny_request(user_id=456)

# Команды
am.set_command_permissions({"admin": {"admin"}, "setup": {"setup"}})
am.user_can_use_command(user_id, "setup")  # bool
```

### PTBUserHandlers (для python-telegram-bot)

**Рекомендуемый способ** интеграции управления пользователями в PTB-ботов.

```python
from hunttech_bot_common.users.ptb import PTBUserHandlers

# Вариант 1: per-bot база (рекомендуется — доступ per-bot)
user_handlers = PTBUserHandlers.from_bot_db(
    bot_name="my_bot",
    master_admin_id=272980897,
)

# Вариант 2: единая БД для всех ботов (устарело)
user_handlers = PTBUserHandlers.from_shared_db(
    master_admin_id=272980897,
    bot_name="My Bot",
)

# Вариант 2: своя БД
user_handlers = PTBUserHandlers(
    access_manager=AccessManager(...),
    bot_name="My Bot",
)

# В handlers:
await user_handlers.is_allowed(update)   # проверить доступ
await user_handlers.is_admin(update)      # проверить админа
await user_handlers.start_handler(update, context)  # /start gate
await user_handlers.request_access_handler(update, context)  # /request_access
await user_handlers.user_command_handler(update, context)    # /user list|add|remove|ban|unban

# Регистрация всех handler'ов одной командой:
user_handlers.register(app, exclude={"start"})
```

#### Единая БД пользователей

Файл: `~/.hermes/hunttech_bots/access_users.json`

Путь возвращает `get_shared_access_path()`. Все боты, использующие `from_shared_db()`,
читают и пишут в один файл. Пользователь, добавленный одним ботом, автоматически
получает доступ ко всем.

#### Стандартные команды

```python
from hunttech_bot_common.users.ptb import get_standard_commands, get_admin_commands

cmds = get_standard_commands()  # [start, request_access, help]
admin_cmds = get_admin_commands()  # [user (admin only)]
```

### aiogram

```python
from hunttech_bot_common.users.middleware import AccessControlMiddleware, CallbackAccessMiddleware
from hunttech_bot_common.users.telegram import start_access_gate, request_access_handler

dp.message.middleware.register(AccessControlMiddleware(get_access_manager=lambda: am))
dp.callback_query.middleware.register(CallbackAccessMiddleware(get_access_manager=lambda: am))
```

---

## `email` — Email: конфигурация, проверка подключения, валидация

```python
from hunttech_bot_common.email import (
    load_email_config, save_email_config, clear_email_config,
    format_email_config, default_email_config,
    test_email_connections, test_smtp_connection, test_imap_connection,
    validate_email, validate_hostname, validate_port, validate_password,
)

# Загрузка конфига (из JSON или .env)
cfg = load_email_config()  # ищет email_config.json в CWD
cfg = default_email_config()  # только .env, без файла

# Сохранение/очистка
save_email_config({"sender": "user@domain.ru", "password": "***"})
clear_email_config()

# Форматирование для вывода (пароль маскируется)
print(format_email_config(cfg))
# 📧 Текущая конфигурация email:
#   • Отправитель: `alan@hunttech.ru`
#   • SMTP-сервер: `smtp.yandex.ru:465`
#   • IMAP-сервер: `imap.yandex.ru:993`
#   • Пароль: `secr****`

# Валидация ввода
assert validate_email("user@domain.ru") is None
assert validate_hostname("imap.yandex.ru") is None
assert validate_port("993") is None
assert validate_password("secret") is None

# Асинхронная проверка SMTP + IMAP
results = await test_email_connections(cfg, timeout=15)
for r in results:
    print(r.short)  # "✅ SMTP: письмо отправлено"
    # или r.emoji, r.service, r.success, r.message
```

### Параметры .env по умолчанию

```env
MAIL_SENDER=alan@hunttech.ru
MAIL_SMTP_HOST=smtp.yandex.ru
MAIL_SMTP_PORT=465
MAIL_IMAP_HOST=imap.yandex.ru
MAIL_IMAP_PORT=993
```

Пароль по умолчанию: `HUNTTECH_DOCS_YANDEX_MAIL_PASSWORD` (env), либо через `/setup email`.

---

## `database` — PostgreSQL

```python
from hunttech_bot_common.database import DatabasePool, BaseRepository, UnitOfWork, DatabaseMigrator

pool = DatabasePool(url="postgresql://user:pass@localhost/db")
await pool.connect()

# Репозиторий
repo = BaseRepository(pool.pool, "my_table")
await repo.create(id="1", name="test", value=42)
await repo.get_by_id("1")
await repo.upsert({"id": "1", "name": "updated"}, conflict_columns=["id"])
await repo.raw_query("SELECT * FROM my_table WHERE name = $1", "test")

# Unit of Work
async with UnitOfWork(pool) as uow:
    repo = BaseRepository(uow.conn, "my_table")
    await repo.create(...)
    # commit при выходе из блока
```

---

## `telegram` — Telegram-утилиты

```python
from hunttech_bot_common.telegram import CommandDef, CommandGroup, render_help_text
from hunttech_bot_common.telegram import escape_html, split_long_message

# Определение команд
cmd = CommandDef(
    command="start",
    title="Запустить бота",
    description="Начать работу",
    hidden=False,
    admin=False,
    show_in_menu=True,
)

# Рендер справки
groups = [CommandGroup(title="Основные", commands=[cmd1, cmd2])]
help_text = render_help_text(groups, user_permissions={"admin"})

# Экранирование
safe = escape_html(user_input)  # < → &lt;, > → &gt;
parts = split_long_message(long_text, max_length=4000)  # для > 4096 символов
```

---

## `security` — Безопасность

```python
from hunttech_bot_common.security import sanitize_text_input, sanitize_filename, mask_secret
from hunttech_bot_common.security import validate_url, is_private_ip

clean = sanitize_text_input(user_input, max_length=1000)
safe_name = sanitize_filename(file_name)  # удаляет path traversal
masked = mask_secret("supersecret")  # "sup*****ret"
validate_url("https://example.com")  # проверяет схему, IP, localhost
```

---

## `files` — Файловые утилиты

```python
from hunttech_bot_common.files import safe_join, validate_extension, validate_file_size

path = safe_join("/base/dir", "sub/file.txt")  # защита от path traversal
validate_extension("file.pdf", allowed={".pdf", ".jpg"})
validate_file_size(1024 * 1024, max_bytes=10 * 1024 * 1024)  # 10MB
```

---

## `ai` — AI-клиент

```python
from hunttech_bot_common import AIClient, AIConnectionError

client = AIClient(endpoint="https://api.openai.com/v1", api_key="sk-...", model="gpt-4")
response = await client.chat(messages=[{"role": "user", "content": "Hello"}])
text = response.content
```

---

## Иерархия исключений

```
CommonLibraryError
├── ConfigurationError
├── AIError
│   ├── AIConnectionError
│   ├── AIAuthenticationError
│   ├── AIRateLimitError
│   ├── AITimeoutError
│   ├── AIInvalidResponseError
│   └── AISchemaValidationError
├── DatabaseError
├── FileValidationError
├── PermissionDeniedError
├── TelegramIntegrationError
└── OperationConflictError
```

---

## Тестирование

```bash
cd /path/to/hunttech-bot-common
pip install pytest pytest-asyncio
pytest tests/
```

---

## Разработка

```bash
git clone https://github.com/aananyev/hunttech-bot-common.git
cd hunttech-bot-common
pip install -e .
# для продакшена с БД:
pip install -e ".[database]"
```
