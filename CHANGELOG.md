# Changelog

## 0.5.0 (2026-08-06)

### Added
- **`media` — логотип HuntTech над приветствием** (стандарт, эталон
  `@hunttech_short_vacancy_bot`): `send_logo(bot, chat_id) -> bool`
  — первое сообщение при `/start` и при старте бота; не роняет поток;
  поддерживает aiogram (`FSInputFile`) и PTB (`telegram.InputFile`);
  логотип — `assets/hunttech_logo.png`;
- **`services.startup` — сводка изменений при перезапуске** (стандарт,
  эталон `@hunttech_open_close_vacancy_bot`): git-подход, маркер
  `startup_state.json` хранит SHA прошлого запуска;
  `send_startup_changelog(bot, chat_id, repo_dir, state_path)` — первый
  запуск → «📦 Последние изменения бота» (8 коммитов), SHA изменился →
  «📦 Изменения с прошлого запуска» (до 10 пунктов), SHA тот же → молча;
  plain text (parse_mode=None); aiogram + PTB;
  `build_startup_changelog`, `git_sha`, `git_subjects_since`,
  `git_recent_subjects`, `load_startup_marker`, `save_startup_marker`,
  `format_startup_changelog`;
- Документация: HUNTECH_BOT_STANDARD.md §5.5 (логотип) и §5.6 (сводка
  изменений) — обязательны для ВСЕХ ботов; docs/README.md, README.md,
  MODULE_CATALOG.md;
- Тесты: tests/test_startup.py (15) + tests/test_media.py (4) — всего 241.

## 0.4.0 (2026-08-05)

### Added
- **`services.rates` — стандартный расчёт почасовых ставок кандидатов**
  (алгоритм «Рейты по аутстафу», перенесён из `hunttech_short_vavancy_bot`
  `/rates`, одобрен владельцем):
  - `calculate_candidate_rate(db, user_rate, empl="")` — единая точка
    вызова для всех ботов: точное совпадение `rate` в
    `HUNTTECH_OUTSTAFFING_RATES` → ближайшая меньшая (только активные
    строки, `delete_ts IS NULL`); часовая = зарплата ÷ 164, округление
    вниз до 100 руб.; выбор по оформлению ГПХ/ИП/«ГПХ или ИП»; отчёт
    в формате «Вознаграждение» + `rate_val` для подстановки в черновик;
  - `lookup_outstaffing_rate`, `hourly_from_monthly`,
    `pick_employment_rates`, `build_candidate_rates_report`;
  - константы `OUTSTAFFING_RATES_TABLE`, `HOURLY_MONTH_HOURS=164`,
    `HOURLY_ROUND_STEP=100`;
  - read-only: в БД ничего не пишется;
- Документация: раздел «services.rates» в `docs/README.md`,
  `MODULE_CATALOG.md`, `README.md`; стандарт в `HUNTECH_BOT_STANDARD.md`
  (§7.4) — боты обязаны вызывать `calculate_candidate_rate`;
- Тесты `tests/test_rates.py` (21 тест: округление, оформление, отчёт,
  lookup exact/nearest_lower/not_found, полный флоу, ошибки).

## 0.2.0 (2026-07-15)

### Added
- AI module with OpenAI-compatible async HTTP client
- Config module with environment-based settings
- Telegram module with command definitions, escaping, callbacks
- Files module with temp directories, safe joins, validation
- Logging module with secrets masking
- Security module with URL/IP validation
- Utils module with async retry, chunking, formatting
- **Users module** — complete user management system:
  - `AccessManager` — JSON-backed user access control per bot
  - `UserSettingsManager` — common + individual settings
  - `AccessControlMiddleware` — aiogram middleware for access gating
  - `CallbackAccessMiddleware` — callback blocking for unauthorized users
  - Standard Telegram UI handlers (`/start` gate, `/request_access`, admin approval, user list with delete buttons)
  - Permission-based command filtering
  - Access request flow with admin notification (Allow/Deny buttons)
  - Invitation notification on admin grant
  - Ban/unban support
  - `UserRecord` dataclass with display_name, mention_html helpers
- Exceptions module with full hierarchy
- Comprehensive test suite (105 tests)

## 0.3.0 (2026-07-16)

### Added
- **Database module** — complete async PostgreSQL layer:
  ...
- **DbConfigService** (`services/db_config_service.py`) — persistent DB config storage in JSON:
  - `load()` / `save()` / `delete()` — config CRUD with atomic writes
  - `to_pool_config()` — convert to PoolConfig for direct use
  - `format_config_display()` — formatted display with URL password masking
  - `_mask_db_url()` — safe URL display for Telegram
- **SetupDb FSM** (`telegram/setup_db.py`) — `/setup db` wizard for admin:
  - Admin-only command (master admin only)
  - Subcommands: `/setup db` (FSM), `/setup db test` (standalone test), `/setup db show` (show config)
  - 5-step FSM: URL → pool_min → pool_max → sslmode → confirm
  - SSL mode selection via inline keyboard (disable/prefer/require/verify-ca/verify-full)
  - Connection test before saving (both in FSM and standalone `/setup db test`)
  - Skip support for keeping existing values
  - `/setup db show` — masked display of current DB config
  - Admin-only: regular users never see these commands in menu or /help
  - `DatabasePool` — asyncpg connection pool with SSL/TLS, timeouts, health checks
  - `PoolConfig` — typed configuration with DATABASE_URL parsing (query params: sslmode, connect_timeout, pool_min/max, statement_timeout, application_name)
  - `BaseRepository` — generic CRUD repository (get_by_id, find_all, find_where, create, update, delete, bulk_create, upsert, count, exists, raw_query)
  - `UnitOfWork` — transaction management with auto commit/rollback, nested transaction support
  - `DatabaseMigrator` — SQL file-based versioned migrations (001_*.sql, tracking table `_migrations`, status, rollback support)
  - 44 tests

### Fixed
- Database `PoolConfig` now correctly parses query params from `DATABASE_URL`
- `DatabasePool.acquire()` is sync (returns PoolAcquireContext, not coroutine)
- `UnitOfWork` properly tracks `_committed` to avoid double rollback in `close()`

### Fixed
- Lock deadlock in AccessManager: `threading.Lock()` → `threading.RLock()`
- Circular import in users package: extracted `base.py` for core types
