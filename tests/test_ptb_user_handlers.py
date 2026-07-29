"""Tests for PTB user management handlers."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from hunttech_bot_common.users.access import AccessManager
from hunttech_bot_common.users.ptb import PTBUserHandlers, get_admin_commands, get_standard_commands

import pytest


# ─── Fixtures ───

@pytest.fixture
def am() -> AccessManager:
    tmp = tempfile.mkdtemp()
    return AccessManager(
        data_path=Path(tmp) / "access.json",
        master_admin_id=100,
        bot_name="Test Bot",
    )


@pytest.fixture
def handlers(am: AccessManager) -> PTBUserHandlers:
    return PTBUserHandlers(access_manager=am, bot_name="Test Bot")


@pytest.fixture
def make_update():
    """Factory for mock updates."""

    def _make(user_id: int, text: str = "/start") -> mock.MagicMock:
        update = mock.MagicMock()
        update.effective_user.id = user_id
        update.effective_user.username = f"user{user_id}"
        update.effective_user.first_name = f"User"
        update.effective_user.last_name = f"#{user_id}"
        msg = mock.MagicMock()
        msg.text = text
        msg.reply_text = mock.AsyncMock()
        update.effective_message = msg
        return update

    return _make


# ─── Access checks ───

class TestAccessChecks:
    async def test_is_allowed_admin(self, handlers: PTBUserHandlers) -> None:
        update = mock.MagicMock()
        update.effective_user.id = 100
        assert await handlers.is_allowed(update)

    async def test_is_allowed_unknown(self, handlers: PTBUserHandlers) -> None:
        update = mock.MagicMock()
        update.effective_user.id = 999
        assert not await handlers.is_allowed(update)

    async def test_is_allowed_added_user(self, handlers: PTBUserHandlers, am: AccessManager) -> None:
        am.add_user(user_id=42)
        update = mock.MagicMock()
        update.effective_user.id = 42
        assert await handlers.is_allowed(update)

    async def test_is_admin_master(self, handlers: PTBUserHandlers) -> None:
        update = mock.MagicMock()
        update.effective_user.id = 100
        assert await handlers.is_admin(update)

    async def test_is_admin_other(self, handlers: PTBUserHandlers) -> None:
        update = mock.MagicMock()
        update.effective_user.id = 42
        assert not await handlers.is_admin(update)


# ─── Start handler ───

class TestStartHandler:
    async def test_admin_welcome(self, handlers: PTBUserHandlers, make_update) -> None:
        update = make_update(100)
        with mock.patch.object(handlers, "_welcome_admin", "ADMIN OK"):
            await handlers.start_handler(update, mock.MagicMock())
        update.effective_message.reply_text.assert_called_once()
        assert "ADMIN" in update.effective_message.reply_text.call_args[0][0]

    async def test_user_welcome(self, handlers: PTBUserHandlers, am: AccessManager) -> None:
        am.add_user(user_id=42)
        update = mock.MagicMock()
        update.effective_user.id = 42
        update.effective_user.username = "user"
        update.effective_user.first_name = "User"
        update.effective_user.last_name = ""
        msg = mock.AsyncMock()
        update.effective_message = msg
        with mock.patch.object(handlers, "_welcome_user", "USER OK"):
            await handlers.start_handler(update, mock.MagicMock())
        msg.reply_text.assert_called_once()
        assert "USER" in msg.reply_text.call_args[0][0]

    async def test_unknown_user_request_access(self, handlers: PTBUserHandlers) -> None:
        update = mock.MagicMock()
        update.effective_user.id = 999
        update.effective_user.username = "newb"
        update.effective_user.first_name = "New"
        update.effective_user.last_name = "User"
        msg = mock.AsyncMock()
        update.effective_message = msg
        context = mock.MagicMock()
        context.bot.send_message = mock.AsyncMock()
        await handlers.start_handler(update, context)
        msg.reply_text.assert_called_once()
        assert "Запрос" in msg.reply_text.call_args[0][0]

    async def test_request_access_alias(self, handlers: PTBUserHandlers) -> None:
        """/request_access should work the same as /start for unknown users."""
        update = mock.MagicMock()
        update.effective_user.id = 777
        update.effective_user.username = "alias_test"
        update.effective_user.first_name = "Alias"
        update.effective_user.last_name = ""
        msg = mock.AsyncMock()
        update.effective_message = msg
        context = mock.MagicMock()
        context.bot.send_message = mock.AsyncMock()
        await handlers.request_access_handler(update, context)
        msg.reply_text.assert_called_once()


# ─── User management ───

class TestUserCommand:
    async def test_list_users(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        am.add_user(user_id=42, username="u1", full_name="User One")
        update = make_update(100, "/user list")
        msg = update.effective_message
        await handlers.user_command_handler(update, mock.MagicMock())
        msg.reply_text.assert_called_once()
        assert "User One" in msg.reply_text.call_args[0][0]

    async def test_add_user(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        update = make_update(100, "/user add 42")
        await handlers.user_command_handler(update, mock.MagicMock())
        assert am.is_allowed(42)

    async def test_remove_user(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        am.add_user(user_id=42)
        update = make_update(100, "/user remove 42")
        await handlers.user_command_handler(update, mock.MagicMock())
        assert not am.is_allowed(42)

    async def test_ban_user(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        am.add_user(user_id=42)
        update = make_update(100, "/user ban 42")
        await handlers.user_command_handler(update, mock.MagicMock())
        assert not am.is_allowed(42)

    async def test_unban_user(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        am.add_user(user_id=42)
        am.ban_user(42)
        update = make_update(100, "/user unban 42")
        await handlers.user_command_handler(update, mock.MagicMock())
        assert am.is_allowed(42)

    async def test_non_admin_cannot_manage(self, handlers: PTBUserHandlers, make_update) -> None:
        update = make_update(42, "/user list")
        await handlers.user_command_handler(update, mock.MagicMock())
        update.effective_message.reply_text.assert_called_once()
        assert "администратор" in update.effective_message.reply_text.call_args[0][0]

    async def test_missing_arg(self, handlers: PTBUserHandlers, make_update) -> None:
        update = make_update(100, "/user add")
        await handlers.user_command_handler(update, mock.MagicMock())
        update.effective_message.reply_text.assert_called_once()
        assert "Telegram ID" in update.effective_message.reply_text.call_args[0][0]

    async def test_invalid_id(self, handlers: PTBUserHandlers, make_update) -> None:
        update = make_update(100, "/user add abc")
        await handlers.user_command_handler(update, mock.MagicMock())
        update.effective_message.reply_text.assert_called_once()
        assert "числовой" in update.effective_message.reply_text.call_args[0][0]

    async def test_cannot_remove_admin(self, handlers: PTBUserHandlers, am: AccessManager, make_update) -> None:
        update = make_update(100, f"/user remove {am.master_admin_id}")
        await handlers.user_command_handler(update, mock.MagicMock())
        update.effective_message.reply_text.assert_called_once()
        assert "Нельзя" in update.effective_message.reply_text.call_args[0][0]


# ─── Registration ───

class TestRegistration:
    def test_register_all(self, handlers: PTBUserHandlers) -> None:
        app = mock.MagicMock()
        handlers.register(app)
        handler_names = set()
        for c in app.add_handler.call_args_list:
            h = c[0][0]
            handler_names.update(getattr(h, "commands", frozenset()))
        assert "start" in handler_names
        assert "request_access" in handler_names
        assert "user" in handler_names

    def test_register_exclude(self, handlers: PTBUserHandlers) -> None:
        app = mock.MagicMock()
        handlers.register(app, exclude={"start"})
        handler_names = set()
        for c in app.add_handler.call_args_list:
            h = c[0][0]
            handler_names.update(getattr(h, "commands", frozenset()))
        assert "start" not in handler_names
        assert "user" in handler_names


# ─── Command definitions ───

class TestCommandDefs:
    def test_standard_commands(self) -> None:
        cmds = get_standard_commands()
        assert len(cmds) >= 3
        names = {c.command for c in cmds}
        assert "start" in names
        assert "help" in names
        assert "request_access" in names

    def test_admin_commands(self) -> None:
        cmds = get_admin_commands()
        assert len(cmds) >= 1
        assert any(c.command == "user" for c in cmds)
        assert all(c.admin for c in cmds)


# ─── AccessManager property ───

class TestAccessManagerProperty:
    def test_access_manager(self, handlers: PTBUserHandlers, am: AccessManager) -> None:
        assert handlers.access_manager is am
