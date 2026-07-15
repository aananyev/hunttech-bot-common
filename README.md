# HuntTech Bot Common

Shared library for HuntTech Telegram bots providing common utilities, AI client abstractions, configuration management, and security helpers.

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
- **utils** - Async retry, chunking, datetime formatting
- **exceptions** - Common exception hierarchy
- **users** - User management module

## Development

```bash
pip install -e ".[test]"
pytest tests/ -v
```
