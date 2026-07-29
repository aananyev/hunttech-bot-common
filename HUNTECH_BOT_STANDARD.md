# HuntTech Bot Standard

> Единый стандарт создания Telegram-ботов в экосистеме HRM HuntTech.
> Цель — ускорить разработку новых ботов за счёт переиспользования общего кода,
> настроек, интерфейсов с HRM и архитектурных решений.

## Принципы

1. **Переиспользование** — любой новый бот начинается с `hunttech-bot-common`, а не с нуля
2. **Консистентность** — все боты выглядят одинаково: env-переменные, настройки, команды, меню
3. **Безопасность** — секреты маскируются, ввод санитизируется, доступ контролируется
4. **Интеграция с HRM** — боты читают справочники HRM через общую БД и пишут свои данные в собственные таблицы
5. **Тестируемость** — каждый бот содержит тесты конфига, кнопок и форматирования

---

## 1. Общие настройки (Shared Settings)

Все боты используют `hunttech_bot_common.config.AppSettings` как базовый класс конфигурации.

### Переменные окружения (стандарт)

| Переменная | Где определена | Назначение |
|-----------|---------------|------------|
| `BOT_TOKEN` | `TelegramSettings.from_env()` | Токен Telegram-бота |
| `ADMIN_IDS` | `TelegramSettings.from_env()` | ID администраторов (через запятую) |
| `AI_ENDPOINT` | `AISettings.from_env()` | URL AI API (совместимый с OpenAI) |
| `AI_API_KEY` | `AISettings.from_env()` | Ключ AI API |
| `AI_MODEL` | `AISettings.from_env()` | Модель (по умолч. `gpt-4o-mini`) |
| `DATABASE_URL` | `DatabaseSettings.from_env()` | URL PostgreSQL (asyncpg) |
| `LOG_LEVEL` | `AppSettings.from_env()` | Уровень логирования |
| `LOG_JSON_FORMAT` | `AppSettings.from_env()` | JSON-формат логов |

### Расширение для конкретного бота

Каждый бот добавляет свои переменные с префиксом. Пример для docs-bot:

```python
from dataclasses import dataclass
from hunttech_bot_common.config import AppSettings

@dataclass(frozen=True)
class MyBotConfig(AppSettings):
    my_custom_field: str = ""

    @classmethod
    def from_env(cls) -> MyBotConfig:
        app = AppSettings.from_env()
        return cls(
            telegram=app.telegram,
            ai=app.ai,
            database=app.database,
            my_custom_field=os.getenv("MY_BOT_CUSTOM_FIELD", ""),
        )
```

### Fallback для старых имён

Если бот исторически использует другие имена переменных — добавить `_first_configured()` fallback:

```python
token = _first_configured(
    os.getenv("BOT_TOKEN"),
    os.getenv("MY_LEGACY_BOT_TOKEN"),
)
```

---

## 2. Интерфейсы с HRM HuntTech

### 2.1. Чтение данных HRM

Для чтения справочников HRM (`Company`, `Currency`, `ExtUser`, `LaborAgreement` и т.д.) используется прямое подключение к общей БД PostgreSQL через `DatabasePool`:

```python
from hunttech_bot_common.database import DatabasePool, BaseRepository

pool = DatabasePool(settings.database)
company_repo = BaseRepository(pool, "hunttech_company")

# Поиск компании по имени
company = await company_repo.find_where("name ILIKE $1", [f"%{name}%"])
```

Все таблицы HRM имеют префикс `hunttech_` (или `itpearls_` — дубли).
Бот работает **только на чтение** справочников HRM, никогда не изменяет их.

### 2.2. Запись данных в HRM

Для записи бот использует **только свои собственные таблицы** с префиксом `hunttech_`:

```python
# Таблицы бота (пример)
accounting_repo = BaseRepository(pool, "hunttech_accounting_document")
await accounting_repo.create({
    "id": uuid, "flow_type": "PRIMARY", "status": "RECEIVED", ...
})
```

**Запрещено:**
- Изменять таблицы HRM (`hunttech_company`, `sec_user`, etc.)
- Использовать `DELETE`, `DROP`, `TRUNCATE` без явного утверждения
- Создавать таблицы без Liquibase-миграции с `preCondition`

### 2.3. Миграции БД

Миграции бота — Liquibase XML в `db/changelog/` с `preCondition onFail="HALT"`:

```xml
<preConditions onFail="HALT">
    <tableExists tableName="HUNTTECH_COMPANY"/>
</preConditions>
<changeSet id="..." author="hunttech">
    <sql>CREATE TABLE IF NOT EXISTS ...</sql>
</changeSet>
```

---

## 3. Переменные и средства хранения

### 3.1. JSON-файлы (только для временных данных)

```python
from hunttech_bot_common.files import safe_join, sanitize_filename
from pathlib import Path

data_dir = Path(get_hermes_home()) / "my_bot"
data_dir.mkdir(parents=True, exist_ok=True)
```

JSON подходит для:
- Состояния бота (scheduler state, last run timestamps)
- Кэша (user sessions, temporary lookups)
- Логов и отладочной информации

JSON **не подходит** для:
- Документов, которые должны быть в реестре HRM
- Данных, требующих транзакционной целостности

### 3.2. PostgreSQL (через DatabasePool)

Для всех бизнес-данных — `DatabasePool` + `BaseRepository` + `UnitOfWork`:

```python
from hunttech_bot_common.database import DatabasePool, BaseRepository, UnitOfWork

async with UnitOfWork(pool) as uow:
    repo = BaseRepository(uow.conn, "hunttech_my_bot_records")
    await repo.create({...})
    # auto commit on success, rollback on error
```

### 3.3. Telegram files (через бота)

Файлы от пользователей (фото, PDF) хранятся в Yandex.Disk или локальной папке бота.
В БД сохраняется только путь.

---

## 4. Безопасность

### 4.1. Маскинг секретов в логах

```python
from hunttech_bot_common.logging import setup_logging
setup_logging()  # SecretsMaskingFilter включён по умолчанию
```

### 4.2. Валидация пользовательского ввода

```python
from hunttech_bot_common.security import sanitize_text_input
from hunttech_bot_common.files import safe_join, validate_extension

user_text = sanitize_text_input(message.text)
safe_path = safe_join(base_dir, user_filename)
validate_extension(filename, {".pdf", ".jpg", ".png"})
```

### 4.3. Доступ по `allowed_user_id`

Каждый бот проверяет `allowed_user_id` (или `app.telegram.admin_ids`) при старте:

```python
if str(update.effective_user.id) not in settings.allowed_user_id:
    await message.reply_text("Доступ запрещён.")
    return
```

Более продвинутый вариант — `AccessManager` из `hunttech_bot_common.users.access`:
- Добавление/удаление пользователей через `/start`
- Права на команды (`set_command_permissions`)
- Баны
- Запрос доступа через `request_access()`

---

## 5. Общение с пользователем

### 5.1. Язык

Все боты HuntTech общаются **на русском языке**.
Технические термины (OCR, AI, dry-run) — на русском или английском по контексту.

### 5.2. Формат ответов

- Ответы начинаются с названия бота: `HRM HuntTech Docs Bot`
- Режим работы: `Режим: dry-run / working`
- Ошибки: понятным языком, без stack trace
- Длинные сообщения (>4096 символов) разбивать через `split_long_message()`

### 5.3. Меню

Порядок кнопок соответствует бизнес-процессу:
1. **Получение / Проверка** — кнопки приёма и проверки
2. **Ожидание / Упаковка** — статусы и подготовка
3. **Отправка** — финальные действия
4. **Мониторинг** — статистика и справка
5. **Обновление** — кнопка обновления меню

Все кнопки содержат тематические пиктограммы.

### 5.4. Команда /help

`/help` показывает:
- Назначение бота (одна строка)
- Режим (dry-run / working)
- Список основных кнопок с описанием
- Ссылку на документацию

Формат через `format_help_message()`.

---

## 6. Архитектура бота

```
telegram_bot.py    — PTB-обработчики, reply/button handlers
recognizer.py      — AI/OCR распознавание
email_sender.py    — отправка писем
contracts_layout   — раскладка файлов
storage.py         — хранение (JSON или DB)
config.py          — конфигурация (наследует AppSettings)
cli.py             — Hermes CLI команды
__init__.py        — регистрация плагина Hermes
plugin.yaml        — метаданные плагина
```

### Жизненный цикл бота

1. `__init__.py register(ctx)` — регистрация CLI, установка логирования
2. `cli.py run` — запуск PTB polling
3. PTB dispatcher — обработка сообщений
4. `recognizer.py` — AI/OCR
5. `storage.py` — сохранение результата
6. `email_sender.py` — отправка (опционально)
7. Scheduler — периодические задачи

---

## 7. Взаимодействие с HRM HuntTech

### 7.1. Hermes → HRM (запись)

Бот (Hermes) вызывает CUBA middleware через:
- **Прямой SQL** (через `DatabasePool`) — для массовых операций
- **CUBA REST API** (в будущем) — для стандартизированного доступа

### 7.2. HRM → Hermes (чтение)

CUBA читает данные бота:
- Через общую БД PostgreSQL
- Таблицы бота имеют префикс `hunttech_accounting_*`
- Только на чтение (CUBA не меняет таблицы бота)

### 7.3. Реестр событий

Все значимые действия бота фиксируются в `AccountingDocumentEvent`:
- `RECEIVED`, `RECOGNIZED`, `WAITING_CONFIRMATION`, `CONFIRMED`
- `SENT`, `ERROR`, `BAD_SCAN`, `SKIPPED`

### 7.4. Экран HRM для ботов (будущее)

Каждый бот может иметь экран в HRM HuntTech:
- Входящие
- Ожидающие подтверждения
- Готовые к отправке
- Отправленные
- Ошибки
- Журнал событий

---

## 8. plugin.yaml

```yaml
name: my_bot
version: 0.1.0
description: "HuntTech my bot."
kind: standalone
requires_env:
  - name: BOT_TOKEN
    description: "Telegram bot token"
    prompt: "Bot token"
    password: true
```

---

## 9. Быстрый старт нового бота

```bash
# 1. Создать репозиторий
# 2. Добавить зависимость
pip install hunttech-bot-common

# 3. Создать config.py с AppSettings
# 4. Создать __init__.py с register(ctx)
# 5. Создать telegram_bot.py с PTB
# 6. Разместить plugin.yaml
# 7. Создать tests/
```

Стандартная структура файлов:

```
my-bot/
├── __init__.py          # register(ctx)
├── cli.py               # Hermes CLI
├── config.py            # AppSettings + свои поля
├── telegram_bot.py      # PTB обработчики
├── storage.py           # Хранение (JSON/DB)
├── plugin.yaml          # Метаданные
├── tests/
│   ├── test_config.py
│   └── test_telegram_bot.py
├── pyproject.toml
└── README.md
```
