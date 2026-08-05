"""Tests for hunttech_bot_common.services.rates — стандартный расчёт ставок.

Алгоритм /rates перенесён из hunttech_short_vavancy_bot (одобрен владельцем):
точное совпадение rate → ближайшая меньшая; часовая = зарплата ÷ 164,
округление вниз до 100 руб.; оформление ГПХ/ИП выбирает ставку.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hunttech_bot_common.services.rates import (
    OUTSTAFFING_RATES_TABLE,
    build_candidate_rates_report,
    calculate_candidate_rate,
    hourly_from_monthly,
    lookup_outstaffing_rate,
    pick_employment_rates,
)


# ═══════════════════════════════════════════════
# hourly_from_monthly — деление на 164 и округление вниз
# ═══════════════════════════════════════════════

class TestHourlyFromMonthly:
    def test_rounds_down_to_nearest_100(self) -> None:
        assert hourly_from_monthly(87900) == 500   # 535.9 → 500
        assert hourly_from_monthly(108600) == 600  # 662.2 → 600

    def test_never_rounds_up(self) -> None:
        assert hourly_from_monthly(91200) == 500   # 556.1 → 500, не 600
        assert hourly_from_monthly(190000) == 1100  # 1158.5 → 1100, не 1200

    def test_exact_division(self) -> None:
        assert hourly_from_monthly(164000) == 1000  # ровно 1000
        assert hourly_from_monthly(300000) == 1800  # 1829.2 → 1800


# ═══════════════════════════════════════════════
# pick_employment_rates — выбор ставок по оформлению
# ═══════════════════════════════════════════════

class TestPickEmploymentRates:
    def test_gph_uses_tk_salary(self) -> None:
        r = pick_employment_rates("ГПХ", 500, 600)
        assert r == {"want_tk": True, "want_ip": False, "rate_val": "500"}

    def test_ip_uses_ie_salary(self) -> None:
        r = pick_employment_rates("ИП", 500, 600)
        assert r == {"want_tk": False, "want_ip": True, "rate_val": "600"}

    def test_both_returns_both(self) -> None:
        r = pick_employment_rates("ГПХ или ИП", 500, 600)
        assert r == {"want_tk": True, "want_ip": True, "rate_val": "500 / 600"}

    def test_empty_empl_returns_both(self) -> None:
        r = pick_employment_rates("", 500, 600)
        assert r == {"want_tk": True, "want_ip": True, "rate_val": "500 / 600"}

    def test_unknown_empl_returns_both(self) -> None:
        r = pick_employment_rates("что-то", 500, 600)
        assert r == {"want_tk": True, "want_ip": True, "rate_val": "500 / 600"}

    def test_whitespace_empl_is_empty(self) -> None:
        r = pick_employment_rates("  ", 500, 600)
        assert r["want_tk"] is True and r["want_ip"] is True


# ═══════════════════════════════════════════════
# build_candidate_rates_report — формат «Вознаграждение»
# ═══════════════════════════════════════════════

class TestReport:
    def test_exact_match_report(self) -> None:
        report = build_candidate_rates_report(
            user_rate=2500, match_type="exact", db_rate=2500,
            hourly_tk=500, hourly_ip=600, empl="",
            want_tk=True, want_ip=True,
        )
        assert "✅ **Расчёт ставки кандидата**" in report
        assert "💰 Ставка заказчика: **2500** руб/час" in report
        assert "🔍 Найдено точное совпадение" in report
        assert "🤝 ГПХ — **500** руб./час на руки." in report
        assert "💼 ИП — **600** руб./час, налоги оплачиваются" in report

    def test_nearest_lower_report_mentions_db_rate(self) -> None:
        report = build_candidate_rates_report(
            user_rate=2700, match_type="nearest_lower", db_rate=2500,
            hourly_tk=500, hourly_ip=600, empl="ГПХ",
            want_tk=True, want_ip=False,
        )
        assert "взята ближайшая меньшая ставка (**2500** руб/час)" in report
        assert "📌 Оформление в вакансии: **ГПХ** — показана только эта ставка." in report
        assert "💼 ИП" not in report

    def test_single_employment_hides_other(self) -> None:
        report = build_candidate_rates_report(
            user_rate=2500, match_type="exact", db_rate=2500,
            hourly_tk=500, hourly_ip=600, empl="ИП",
            want_tk=False, want_ip=True,
        )
        assert "🤝 ГПХ" not in report
        assert "💼 ИП — **600**" in report


# ═══════════════════════════════════════════════
# lookup_outstaffing_rate — SQL-логика (мок conn)
# ═══════════════════════════════════════════════

class TestLookup:
    def _conn(self, rows_by_query: list[dict | None]) -> AsyncMock:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=rows_by_query)
        return conn

    def test_exact_match_first(self) -> None:
        import asyncio

        conn = self._conn([
            {"rate": 2500, "max_salary": 87900, "max_ie_salary": 108600},
        ])
        found = asyncio.run(lookup_outstaffing_rate(conn, 2500))
        assert found == {
            "rate": 2500, "max_salary": 87900, "max_ie_salary": 108600,
            "match_type": "exact",
        }
        # только один запрос — точный
        assert conn.fetchrow.call_count == 1
        assert "WHERE rate = $1 AND delete_ts IS NULL" in conn.fetchrow.call_args.args[0]

    def test_nearest_lower_fallback(self) -> None:
        conn = self._conn([None, {"rate": 2400, "max_salary": 85000, "max_ie_salary": 104000}])
        import asyncio

        found = asyncio.run(lookup_outstaffing_rate(conn, 2500))
        assert found["match_type"] == "nearest_lower"
        assert found["rate"] == 2400
        assert conn.fetchrow.call_count == 2
        assert "WHERE rate < $1 AND delete_ts IS NULL" in conn.fetchrow.call_args.args[0]
        assert "ORDER BY rate DESC" in conn.fetchrow.call_args.args[0]

    def test_not_found_returns_none(self) -> None:
        conn = self._conn([None, None])
        import asyncio

        assert asyncio.run(lookup_outstaffing_rate(conn, 2500)) is None

    def test_both_queries_filter_deleted_rows(self) -> None:
        """Оба запроса обязаны фильтровать soft-deleted строки."""
        import inspect
        import hunttech_bot_common.services.rates as rates_mod

        src = inspect.getsource(rates_mod)
        assert "WHERE rate = $1 AND delete_ts IS NULL" in src
        assert "WHERE rate < $1 AND delete_ts IS NULL" in src


# ═══════════════════════════════════════════════
# calculate_candidate_rate — высокоуровневый расчёт
# ═══════════════════════════════════════════════

class TestCalculate:
    def _db(self, conn: AsyncMock) -> AsyncMock:
        # DatabasePool.acquire() — НЕ корутина: обычный метод, возвращающий
        # контекстный менеджер (PoolAcquireContext).
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        db = AsyncMock()
        # acquire — ОБЫЧНЫЙ метод (asyncpg-стиль): MagicMock, не AsyncMock,
        # иначе вызов вернёт корутину вместо контекстного менеджера.
        db.acquire = MagicMock(return_value=cm)
        return db

    def test_full_flow_exact(self) -> None:
        import asyncio

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "rate": 2500, "max_salary": 87900, "max_ie_salary": 108600,
        })
        db = self._db(conn)
        result = asyncio.run(calculate_candidate_rate(db, 2500, empl="ГПХ"))
        assert "error" not in result
        assert result["match_type"] == "exact"
        assert result["db_rate"] == 2500
        assert result["salary_tk"] == 87900
        assert result["salary_ip"] == 108600
        assert result["hourly_tk"] == 500   # 87900/164 → 535.9 → 500
        assert result["hourly_ip"] == 600   # 108600/164 → 662.2 → 600
        assert result["want_tk"] is True and result["want_ip"] is False
        assert result["rate_val"] == "500"
        assert "500** руб./час на руки" in result["report"]

    def test_full_flow_nearest_lower_both(self) -> None:
        import asyncio

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, {
            "rate": 2400, "max_salary": 190000, "max_ie_salary": 220000,
        }])
        db = self._db(conn)
        result = asyncio.run(calculate_candidate_rate(db, 2500, empl=""))
        assert result["match_type"] == "nearest_lower"
        assert result["hourly_tk"] == 1100   # 190000/164 → 1158.5 → 1100
        assert result["hourly_ip"] == 1300   # 220000/164 → 1341.4 → 1300
        assert result["rate_val"] == "1100 / 1300"
        assert "взята ближайшая меньшая ставка (**2400** руб/час)" in result["report"]

    def test_no_db(self) -> None:
        import asyncio

        result = asyncio.run(calculate_candidate_rate(None, 2500))
        assert result == {"error": "no_db"}

    def test_not_found(self) -> None:
        import asyncio

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])
        db = self._db(conn)
        result = asyncio.run(calculate_candidate_rate(db, 2500))
        assert result == {"error": "not_found"}

    def test_db_error(self) -> None:
        import asyncio

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=RuntimeError("boom"))
        db = self._db(conn)
        result = asyncio.run(calculate_candidate_rate(db, 2500))
        assert result["error"] == "db_error"
        assert "boom" in result["detail"]
