"""Tests for hunttech_bot_common.media — логотип HuntTech над приветствием."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hunttech_bot_common.media import LOGO_PATH, send_logo


class TestSendLogo:
    def test_logo_file_exists(self) -> None:
        assert LOGO_PATH.exists(), f"логотип отсутствует: {LOGO_PATH}"
        assert LOGO_PATH.stat().st_size > 10_000

    def test_send_success(self) -> None:
        bot = AsyncMock()
        ok = asyncio.run(send_logo(bot, 123))
        assert ok is True
        bot.send_photo.assert_awaited_once()
        assert bot.send_photo.await_args.kwargs["chat_id"] == 123
        photo = bot.send_photo.await_args.kwargs["photo"]
        assert photo.path.endswith("hunttech_logo.png")

    def test_send_success_ptb_bot(self) -> None:
        """PTB-бот (python-telegram-bot) получает telegram.InputFile.

        Регресс-тест бага: импорт-проба выбирала aiogram FSInputFile и для
        PTB-бота (в venv Hermes установлены ОБА фреймворка) →
        `FSInputFile.read() missing 'bot'`.
        """
        from telegram import Bot as PTBBot
        from telegram import InputFile

        from hunttech_bot_common.media import LOGO_PATH, _photo_for_bot

        bot = PTBBot(token="1:test:token")
        photo = _photo_for_bot(bot)
        assert isinstance(photo, InputFile)
        # PTB v22: Path не принимается — файл читается в bytes
        assert photo.input_file_content == LOGO_PATH.read_bytes()

    def test_send_failure_returns_false(self) -> None:
        bot = AsyncMock()
        bot.send_photo = AsyncMock(side_effect=RuntimeError("boom"))
        ok = asyncio.run(send_logo(bot, 123))
        assert ok is False  # не роняет поток приветствия

    def test_missing_file_returns_false(self) -> None:
        bot = AsyncMock()
        with patch("hunttech_bot_common.media.LOGO_PATH", Path("/nonexistent/logo.png")):
            ok = asyncio.run(send_logo(bot, 123))
        assert ok is False
        bot.send_photo.assert_not_awaited()
