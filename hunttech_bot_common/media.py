"""Медиа: логотип HuntTech для приветствий (стандарт HuntTech).

При /start и при старте бота логотип компании отправляется ПЕРВЫМ
сообщением — над приветствием (эталон — @hunttech_short_vacancy_bot,
одобрено владельцем).

Файл логотипа лежит в ``hunttech_bot_common/assets/hunttech_logo.png``.
``send_logo`` не роняет поток приветствия: при отсутствии файла или
ошибке отправки возвращает False.

Поддерживает и aiogram (``FSInputFile``), и python-telegram-bot
(``telegram.InputFile``) — фреймворк определяется доступным импортом.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "hunttech_logo.png"


async def send_logo(bot: Any, chat_id: int) -> bool:
    """Отправить фото-логотип HuntTech над приветствием.

    Args:
        bot: aiogram Bot или PTB Application.bot.
        chat_id: получатель.

    Returns:
        True при успехе; False при отсутствии файла или ошибке
        (не роняет поток приветствия).
    """
    try:
        if not LOGO_PATH.exists():
            logger.warning("Логотип не найден: %s", LOGO_PATH)
            return False
        try:
            from aiogram.types import FSInputFile

            photo = FSInputFile(str(LOGO_PATH))
        except ImportError:
            from telegram import InputFile  # python-telegram-bot

            photo = InputFile(LOGO_PATH)
        await bot.send_photo(chat_id=chat_id, photo=photo)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Не удалось отправить логотип %s: %s", chat_id, e)
        return False
