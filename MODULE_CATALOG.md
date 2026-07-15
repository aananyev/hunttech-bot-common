# Module Catalog

## hunttech_bot_common

Top-level package. Re-exports key symbols from submodules.

## hunttech_bot_common.exceptions

Exception hierarchy for the library.

- `CommonLibraryError` - Base exception
- `ConfigurationError` - Configuration issues
- `AIError` - Base AI exception
  - `AIConnectionError` - Connection failures
  - `AIAuthenticationError` - Auth failures
  - `AIRateLimitError` - Rate limiting
  - `AITimeoutError` - Timeout errors
  - `AIInvalidResponseError` - Invalid responses
  - `AISchemaValidationError` - Schema validation failures
- `DatabaseError` - Database issues
- `FileValidationError` - File validation failures
- `PermissionDeniedError` - Permission issues
- `TelegramIntegrationError` - Telegram errors
- `OperationConflictError` - Operation conflicts

## hunttech_bot_common.ai

OpenAI-compatible AI client.

- `AIClient` - Async HTTP client with retry logic
- `MockAIClient` - Mock client for testing
- `AIResponse` - Response dataclass
- `parse_structured_response` - Parse JSON from LLM responses
- `strip_json_markdown` - Extract JSON from markdown fences

## hunttech_bot_common.config

Configuration management.

- `AppSettings` - Main settings with `from_env()` classmethod
- `TelegramSettings` - Bot token, admin IDs
- `AISettings` - Endpoint, API key, model
- `DatabaseSettings` - Connection URL, pool settings

## hunttech_bot_common.telegram

Telegram bot utilities.

- `CommandDef` - Command definition dataclass
- `CommandGroup` - Command group dataclass
- `escape_md_simple` - Escape Markdown special chars
- `escape_html` - Escape HTML special chars
- `split_long_message` - Split long messages
- `make_callback_data` / `parse_callback_data` - Callback data helpers
- `render_help_text` - Render help text from commands
- `PermissionChecker` - Permission checking protocol

## hunttech_bot_common.files

File handling utilities.

- `temp_directory` - Temporary directory context manager
- `safe_join` - Path traversal prevention
- `validate_extension` - File extension validation
- `validate_file_size` - File size validation
- `sanitize_filename` - Filename sanitization

## hunttech_bot_common.logging

Logging utilities.

- `setup_logging` - Configure logging
- `SecretsMaskingFilter` - Mask secrets in logs
- `mask_secret` - Mask sensitive values

## hunttech_bot_common.security

Security utilities.

- `validate_url` - URL validation and sanitization
- `is_private_ip` - Check if IP is private
- `mask_secret` - Mask sensitive data
- `sanitize_text_input` - Strip dangerous content

## hunttech_bot_common.utils

General utilities.

- `async_retry` - Async retry with exponential backoff
- `chunk_list` - Split list into chunks
- `format_datetime` - Format datetime objects

## hunttech_bot_common.users

User management module — per-bot access control, settings, and Telegram UI.

### Users (`base.py`)

- `UserRecord` — User dataclass with `display_name`, `mention_html`, `has_permission()`
- `user_from_telegram()` — Create UserRecord from Telegram user data

### Access (`access.py`)

- `AccessManager` — JSON-backed user access control:
  - `add_user()` / `remove_user()` / `get_allowed_users()` — CRUD
  - `is_allowed()` / `is_admin()` / `get_admin_ids()` — Access checks
  - `ban_user()` / `unban_user()` / `is_banned()` — Ban management
  - `request_access()` / `approve_request()` / `deny_request()` — Access request flow
  - `set_command_permissions()` / `user_can_use_command()` — Command-based permissions
  - `filter_commands()` — Filter CommandDef list by user permissions
  - `add_permission()` / `remove_permission()` / `has_permission()` — Permission strings
  - `get_user_settings()` / `update_user_settings()` / `reset_user_settings()` — Per-user settings
  - `save()` / `reload()` — JSON persistence with atomic writes
  - Thread-safe with `threading.RLock()`

### Settings (`settings.py`)

- `UserSettingsManager` — Common (developer-defined, read-only to user) + Individual (user-manageable via /setup):
  - `apply_common_to_user()` — Copy common settings on first access
  - `get_individual()` / `update_individual()` / `reset_individual()` — Individual settings CRUD
  - `get_settings_help_text()` — Formatted settings display
  - Sensitive value masking (api_key, password, token, secret)

### Middleware (`middleware.py`)

- `AccessControlMiddleware` — aiogram middleware for message access gating
- `CallbackAccessMiddleware` — aiogram middleware for callback access blocking
  - Only `/start` allowed through for unauthorized users
  - Customizable block message

### Telegram UI (`telegram.py`)

- `start_access_gate()` — /start handler with access gate and request button
- `request_access_handler()` — /request_access handler with admin notification
- `admin_approval_callback()` — Handle `admin:allow:USER_ID` / `admin:deny:USER_ID` callbacks
- `user_list_handler()` — Show allowed users with inline delete buttons
- `user_delete_callback()` — Handle `userlist:del:USER_ID` callbacks
- `access_callback_handler()` — Handle `access:request` / `access:check_status` callbacks
- `sync_user_menu()` — Sync Telegram BotCommandScopeChat menu per user permissions
- `get_standard_user_commands()` / `get_standard_admin_commands()` — Standard CommandDefs
- `get_standard_groups()` — Standard CommandGroups for help rendering
- Constants: `ACCESS_DENIED_TEXT`, `ACCESS_REQUEST_SENT_TEXT`, `ACCESS_GRANTED_TEXT`, `INVITATION_TEXT`, `ACCESS_REVOKED_TEXT`
