"""Tests for hunttech-bot-common package."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from hunttech_bot_common import __version__
from hunttech_bot_common.ai import (
    AIResponse,
    MockAIClient,
    parse_structured_response,
    strip_json_markdown,
)
from hunttech_bot_common.exceptions import (
    AIAuthenticationError,
    AIConnectionError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitError,
    AISchemaValidationError,
    AITimeoutError,
    CommonLibraryError,
    ConfigurationError,
    DatabaseError,
    FileValidationError,
    OperationConflictError,
    PermissionDeniedError,
    TelegramIntegrationError,
)
from hunttech_bot_common.files import (
    safe_join,
    sanitize_filename,
    temp_directory,
    validate_extension,
    validate_file_size,
)
from hunttech_bot_common.security import (
    is_private_ip,
    mask_secret,
    sanitize_text_input,
    validate_url,
)
from hunttech_bot_common.telegram import (
    CommandDef,
    CommandGroup,
    escape_html,
    escape_md_simple,
    make_callback_data,
    parse_callback_data,
    render_help_text,
    split_long_message,
)
from hunttech_bot_common.utils import async_retry, chunk_list, format_datetime
from hunttech_bot_common.users import UserRecord, user_from_telegram
from hunttech_bot_common.users.access import AccessManager
from hunttech_bot_common.users.settings import UserSettingsManager
from hunttech_bot_common.telegram import CommandDef


# =============================================================================
# Version
# =============================================================================

def test_version() -> None:
    assert __version__ == "0.3.0"


# =============================================================================
# AI Module
# =============================================================================

@pytest.mark.asyncio
async def test_mock_ai_client() -> None:
    client = MockAIClient("test response")
    response = await client.complete("system", "user")
    assert isinstance(response, AIResponse)
    assert response.content == "test response"
    assert response.duration_ms == 0.0
    assert response.usage == {}


@pytest.mark.asyncio
async def test_mock_ai_client_schema_validation() -> None:
    from dataclasses import dataclass

    @dataclass
    class TestSchema:
        name: str
        value: int

    client = MockAIClient(json.dumps({"name": "test", "value": 42}))
    response = await client.complete("", "", response_schema=TestSchema)
    data = json.loads(response.content)
    assert data["name"] == "test"
    assert data["value"] == 42


@pytest.mark.asyncio
async def test_mock_ai_client_schema_validation_error() -> None:
    from dataclasses import dataclass

    @dataclass
    class TestSchema:
        name: str
        value: int

    client = MockAIClient("not valid json{")
    with pytest.raises(AISchemaValidationError):
        await client.complete("", "", response_schema=TestSchema)


def test_ai_response_dataclass() -> None:
    resp = AIResponse(content="hello", duration_ms=100.0, usage={"prompt_tokens": 10})
    assert resp.content == "hello"
    assert resp.duration_ms == 100.0
    assert resp.usage["prompt_tokens"] == 10


def test_strip_json_markdown_clean() -> None:
    assert strip_json_markdown('{"key": "value"}') == '{"key": "value"}'


def test_strip_json_markdown_fence() -> None:
    result = strip_json_markdown('```json\n{"key": "value"}\n```')
    assert result == '{"key": "value"}'


def test_strip_json_markdown_no_language() -> None:
    result = strip_json_markdown('```\n{"key": "value"}\n```')
    assert result == '{"key": "value"}'


def test_strip_json_markdown_with_text() -> None:
    result = strip_json_markdown('Here is the result:\n```json\n{"a": 1}\n```\nHope that helps!')
    assert result == '{"a": 1}'


def test_parse_structured_response_clean_json() -> None:
    result = parse_structured_response('{"name": "test", "value": 1}', dict)
    assert result == {"name": "test", "value": 1}


def test_parse_structured_response_markdown_fence() -> None:
    result = parse_structured_response('```json\n{"name": "test"}\n```', dict)
    assert result == {"name": "test"}


def test_parse_structured_response_invalid_json() -> None:
    with pytest.raises(AISchemaValidationError):
        parse_structured_response('not json at all', dict)


def test_parse_structured_response_dataclass() -> None:
    from dataclasses import dataclass

    @dataclass
    class MySchema:
        name: str
        age: int

    result = parse_structured_response('{"name": "Alice", "age": 30}', MySchema)
    assert isinstance(result, MySchema)
    assert result.name == "Alice"
    assert result.age == 30


# =============================================================================
# Configuration Module
# =============================================================================

def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("AI_ENDPOINT", "https://test.ai/v1")
    monkeypatch.setenv("AI_API_KEY", "sk-test-key")
    monkeypatch.setenv("AI_MODEL", "gpt-4")
    monkeypatch.setenv("ADMIN_IDS", "123,456")

    from hunttech_bot_common.config import AppSettings

    settings = AppSettings.from_env()
    assert settings.telegram.bot_token == "test_token_123"
    assert settings.telegram.admin_ids == [123, 456]
    assert settings.ai.endpoint == "https://test.ai/v1"
    assert settings.ai.api_key == "sk-test-key"
    assert settings.ai.model == "gpt-4"
    assert settings.database is None


def test_config_missing_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    from hunttech_bot_common.config import AppSettings

    with pytest.raises(ConfigurationError):
        AppSettings.from_env()


def test_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "bot123:abc")
    from hunttech_bot_common.config import AppSettings

    settings = AppSettings.from_env()
    assert settings.ai.endpoint == "https://api.openai.com/v1/chat/completions"
    assert settings.ai.model == "gpt-4o-mini"
    assert settings.log_level == "INFO"
    assert settings.log_json_format is False


# =============================================================================
# Telegram Module
# =============================================================================

def test_escape_md_simple() -> None:
    result = escape_md_simple("Hello _world_ *bold* [link]")
    assert result == r"Hello \_world\_ \*bold\* \[link\]"


def test_escape_md_simple_special_chars() -> None:
    result = escape_md_simple(r"_*[]()~`>#+-=|{}.!\\")
    assert result == r"\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!\\\\"


def test_escape_html() -> None:
    result = escape_html("<script>alert('xss')</script> & \"quotes\"")
    assert "&lt;script&gt;" in result
    assert "&amp;" in result
    assert "&quot;" in result


def test_split_long_message_short() -> None:
    result = split_long_message("Hello, world!")
    assert result == ["Hello, world!"]


def test_split_long_message_long() -> None:
    text = "Paragraph one.\n\n" + "A" * 2000 + "\n\n" + "B" * 2000
    result = split_long_message(text, max_len=1500)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 1500


def test_make_callback_data() -> None:
    result = make_callback_data("edit", "123", "title")
    assert result == "edit:123:title"


def test_parse_callback_data() -> None:
    result = parse_callback_data("edit:123:title")
    assert result == ["edit", "123", "title"]


def test_render_help_text_basic() -> None:
    commands = [
        CommandDef(command="start", title="Start bot", group="main"),
        CommandDef(command="help", title="Show help", group="main"),
    ]
    groups = [CommandGroup(key="main", title="General", emoji="📋")]
    result = render_help_text(commands, groups)
    assert "/`start`" in result
    assert "/`help`" in result
    assert "📋" in result
    assert "General" in result


def test_render_help_text_hidden_command() -> None:
    commands = [
        CommandDef(command="start", title="Start", group="main"),
        CommandDef(command="admin", title="Admin", group="main", admin=True, hidden=True),
    ]
    groups = [CommandGroup(key="main", title="General")]
    result = render_help_text(commands, groups, admin_ids={1}, user_id=2)
    assert "/`start`" in result
    assert "/`admin`" not in result


def test_render_help_text_admin_visible() -> None:
    commands = [
        CommandDef(command="admin", title="Admin", group="main", admin=True),
    ]
    groups = [CommandGroup(key="main", title="General")]
    result = render_help_text(commands, groups, admin_ids={1}, user_id=1)
    assert "/`admin`" in result


# =============================================================================
# Files Module
# =============================================================================

def test_temp_directory() -> None:
    with temp_directory() as tmpdir:
        assert tmpdir.exists()
        assert tmpdir.is_dir()
        test_file = tmpdir / "test.txt"
        test_file.write_text("hello")
        assert test_file.exists()
    assert not tmpdir.exists()


def test_safe_join_normal() -> None:
    result = safe_join("/base", "sub", "file.txt")
    assert str(result) == str(Path("/base/sub/file.txt").resolve())


def test_safe_join_path_traversal() -> None:
    with pytest.raises(FileValidationError):
        safe_join("/base", "..", "etc", "passwd")


def test_validate_extension_allowed() -> None:
    validate_extension("document.pdf", {".pdf", ".txt"})


def test_validate_extension_denied() -> None:
    with pytest.raises(FileValidationError):
        validate_extension("file.exe", {".txt", ".pdf"})


def test_validate_extension_no_extension() -> None:
    with pytest.raises(FileValidationError):
        validate_extension("README", {".txt"})


def test_validate_file_size_ok() -> None:
    validate_file_size(500, 1000)


def test_validate_file_size_exceeded() -> None:
    with pytest.raises(FileValidationError):
        validate_file_size(2000, 1000)


def test_sanitize_filename() -> None:
    assert sanitize_filename("hello world.txt") == "hello world.txt"
    result = sanitize_filename("../etc/passwd")
    # / is replaced with _, then dots are collapsed and leading dots stripped
    assert result == "_etc_passwd" or result == "etc_passwd"
    assert sanitize_filename("file<>.txt") == "file.txt"
    assert "/" not in sanitize_filename("../malicious/file.txt")


# =============================================================================
# Security Module
# =============================================================================

def test_mask_secret() -> None:
    result = mask_secret("sk-tes...2345", visible_chars=3)
    # First 3 chars are "sk-", last 3 are "345"
    assert result == "sk-...345"


def test_mask_secret_short() -> None:
    assert mask_secret("abc") == "abc***"


def test_mask_secret_empty() -> None:
    assert mask_secret("") == ""


def test_validate_url_public() -> None:
    result = validate_url("https://8.8.8.8/path")
    assert "8.8.8.8" in result


def test_validate_url_localhost() -> None:
    with pytest.raises(FileValidationError):
        validate_url("http://127.0.0.1:8080")


def test_validate_url_no_scheme() -> None:
    with pytest.raises(FileValidationError):
        validate_url("ftp://example.com")


def test_validate_url_credentials() -> None:
    with pytest.raises(FileValidationError):
        validate_url("http://user:pass@example.com")


def test_validate_url_allow_private() -> None:
    result = validate_url("http://localhost/test", allow_private=True)
    assert "localhost" in result


def test_is_private_ip_localhost() -> None:
    assert is_private_ip("127.0.0.1") is True


def test_is_private_ip_private_range() -> None:
    assert is_private_ip("192.168.1.1") is True
    assert is_private_ip("10.0.0.1") is True
    assert is_private_ip("172.16.0.1") is True


def test_is_private_ip_public() -> None:
    assert is_private_ip("8.8.8.8") is False


def test_sanitize_text_input() -> None:
    result = sanitize_text_input("<script>alert('xss')</script>Hello")
    assert "script" not in result
    assert "Hello" in result


def test_sanitize_text_input_clean() -> None:
    result = sanitize_text_input("Hello, how are you?")
    assert result == "Hello, how are you?"


def test_sanitize_text_input_empty() -> None:
    assert sanitize_text_input("") == ""


# =============================================================================
# Utils Module
# =============================================================================

@pytest.mark.asyncio
async def test_async_retry_success() -> None:
    call_count = 0

    async def succeeds() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await async_retry(succeeds, max_attempts=3, delay=0.01)
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_async_retry_failure() -> None:
    call_count = 0

    async def always_fails() -> str:
        nonlocal call_count
        call_count += 1
        raise ValueError("always fails")

    with pytest.raises(ValueError):
        await async_retry(always_fails, max_attempts=3, delay=0.01)

    assert call_count == 3


def test_chunk_list() -> None:
    items = [1, 2, 3, 4, 5, 6, 7]
    result = chunk_list(items, 3)
    assert result == [[1, 2, 3], [4, 5, 6], [7]]


def test_chunk_list_empty() -> None:
    assert chunk_list([], 3) == []


def test_format_datetime() -> None:
    dt = datetime(2024, 1, 15, 14, 30, 0)
    result = format_datetime(dt)
    assert result == "2024-01-15 14:30:00"


def test_format_datetime_custom() -> None:
    dt = datetime(2024, 1, 15, 14, 30, 0)
    result = format_datetime(dt, "%d/%m/%Y")
    assert result == "15/01/2024"


# =============================================================================
# Exceptions Module
# =============================================================================

def test_exception_hierarchy() -> None:
    assert issubclass(AIError, CommonLibraryError)
    assert issubclass(AIConnectionError, AIError)
    assert issubclass(AIAuthenticationError, AIError)
    assert issubclass(AIRateLimitError, AIError)
    assert issubclass(AITimeoutError, AIError)
    assert issubclass(AIInvalidResponseError, AIError)
    assert issubclass(AISchemaValidationError, AIError)
    assert issubclass(ConfigurationError, CommonLibraryError)
    assert issubclass(DatabaseError, CommonLibraryError)
    assert issubclass(FileValidationError, CommonLibraryError)
    assert issubclass(PermissionDeniedError, CommonLibraryError)
    assert issubclass(TelegramIntegrationError, CommonLibraryError)
    assert issubclass(OperationConflictError, CommonLibraryError)


def test_exception_message() -> None:
    exc = ConfigurationError("missing env var")
    assert str(exc) == "missing env var"
    assert exc.message == "missing env var"


# =============================================================================
# Users Module
# =============================================================================

def test_user_creation() -> None:
    user = UserRecord(user_id=123, username="testuser", first_name="Test")
    assert user.user_id == 123
    assert user.username == "testuser"
    assert user.first_name == "Test"


def test_user_display_name_with_username() -> None:
    user = UserRecord(user_id=1, username="johndoe", first_name="John")
    assert user.display_name == "@johndoe"


def test_user_display_name_without_username() -> None:
    user = UserRecord(user_id=42, first_name="John", last_name="Doe")
    assert user.display_name == "John Doe"


def test_user_permission_check() -> None:
    user = UserRecord(user_id=2, permissions=["read", "write"])
    assert user.has_permission("read") is True
    assert user.has_permission("delete") is False


def test_user_from_telegram() -> None:
    user = user_from_telegram(
        user_id=12345,
        username="alice",
        first_name="Alice",
        last_name="Smith",
    )
    assert user.user_id == 12345
    assert user.username == "alice"
    assert user.first_name == "Alice"
    assert user.last_name == "Smith"
    assert user.created_at is not None


# =============================================================================
# Public API imports
# =============================================================================

def test_public_api_imports() -> None:
    from hunttech_bot_common import (
        AIAuthenticationError,
        AIConnectionError,
        AIError,
        AIInvalidResponseError,
        AIRateLimitError,
        AISchemaValidationError,
        AITimeoutError,
        CommonLibraryError,
        ConfigurationError,
        DatabaseError,
        FileValidationError,
        OperationConflictError,
        PermissionDeniedError,
        TelegramIntegrationError,
    )
    assert CommonLibraryError is not None
    assert ConfigurationError is not None


# =============================================================================
# Edge Cases
# =============================================================================

def test_sanitize_filename_empty_after_sanitization() -> None:
    result = sanitize_filename("")
    assert result.startswith("untitled_")


def test_sanitize_filename_only_special_chars() -> None:
    result = sanitize_filename("../../../")
    assert ".." not in result


def test_split_long_message_no_paragraphs() -> None:
    long = "word " * 2000
    result = split_long_message(long, max_len=500)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 500


# ═══════════════════════════════════════════════
# Users module tests
# ═══════════════════════════════════════════════

class TestAccessManager:
    """Tests for AccessManager."""

    def test_init_creates_empty_store(self, tmp_path: Path) -> None:
        """AccessManager starts with no users."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.get_allowed_users() == []
        assert am.get_user_count() == 0
        assert am.get_admin_ids() == {100}

    def test_master_admin_always_allowed(self, tmp_path: Path) -> None:
        """Master admin is always allowed without being in user list."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.is_allowed(100) is True
        assert am.is_admin(100) is True

    def test_add_user(self, tmp_path: Path) -> None:
        """Adding a user returns True and user becomes allowed."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot", auto_save=True)
        result = am.add_user(user_id=200, username="ivanov", added_by=100)
        assert result is True
        assert am.is_allowed(200) is True
        assert am.get_user_count() == 1

    def test_add_duplicate_user_returns_false(self, tmp_path: Path) -> None:
        """Adding an existing user returns False but updates info."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        result = am.add_user(user_id=200, username="ivanov_new", added_by=100)
        assert result is False
        assert am.is_allowed(200) is True

    def test_remove_user(self, tmp_path: Path) -> None:
        """Removing a user revokes access."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        result = am.remove_user(200)
        assert result is True
        assert am.is_allowed(200) is False

    def test_remove_nonexistent_user_returns_false(self, tmp_path: Path) -> None:
        """Removing a nonexistent user returns False."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.remove_user(999) is False

    def test_unknown_user_not_allowed(self, tmp_path: Path) -> None:
        """Unknown user is not allowed."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.is_allowed(999) is False

    def test_ban_user(self, tmp_path: Path) -> None:
        """Banned user loses access."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        assert am.is_allowed(200) is True
        am.ban_user(200)
        assert am.is_allowed(200) is False
        assert am.is_banned(200) is True

    def test_unban_user(self, tmp_path: Path) -> None:
        """Unbanned user regains access."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        am.ban_user(200)
        am.unban_user(200)
        assert am.is_allowed(200) is True
        assert am.is_banned(200) is False

    def test_get_user(self, tmp_path: Path) -> None:
        """get_user returns the user record."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        user = am.get_user(200)
        assert user is not None
        assert user["username"] == "ivanov"
        assert am.get_user(999) is None

    def test_persistence(self, tmp_path: Path) -> None:
        """Data persists to JSON file and reloads correctly."""
        data_file = tmp_path / "access.json"
        am1 = AccessManager(data_file, master_admin_id=100, bot_name="TestBot", auto_save=True)
        am1.add_user(user_id=200, username="ivanov", added_by=100)
        am1.add_user(user_id=201, username="petrov", added_by=100)

        # Create new instance reading same file
        am2 = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am2.get_user_count() == 2
        assert am2.is_allowed(200) is True
        assert am2.is_allowed(201) is True

    def test_pending_requests(self, tmp_path: Path) -> None:
        """Access requests workflow works correctly."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")

        # New request
        result = am.request_access(user_id=300, username="new_user", first_name="New")
        assert result["is_new"] is True
        assert result["is_already_allowed"] is False
        assert am.get_request_status(300) == "pending"

        # Duplicate request
        result2 = am.request_access(user_id=300)
        assert result2["is_new"] is False

        # Approve
        assert am.approve_request(300, approved_by=100) is True
        assert am.is_allowed(300) is True
        assert am.get_request_status(300) is None  # Removed from pending

    def test_request_from_allowed_user(self, tmp_path: Path) -> None:
        """Request from already-allowed user returns is_already_allowed."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(user_id=200, username="ivanov", added_by=100)
        result = am.request_access(200)
        assert result["is_already_allowed"] is True

    def test_deny_request(self, tmp_path: Path) -> None:
        """Denied request has 'denied' status."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.request_access(user_id=300, username="new_user")
        assert am.deny_request(300) is True
        assert am.get_request_status(300) == "denied"
        assert am.is_allowed(300) is False

    def test_deny_nonexistent_request(self, tmp_path: Path) -> None:
        """Denying a nonexistent request returns False."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.deny_request(999) is False

    def test_get_pending_requests(self, tmp_path: Path) -> None:
        """get_pending_requests returns all pending requests."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.request_access(300, username="user1")
        am.request_access(301, username="user2")
        pending = am.get_pending_requests()
        assert len(pending) == 2

    def test_command_permissions(self, tmp_path: Path) -> None:
        """Command permissions are checked correctly."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        cmds = {
            "start": set(),
            "setup": {"setup"},
            "admin_panel": {"admin"},
        }
        am.set_command_permissions(cmds)
        assert am.get_command_permissions() == cmds

    def test_user_can_use_command(self, tmp_path: Path) -> None:
        """user_can_use_command checks permissions."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        cmds = {"start": set(), "setup": {"setup"}, "admin": {"admin"}}
        am.set_command_permissions(cmds)
        am.add_user(200, username="user1")

        # Admin (master) can use any command
        assert am.user_can_use_command(100, "admin") is True
        assert am.user_can_use_command(100, "setup") is True

        # Regular user can use commands without permissions
        assert am.user_can_use_command(200, "start") is True

        # Regular user cannot use commands requiring permissions they don't have
        assert am.user_can_use_command(200, "setup") is False

        # Add permission
        am.add_permission(200, "setup")
        assert am.user_can_use_command(200, "setup") is True

    def test_filter_commands(self, tmp_path: Path) -> None:
        """filter_commands returns only allowed commands for user."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        cmds = {"start": set(), "setup": {"setup"}, "admin": {"admin"}}
        am.set_command_permissions(cmds)

        commands = [
            CommandDef(command="start", title="Start", group="main"),
            CommandDef(command="setup", title="Setup", permissions={"setup"}, group="settings"),
            CommandDef(command="admin", title="Admin", admin=True, group="admin"),
            CommandDef(command="hidden", title="Hidden", hidden=True, group="admin"),
        ]

        # Admin sees all
        admin_cmds = am.filter_commands(commands, 100)
        assert len(admin_cmds) == 4

        # Regular user sees only accessible
        am.add_user(200, username="user1")
        user_cmds = am.filter_commands(commands, 200)
        assert len(user_cmds) == 1  # Only start
        assert user_cmds[0].command == "start"

        # User with setup permission
        am.add_permission(200, "setup")
        setup_cmds = am.filter_commands(commands, 200)
        assert len(setup_cmds) == 2  # start + setup

    def test_add_remove_permission(self, tmp_path: Path) -> None:
        """Adding and removing permissions works."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(200, username="user1")

        assert am.add_permission(200, "setup") is True
        assert am.has_permission(200, "setup") is True
        assert am.get_user_permissions(200) == {"setup"}

        assert am.remove_permission(200, "setup") is True
        assert am.has_permission(200, "setup") is False

    def test_add_permission_nonexistent_user(self, tmp_path: Path) -> None:
        """Adding permission to nonexistent user returns False."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.add_permission(999, "setup") is False

    def test_set_user_permissions(self, tmp_path: Path) -> None:
        """set_user_permissions replaces all permissions."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(200, username="user1")
        am.add_permission(200, "setup")
        am.set_user_permissions(200, {"admin", "setup"})
        assert am.get_user_permissions(200) == {"admin", "setup"}

    def test_user_settings(self, tmp_path: Path) -> None:
        """User settings CRUD works."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        am.add_user(200, username="user1")

        # Get empty settings
        assert am.get_user_settings(200) == {}

        # Update settings
        assert am.update_user_settings(200, {"theme": "dark", "lang": "ru"}) is True
        assert am.get_user_settings(200) == {"theme": "dark", "lang": "ru"}

        # Merge
        assert am.update_user_settings(200, {"notify": True}) is True
        assert am.get_user_settings(200) == {"theme": "dark", "lang": "ru", "notify": True}

        # Reset
        assert am.reset_user_settings(200, {"theme"}) is True
        assert "theme" not in am.get_user_settings(200)

    def test_get_nonexistent_user_settings(self, tmp_path: Path) -> None:
        """Getting settings for nonexistent user returns empty dict."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.get_user_settings(999) == {}

    def test_get_pending_requests_empty(self, tmp_path: Path) -> None:
        """get_pending_requests returns empty list when none."""
        data_file = tmp_path / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.get_pending_requests() == []

    def test_reload_from_missing_file(self, tmp_path: Path) -> None:
        """Reload from non-existent file doesn't crash."""
        data_file = tmp_path / "nonexistent" / "access.json"
        am = AccessManager(data_file, master_admin_id=100, bot_name="TestBot")
        assert am.get_allowed_users() == []

class TestUserSettingsManager:
    """Tests for UserSettingsManager."""

    def test_init_with_settings(self) -> None:
        """Settings manager initialises with common and individual keys."""
        common = {"endpoint": "https://api.example.com", "model": "gpt-4"}
        individual = {"theme", "language"}
        mgr = UserSettingsManager(common_settings=common, individual_keys=individual)
        assert mgr.common == common
        assert mgr.individual_keys == individual

    def test_is_individual_key(self) -> None:
        """is_individual_key correctly identifies individual keys."""
        mgr = UserSettingsManager(common_settings={}, individual_keys={"theme"})
        assert mgr.is_individual_key("theme") is True
        assert mgr.is_individual_key("model") is False

    def test_get_common_keys(self) -> None:
        """get_common_keys returns common settings keys."""
        mgr = UserSettingsManager(
            common_settings={"endpoint": "x", "model": "y"},
            individual_keys={"theme"},
        )
        assert mgr.get_common_keys() == {"endpoint", "model"}

    def test_update_individual_filters_keys(self) -> None:
        """update_individual only accepts keys in individual_keys."""
        from unittest.mock import MagicMock

        am = MagicMock()
        am.get_user_settings.return_value = {"theme": "light", "lang": "ru"}
        mgr = UserSettingsManager(
            common_settings={"endpoint": "x"},
            individual_keys={"theme", "lang"},
        )

        result = mgr.update_individual(
            200, {"theme": "dark", "secret": "should_not_pass"}, am
        )
        assert result == {"theme": "dark"}
        am.update_user_settings.assert_called_once_with(200, {"theme": "dark"})

    def test_get_settings_help_text(self) -> None:
        """get_settings_help_text generates correct output."""
        from unittest.mock import MagicMock

        am = MagicMock()
        am.get_user_settings.return_value = {
            "endpoint": "https://api.example.com",
            "theme": "dark",
            "api_key": "sk-12345678secret",
        }
        mgr = UserSettingsManager(
            common_settings={"endpoint": "https://api.example.com", "api_key": "sk-12345678secret"},
            individual_keys={"theme"},
        )

        text = mgr.get_settings_help_text(200, am)
        assert "Common settings (read-only)" in text
        assert "Individual settings (editable" in text
        # API key should be masked
        assert "sk-1****" in text

    def test_apply_common_to_user(self) -> None:
        """apply_common_to_user copies common settings to user."""
        from unittest.mock import MagicMock

        am = MagicMock()
        am.get_user_settings.return_value = {"theme": "dark"}
        mgr = UserSettingsManager(
            common_settings={"endpoint": "https://api.example.com", "model": "gpt-4"},
            individual_keys=set(),
        )

        result = mgr.apply_common_to_user(200, am)
        assert result is True
        am.update_user_settings.assert_called_once()

class TestUserRecord:
    """Tests for UserRecord."""

    def test_display_name_full_name(self) -> None:
        """display_name returns full_name if set."""
        user = UserRecord(
            user_id=200, full_name="Ivan Ivanov",
            username="ivanov", first_name="Ivan",
        )
        assert user.display_name == "Ivan Ivanov"

    def test_display_name_username(self) -> None:
        """display_name returns @username if no full_name."""
        user = UserRecord(user_id=200, username="ivanov", first_name="")
        assert user.display_name == "@ivanov"

    def test_display_name_user_id(self) -> None:
        """display_name falls back to User#ID."""
        user = UserRecord(user_id=200)
        assert user.display_name == "User#200"

    def test_mention_html(self) -> None:
        """mention_html generates correct HTML."""
        user = UserRecord(user_id=200, full_name="Ivan Ivanov")
        expected = '<a href="tg://user?id=200">Ivan Ivanov</a>'
        assert user.mention_html == expected

    def test_has_permission(self) -> None:
        """has_permission checks permission list."""
        user = UserRecord(user_id=200, permissions=["setup", "admin"])
        assert user.has_permission("setup") is True
        assert user.has_permission("nonexistent") is False

    def test_user_from_telegram(self) -> None:
        """user_from_telegram creates UserRecord from Telegram data."""
        user = user_from_telegram(
            user_id=200, username="ivanov",
            first_name="Ivan", last_name="Ivanov",
            language_code="ru",
        )
        assert user.user_id == 200
        assert user.username == "ivanov"
        assert user.full_name == "Ivan Ivanov"
        assert user.first_name == "Ivan"
        assert user.language_code == "ru"
        assert user.created_at != ""

    def test_user_from_telegram_no_last_name(self) -> None:
        """user_from_telegram works with only first_name."""
        user = user_from_telegram(user_id=200, first_name="Ivan")
        assert user.full_name == "Ivan"
        assert user.last_name is None
