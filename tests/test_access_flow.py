"""Тесты access-флоу: /start → авто-запрос доступа → уведомление админу.

Покрывают алгоритм владельца (2026-08-07, @hunttech_short_vacancy_bot):
неавторизованный пользователь нажимает /start → администратору прилетает
сообщение с кнопками «✅ Разрешить» / «❌ Запретить»; при одобрении
пользователь получает доступ как обычный пользователь (не администратор).

Регрессия: CallbackAccessMiddleware блокировал access:request от
неавторизованных — кнопка «📨 Запросить доступ» была мёртвой.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hunttech_bot_common.users import AccessManager
from hunttech_bot_common.users.middleware import CallbackAccessMiddleware
from hunttech_bot_common.users.telegram import start_access_gate


@pytest.fixture
def am():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AccessManager(
            data_path=Path(tmpdir) / "access.json",
            master_admin_id=12345,
            bot_name="TestBot",
            auto_save=True,
        )
        yield manager


def _mk_user(user_id: int = 908286178, username: str = "pavel_korab",
             first_name: str = "Павел", last_name: str = "Иванов"):
    return SimpleNamespace(
        id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        language_code="ru",
    )


def _mk_event(user_id: int = 908286178, data: str | None = None):
    """Message-подобный или CallbackQuery-подобный объект."""
    from_user = _mk_user(user_id)
    if data is not None:
        return SimpleNamespace(from_user=from_user, data=data,
                               answer=AsyncMock(), message=SimpleNamespace())
    return SimpleNamespace(from_user=from_user, answer=AsyncMock())


class TestCallbackAccessMiddleware:
    """Middleware должен пропускать access:* callback'и от неавторизованных."""

    async def test_passes_access_request_from_unauthorized(self, am):
        mw = CallbackAccessMiddleware(lambda: am)
        handler = AsyncMock()
        event = _mk_event(data="access:request")
        await mw(handler, event, {})
        handler.assert_awaited_once_with(event, {})
        event.answer.assert_not_awaited()

    async def test_passes_access_check_status_from_unauthorized(self, am):
        mw = CallbackAccessMiddleware(lambda: am)
        handler = AsyncMock()
        event = _mk_event(data="access:check_status")
        await mw(handler, event, {})
        handler.assert_awaited_once_with(event, {})

    async def test_blocks_other_callbacks_from_unauthorized(self, am):
        mw = CallbackAccessMiddleware(lambda: am)
        handler = AsyncMock()
        event = _mk_event(data="vac:something")
        await mw(handler, event, {})
        handler.assert_not_awaited()
        event.answer.assert_awaited_once()

    async def test_allows_allowed_user_callbacks(self, am):
        am.add_user(user_id=908286178, username="pavel_korab")
        mw = CallbackAccessMiddleware(lambda: am)
        handler = AsyncMock()
        event = _mk_event(data="vac:something")
        await mw(handler, event, {})
        handler.assert_awaited_once_with(event, {})


class TestStartAutoRequest:
    """/start неизвестного пользователя → авто-запрос + уведомление админу."""

    async def test_start_creates_request_and_notifies_admin(self, am):
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace()),
        )
        event = _mk_event(user_id=908286178)

        result = await start_access_gate(
            event=event,
            user_id=908286178,
            access_manager=am,
            bot=bot,
            commands=None,
        )

        # Возврат нового контракта: запрос создан
        assert result == "requested"
        # Пользователю — «Запрос отправлен»
        assert "Запрос отправлен" in event.answer.call_args.args[0]
        # Админу — уведомление с кнопками Разрешить/Запретить
        assert bot.send_message.awaited_once
        kwargs = bot.send_message.call_args.kwargs
        assert kwargs["chat_id"] == 12345
        text = kwargs["text"]
        assert "Новый запрос доступа" in text
        assert "908286178" in text
        kb = kwargs["reply_markup"]
        rows = kb.inline_keyboard
        buttons = [b.callback_data for row in rows for b in row]
        assert f"admin:allow:908286178" in buttons
        assert f"admin:deny:908286178" in buttons
        # Запрос лежит в pending
        assert am.get_request_status(908286178) == "pending"

    async def test_start_twice_does_not_spam_admin(self, am):
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace()),
        )
        await start_access_gate(event=_mk_event(), user_id=908286178,
                                access_manager=am, bot=bot, commands=None)
        assert bot.send_message.await_count == 1

        # Повторный /start — статус pending, нового уведомления админу нет
        event2 = _mk_event()
        result = await start_access_gate(event=event2, user_id=908286178,
                                         access_manager=am, bot=bot,
                                         commands=None)
        assert result == "pending"
        assert bot.send_message.await_count == 1
        assert "Запрос уже отправлен" in event2.answer.call_args.args[0]

    async def test_approved_user_is_regular_not_admin(self, am):
        """Одобренный по кнопке «Разрешить» — обычный пользователь."""
        am.request_access(user_id=908286178, username="pavel_korab",
                          first_name="Павел", last_name="Иванов")
        am.approve_request(908286178, approved_by=12345)
        assert am.is_allowed(908286178)
        assert not am.is_admin(908286178)  # не администратор
        assert am.get_request_status(908286178) is None  # запрос снят

    async def test_denied_user_can_rerquest_after_deny(self, am):
        """После отказа повторный запрос создаёт НОВЫЙ запрос (is_new=True)."""
        r1 = am.request_access(user_id=908286178, username="pavel_korab",
                               first_name="Павел")
        assert r1["is_new"] is True
        am.deny_request(908286178)
        assert am.get_request_status(908286178) == "denied"

        r2 = am.request_access(user_id=908286178, username="pavel_korab",
                               first_name="Павел")
        assert r2["is_new"] is True  # новый запрос вместо вечного «уже отправлен»
        assert am.get_request_status(908286178) == "pending"

    async def test_admin_notification_html_survives_underscore_username(self, am):
        """Уведомление админу НЕ падает с username вида pavel_korab.

        Регрессия 2026-08-07: текст шёл в глобальный parse_mode=Markdown бота
        без явного parse_mode → одиночное `_` в username давало
        TelegramBadRequest «can't parse entities», админ не получал запрос.
        """
        from aiogram.enums import ParseMode

        from hunttech_bot_common.users.telegram import request_access_handler

        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace()))
        event = _mk_event(user_id=908286178)  # username по умолчанию pavel_korab

        result = await request_access_handler(
            event, 908286178, am, bot, bot_name="TestBot",
        )
        assert result == "new_request"
        kwargs = bot.send_message.call_args.kwargs
        assert kwargs["parse_mode"] == ParseMode.HTML  # явно, не глобальный бота
        text = kwargs["text"]
        assert "<b>Новый запрос доступа</b>" in text
        assert "@pavel_korab" in text  # в HTML подчёркивание безопасно
        assert f"admin:allow:908286178" in [
            b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row
        ]

    async def test_pending_notifications_sent_on_startup(self, am):
        """При старте бота админу уходят все pending-запросы (потерянные
        уведомления не пропадают), denied игнорируются."""
        from hunttech_bot_common.users.telegram import notify_admin_of_pending_requests

        am.request_access(user_id=111, username="user_one", first_name="Один")
        am.request_access(user_id=222, username="user_two", first_name="Два")
        am.request_access(user_id=333, username="user_three", first_name="Три")
        am.deny_request(333)  # отклонённый — уведомления не будет

        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace()))
        sent = await notify_admin_of_pending_requests(bot, am, bot_name="TestBot")
        assert sent == 2
        assert bot.send_message.await_count == 2
        for call in bot.send_message.call_args_list:
            kwargs = call.kwargs
            assert kwargs["chat_id"] == 12345
            assert "admin:allow:" in str(kwargs["reply_markup"])
            assert "<b>Запрос доступа</b>" in kwargs["text"]

    async def test_approval_notifies_user_and_sends_welcome(self, am):
        """При «Разрешить» пользователь получает оповещение + приветствие с /help."""
        from hunttech_bot_common.users.telegram import admin_approval_callback

        am.request_access(user_id=100, username="newuser", first_name="New")
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace()))
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=12345),
            data="admin:allow:100",
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )

        await admin_approval_callback(
            callback, am, bot, bot_name="TestBot",
            welcome_text="👋 Добро пожаловать!\nИспользуйте /help",
            welcome_parse_mode=None,
        )

        assert am.is_allowed(100)  # обычный пользователь, не админ
        assert not am.is_admin(100)
        texts = [c.kwargs["text"] for c in bot.send_message.call_args_list]
        assert len(texts) == 2
        assert "Вас пригласили" in texts[0]      # оповещение о доступе
        assert "/help" in texts[1]                # приветствие с командой
        assert texts[1] == "👋 Добро пожаловать!\nИспользуйте /help"
