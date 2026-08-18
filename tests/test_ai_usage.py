"""Tests for hunttech_bot_common.ai.usage — учёт обращений к нейросети."""

from __future__ import annotations

from pathlib import Path

import pytest

from hunttech_bot_common.ai import (
    AIResponse,
    AIClient,
    UsageRecord,
    UsageTracker,
    estimate_cost,
    format_usage_report,
    usage_period_from_args,
)
from hunttech_bot_common.exceptions import AIAuthenticationError


# ── estimate_cost ───────────────────────────────────────────────────


def test_cost_deepseek_chat():
    # deepseek-chat: $0.27 / $1.10 за 1M → 1M вход + 1M выход = $1.37
    assert estimate_cost("deepseek-chat", 1_000_000, 1_000_000) == pytest.approx(1.37, abs=1e-9)
    assert estimate_cost("deepseek-v4-flash", 1_000_000, 1_000_000) == pytest.approx(1.37, abs=1e-9)


def test_cost_gpt4o_mini_not_matched_by_gpt4o():
    # «gpt-4o-mini» не должен попасть под «gpt-4o» ($2.50/$10)
    c_mini = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    c_4o = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
    assert c_mini == pytest.approx(0.75, abs=1e-9)  # 0.15 + 0.60
    assert c_4o == pytest.approx(12.50, abs=1e-9)  # 2.50 + 10.00


def test_cost_unknown_model_zero():
    assert estimate_cost("weird-model-42", 500, 300) == 0.0
    assert estimate_cost(None, 500, 300) == 0.0


def test_cost_partial_tokens():
    assert estimate_cost("deepseek-chat", 1_000, 0) == pytest.approx(0.00027, abs=1e-9)


# ── UsageTracker: запись / чтение / периоды ─────────────────────────


@pytest.fixture
def tracker(tmp_path: Path) -> UsageTracker:
    return UsageTracker(path=tmp_path / "ai_usage.json")


def _rec(**over) -> UsageRecord:
    base = dict(
        bot_name="recruiting", user_id=272980897, username="owner",
        provider="deepseek", model="deepseek-chat", task="detect_intent",
        status="ok", prompt_tokens=100, completion_tokens=50,
        total_tokens=150, duration_ms=1234.0,
        cost_usd=estimate_cost("deepseek-chat", 100, 50),
        source="админ (.env)",
    )
    base.update(over)
    return UsageRecord(**base)


def test_append_and_read_back(tracker: UsageTracker):
    tracker.append(_rec())
    rows = tracker.records("all")
    assert len(rows) == 1
    assert rows[0]["model"] == "deepseek-chat"
    assert rows[0]["task"] == "detect_intent"
    assert rows[0]["user_id"] == 272980897


def test_persists_between_instances(tmp_path: Path):
    p = tmp_path / "ai_usage.json"
    UsageTracker(path=p).append(_rec())
    rows = UsageTracker(path=p).records("all")
    assert len(rows) == 1


def test_period_filter(tracker: UsageTracker):
    from datetime import datetime, timedelta, timezone

    old = _rec(created_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat())
    fresh = _rec()
    tracker.append(old)
    tracker.append(fresh)
    assert len(tracker.records("day")) == 1
    assert len(tracker.records("week")) == 1
    assert len(tracker.records("month")) == 2
    assert len(tracker.records("all")) == 2
    assert len(tracker.records("3")) == 1


def test_max_records_trim(tmp_path: Path):
    tracker = UsageTracker(path=tmp_path / "ai_usage.json", max_records=3)
    for i in range(5):
        tracker.append(_rec(user_id=i))
    rows = tracker.records("all")
    assert len(rows) == 3
    assert rows[-1]["user_id"] == 4  # последние записи сохраняются


def test_corrupt_file_resilience(tmp_path: Path):
    p = tmp_path / "ai_usage.json"
    p.write_text("{not json", encoding="utf-8")
    tracker = UsageTracker(path=p)
    tracker.append(_rec())
    rows = tracker.records("all")
    assert len(rows) == 1  # битый файл не роняет запись


# ── summarize: разрезы ──────────────────────────────────────────────


def test_summarize_slices(tracker: UsageTracker):
    tracker.append(_rec(task="detect_intent", model="deepseek-chat"))
    tracker.append(_rec(task="detect_intent", model="deepseek-chat"))
    tracker.append(_rec(task="build_vacancy_description", model="gpt-4o-mini",
                        user_id=999, username="recruiter"))
    tracker.append(_rec(status="error", task="detect_intent"))

    s = tracker.summarize("all")
    t = s["totals"]
    assert t["requests"] == 4
    assert t["ok_requests"] == 3
    assert t["error_requests"] == 1
    assert t["total_tokens"] == 150 * 4

    models = dict(s["by_model"])
    assert models["deepseek-chat"]["requests"] == 3
    assert models["gpt-4o-mini"]["requests"] == 1

    users = dict(s["by_user"])
    assert "@owner (id 272980897)" in users
    assert users["@recruiter (id 999)"]["requests"] == 1

    tasks = dict(s["by_task"])
    assert tasks["detect_intent"]["requests"] == 3
    assert tasks["build_vacancy_description"]["requests"] == 1

    providers = dict(s["by_provider"])
    assert providers["deepseek"]["requests"] == 4  # 3 ok + 1 error

    days = dict(s["by_day"])
    assert len(days) == 1  # все записи — сегодня


def test_summarize_empty(tracker: UsageTracker):
    s = tracker.summarize("day")
    assert s["totals"]["requests"] == 0
    assert s["totals"]["cost_usd"] == 0.0
    assert s["by_model"] == []


# ── format_usage_report ─────────────────────────────────────────────


def test_report_sections(tracker: UsageTracker):
    tracker.append(_rec())
    text = format_usage_report(tracker, period="all", bot_name="Recruiting")
    assert "💰 Расходы на нейросеть — Recruiting" in text
    assert "ИТОГО:" in text and "1 запрос" in text
    assert "По моделям:" in text
    assert "По пользователям:" in text
    assert "По задачам:" in text
    assert "По провайдерам:" in text
    assert "По дням:" in text
    assert "deepseek-chat" in text
    assert "@owner" in text
    assert "detect_intent" in text
    assert "за всё время" in text


def test_report_empty(tracker: UsageTracker):
    text = format_usage_report(tracker, period="day")
    assert "ИТОГО: 0 запросов" in text
    assert "Стоимость: $0.0000" in text


# ── usage_period_from_args ──────────────────────────────────────────


def test_period_args():
    assert usage_period_from_args(None) == "day"
    assert usage_period_from_args([]) == "day"
    assert usage_period_from_args(["week"]) == "week"
    assert usage_period_from_args(["month"]) == "month"
    assert usage_period_from_args(["all"]) == "all"
    assert usage_period_from_args(["30"]) == "30"
    assert usage_period_from_args(["bogus"]) == "day"
    assert usage_period_from_args(["bogus", "week"]) == "week"  # первый валидный


# ── AIClient + tracker: автоматическая запись ──────────────────────


class _FakeTransport:
    """Подмена _do_complete: без сети."""

    def __init__(self, response=None, error=None):
        self.response = response or AIResponse(
            content="ok", duration_ms=5.0,
            usage={"prompt_tokens": 100, "completion_tokens": 50,
                   "total_tokens": 150},
        )
        self.error = error
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_complete_tracks_ok(tmp_path: Path):
    tracker = UsageTracker(path=tmp_path / "ai_usage.json")
    client = AIClient(
        endpoint="https://x/v1/chat/completions", api_key="k", model="deepseek-chat",
        user_id=42, username="u", bot_name="recruiting", usage_tracker=tracker,
        ai_source="личные",
    )
    client._do_complete = _FakeTransport()
    resp = await client.complete("sys", "usr", task="detect_intent")
    assert resp.content == "ok"
    rows = tracker.records("all")
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == "ok"
    assert r["task"] == "detect_intent"
    assert r["model"] == "deepseek-chat"
    assert r["bot_name"] == "recruiting"
    assert r["user_id"] == 42
    assert r["prompt_tokens"] == 100
    assert r["completion_tokens"] == 50
    assert r["total_tokens"] == 150
    assert r["cost_usd"] == pytest.approx(estimate_cost("deepseek-chat", 100, 50))


@pytest.mark.asyncio
async def test_complete_tracks_error(tmp_path: Path):
    tracker = UsageTracker(path=tmp_path / "ai_usage.json")
    client = AIClient(
        endpoint="https://x/v1/chat/completions", api_key="k", model="deepseek-chat",
        usage_tracker=tracker,
    )
    client._do_complete = _FakeTransport(error=AIAuthenticationError("bad key"))
    with pytest.raises(AIAuthenticationError):
        await client.complete("sys", "usr", task="detect_intent")
    rows = tracker.records("all")
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["task"] == "detect_intent"
    assert rows[0]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_complete_retries_then_tracks_error_once(tmp_path: Path):
    from hunttech_bot_common.exceptions import AIConnectionError

    tracker = UsageTracker(path=tmp_path / "ai_usage.json")
    client = AIClient(
        endpoint="https://x/v1/chat/completions", api_key="k", model="deepseek-chat",
        usage_tracker=tracker,
    )
    transport = _FakeTransport(error=AIConnectionError("boom"))
    client._do_complete = transport
    with pytest.raises(AIConnectionError):
        await client.complete("sys", "usr", task="detect_intent")
    # 3 попытки (ретраи), но в реестр — одна запись (финальная ошибка)
    assert transport.calls == 3
    rows = tracker.records("all")
    assert len(rows) == 1
    assert rows[0]["status"] == "error"


@pytest.mark.asyncio
async def test_no_tracker_no_crash(tmp_path: Path):
    client = AIClient(endpoint="https://x/v1/chat/completions", api_key="k",
                      model="deepseek-chat")
    client._do_complete = _FakeTransport()
    resp = await client.complete("sys", "usr", task="detect_intent")
    assert resp.content == "ok"
