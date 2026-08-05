# HuntTech Bot Common

Shared library for HuntTech Telegram bots providing common utilities, AI client abstractions, configuration management, and security helpers.

**Цель библиотеки** — ускорить разработку новых ботов за счёт переиспользования:
- [x] Конфигурация через `AppSettings` (единые env-переменные)
- [x] AI-клиент с retry (OpenAI-совместимый)
- [x] Telegram-утилиты (команды, экранирование, разбивка сообщений)
- [x] Файловые утилиты (safe_join, sanitize_filename, валидация)
- [x] Логирование с маскингом секретов
- [x] Безопасность (sanitize_text_input, validate_url)
- [x] База данных (asyncpg pool, repository, unit of work, миграции)
- [x] Управление пользователями (AccessManager, middleware, Telegram UI)
- [x] **Email (конфигурация, SMTP/IMAP проверка, валидация)**
- [x] **Расчёт ставок (rates) — стандартный алгоритм «Рейты по аутстафу»**

Полный стандарт создания ботов HuntTech: [`HUNTECH_BOT_STANDARD.md`](HUNTECH_BOT_STANDARD.md)

## Installation

```bash
pip install hunttech-bot-common
```

### With extras

```bash
pip install "hunttech-bot-common[database]"   # For asyncpg support
pip install "hunttech-bot-common[documents]"   # For document parsing (docx, pdf, rtf)
pip install "hunttech-bot-common[all]"         # All extras
```

## Quick Start

```python
from hunttech_bot_common.config import AppSettings
from hunttech_bot_common.ai import AIClient
from hunttech_bot_common.logging import setup_logging

# Setup logging
setup_logging()

# Load settings from environment
settings = AppSettings.from_env()

# Use AI client
client = AIClient(
    endpoint=settings.ai.endpoint,
    api_key=settings.ai.api_key,
    model=settings.ai.model,
)
response = await client.complete("You are helpful", "Hello!")
print(response.content)
```

## Modules

- **ai** - OpenAI-compatible async AI client with retry logic
- **config** - Environment-based configuration management
- **telegram** - Telegram bot utilities (commands, escaping, callbacks)
- **files** - File handling, validation, and temporary directories
- **logging** - Structured logging with secrets masking
- **security** - URL validation, IP checking, input sanitization
- **email** - Email configuration, SMTP/IMAP testing, input validation
- **utils** - Async retry, chunking, datetime formatting
- **exceptions** - Common exception hierarchy
- **users** - User management module
- **services.rates** - Расчёт почасовых ставок кандидатов по ставке заказчика
  (справочник HUNTTECH_OUTSTAFFING_RATES, ÷164, округление вниз до 100 руб.)

## Development

```bash
pip install -e ".[test]"
pytest tests/ -v
```
