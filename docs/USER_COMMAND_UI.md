# Интерфейс /user — управление доступом (стандарт HuntTech)

> Проверено и одобрено владельцем (hunttech_short_vavancy_bot, 2026-08).
> **Этот интерфейс — стандарт для ВСЕХ новых HuntTech-ботов.**
> Эталонная реализация: `hunttech_short_vavancy_bot/src/.../handlers/user_handler.py`
> + `start.py` (`_activate_invited_by_username`).

## Команды

| Команда | Назначение | Доступ |
|---------|-----------|--------|
| `/user list` | Список пользователей: активные, ожидают активации, ожидают одобрения | только админ |
| `/user add @username` | Пригласить по username (активация при первом `/start`) | только админ |
| `/user add <telegram_id>` | Выдать доступ сразу по ID (+ уведомление) | только админ |
| `/user delete @username` | Отозвать доступ по username | только админ |
| `/user delete <id>` | Отозвать доступ по ID | только админ |
| `/setup user list\|add\|delete` | Алиас-подкоманда `/setup` для тех же операций | только админ |

## Секции `/user list` (порядок вывода)

1. **✅ Активные** — разрешённые пользователи с реальным Telegram ID
   (user_id > 0). Формат строки: `` • `123456789` — `Имя Фамилия` ``.
   Для каждого — кнопка `❌ <имя>` (`userlist:del:<id>`).
2. **⏳ Ожидают активации** — приглашённые по username, ещё не написавшие
   боту (user_id <= 0, см. «Ключи приглашений»). Формат:
   `` • `@username` (не написал(а) боту) ``. Подсказка: «После первого
   `/start` пользователь активируется автоматически».
3. **👑 Администраторы** — `ID {master_admin_id}`.
4. **⏳ Ожидают одобрения (запросы доступа)** — пользователи, запросившие
   доступ (`/request_access` или кнопка «📨 Запросить доступ» на экране
   «Доступ запрещён»), статус != denied. Для каждого — кнопки
   `✅ <username>` (`userlist:approve:<id>`) и `❌ <username>`
   (`userlist:deny:<id>`). Подсказка: «Кнопки под списком: ✅ — выдать
   доступ, ❌ — отклонить запрос».
5. Пустой список (нет ни users, ни waiting) — «📭 Список разрешённых
   пользователей пуст.» + как добавить первого + что делать рекрутеру.

Кнопки `userlist:del|approve|deny:<id>` обрабатываются в одном callback
(`userlist_callback`), регистрация: `dp.callback_query.register(..., F.data.startswith("userlist:"))`.
Права: `is_admin` (только master_admin_id) — иначе «🚫 Только администратор».

## Разъяснения после операций (обязательно)

Каждая операция объясняет админу, что сделано и что нужно рекрутеру:

- **add по ID (уведомление отправлено)**: «Если он ещё не писал боту —
  попросите его открыть чат с ботом и нажать `/start`: он увидит
  приветствие и сможет самостоятельно загружать вакансии (`/load`),
  генерировать (`/show`) и публиковать объявления (`/post`).»
- **add по ID (уведомление не ушло)**: «попросите рекрутера написать боту
  `/start` — бот поприветствует его и выдаст доступ автоматически».
- **add по username**: «После первого `/start` бот активирует его
  автоматически» + инструкция.
- **delete**: «Доступ отозван. Если он напишет боту `/start`, увидит
  «🚫 Доступ запрещён» и сможет отправить запрос на доступ — он придёт
  вам на подтверждение».
- **approve (из списка)**: «Уведомление отправлено. Если пользователь ещё
  не писал боту — попросите его нажать `/start`…»; пользователю —
  приглашение: «📨 Вам предоставлен доступ к боту! Нажмите `/start`…».
- **deny**: «Запрос отклонён. Доступ не выдан… увидит «🚫 Доступ запрещён».

## Ключи приглашений (важный питфолл)

`AccessManager` хранит пользователей по ключу `user_id`. Добавление по
username с `user_id=0` приводит к **перезаписи** предыдущих приглашений
(один ключ `0`). Решение:

```python
import zlib

def _invite_key(username: str) -> int:
    """Стабильный отрицательный ключ для приглашения по username.
    Реальные Telegram ID всегда положительные."""
    return -zlib.crc32(username.strip().lower().encode("utf-8"))
```

- Приглашение по username: `am.add_user(user_id=_invite_key(username), username=..., full_name=f"@{username}", added_by=...)`.
- Критерий «ожидает активации» в списке: `user_id <= 0`.
- JSON-сериализация работает с отрицательными ключами (`int(uid)` при
  загрузке, `str(uid)` при сохранении).

## Активация приглашённого при /start

В `cmd_start` перед access gate:

```python
async def _activate_invited_by_username(am, user_id: int, username: str | None) -> bool:
    if not username or am.is_admin(user_id) or am.is_allowed(user_id):
        return False
    for u in am.get_allowed_users():
        if u.get("user_id", 0) <= 0 and \
                (u.get("username") or "").lower() == username.lower():
            old_id = u["user_id"]
            am.add_user(user_id=user_id, username=username,
                        full_name=u.get("full_name") or f"@{username}",
                        added_by=u.get("added_by"))
            am.remove_user(old_id)
            return True
    return False
```

После активации `start_access_gate` покажет welcome (is_allowed(real_id) → True).

## Питфоллы

- **dict-записи**: `get_allowed_users()` / `get_pending_requests()` /
  `get_user()` возвращают `list[dict]` / `dict` — доступ по ключу
  (`u.get("user_id")`), НЕ по атрибуту (`AttributeError: 'dict' object
  has no attribute 'user_id'`).
- **find_by_username не существует** в AccessManager — поиск по username:
  `next((u for u in am.get_allowed_users() if (u.get("username") or "").lower() == name.lower()), None)`.
- **parse_mode**: у бота default parse_mode=Markdown — любой текст с
  бэктиками/`**` без явного `parse_mode=None` роняет отправку
  (`TelegramBadRequest: can't parse entities`). Все динамические ответы
  `/user` — с `parse_mode=None`.
- **pending-запросы**: `get_pending_requests()` включает и `denied` —
  фильтровать `status != "denied"` для секции «Ожидают одобрения».
- Ранний return «Список пуст» — только если нет ни users, ни waiting,
  иначе секция ожидания пропадёт.

## Тесты

Эталон: `hunttech_short_vavancy_bot/tests/test_load_panel.py`
(`TestUserExplain`, `TestSetupUser`, `TestAdminCommandsHiddenFromRegularUsers`)
и `tests/test_access.py`. Покрывают: секции списка, кнопки approve/deny,
уникальные ключи приглашений, активацию по username, разъяснения,
скрытие админ-команд из /help и меню у обычных пользователей.
