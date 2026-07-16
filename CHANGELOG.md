# Changelog

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
