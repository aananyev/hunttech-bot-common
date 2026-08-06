"""Tests for hunttech_bot_common.services.startup — changelog при старте.

Git-подход (эталон @hunttech_open_close_vacancy_bot): маркер startup_state.json
хранит SHA прошлого запуска; первый запуск → «Последние изменения бота»,
SHA изменился → «Изменения с прошлого запуска», тот же SHA → тишина.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hunttech_bot_common.services.startup import (
    build_startup_changelog,
    format_startup_changelog,
    git_recent_subjects,
    git_sha,
    git_subjects_since,
    load_startup_marker,
    save_startup_marker,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Временный git-репозиторий с 2 коммитами."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "file.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "Первый коммит"], check=True)
    (tmp_path / "file.txt").write_text("two", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "Второй коммит"], check=True)
    return tmp_path


class TestGitHelpers:
    def test_git_sha_returns_head(self, git_repo: Path) -> None:
        head = git_sha(git_repo)
        assert head and len(head) == 40

    def test_git_sha_none_for_bad_dir(self, tmp_path: Path) -> None:
        assert git_sha(tmp_path / "nope") is None

    def test_subjects_since(self, git_repo: Path) -> None:
        head = git_sha(git_repo)
        prev = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD~1"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert git_subjects_since(prev, git_repo) == ["Второй коммит"]

    def test_recent_subjects(self, git_repo: Path) -> None:
        items = git_recent_subjects(git_repo, max_items=8)
        assert items == ["Второй коммит", "Первый коммит"]


class TestMarker:
    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_startup_marker(tmp_path / "no.json") is None

    def test_save_then_load(self, tmp_path: Path) -> None:
        state = tmp_path / "startup_state.json"
        save_startup_marker(state, "abc123")
        assert load_startup_marker(state) == "abc123"
        # атомарность: tmp-файла не осталось
        assert not (tmp_path / "startup_state.tmp").exists()

    def test_load_corrupted_returns_none(self, tmp_path: Path) -> None:
        state = tmp_path / "startup_state.json"
        state.write_text("{broken", encoding="utf-8")
        assert load_startup_marker(state) is None


class TestBuildChangelog:
    def test_first_run_shows_recent(self, git_repo: Path, tmp_path: Path) -> None:
        result = build_startup_changelog(git_repo, tmp_path / "startup_state.json")
        assert result is not None
        assert result["header"] == "📦 Последние изменения бота:"
        assert result["items"] == ["Второй коммит", "Первый коммит"]

    def test_same_sha_silent(self, git_repo: Path, tmp_path: Path) -> None:
        state = tmp_path / "startup_state.json"
        head = git_sha(git_repo)
        assert head
        save_startup_marker(state, head)
        assert build_startup_changelog(git_repo, state) is None

    def test_new_commits_shown(self, git_repo: Path, tmp_path: Path) -> None:
        state = tmp_path / "startup_state.json"
        head = git_sha(git_repo)
        assert head
        save_startup_marker(state, head)
        # новый коммит
        (git_repo / "file.txt").write_text("three", encoding="utf-8")
        subprocess.run(["git", "-C", str(git_repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-q", "-m", "Третий коммит"], check=True)
        result = build_startup_changelog(git_repo, state)
        assert result is not None
        assert result["header"] == "📦 Изменения с прошлого запуска:"
        assert result["items"] == ["Третий коммит"]

    def test_unknown_sha_rebase_silent(self, git_repo: Path, tmp_path: Path) -> None:
        state = tmp_path / "startup_state.json"
        save_startup_marker(state, "0" * 40)  # не предок HEAD
        assert build_startup_changelog(git_repo, state) is None

    def test_no_git_returns_none(self, tmp_path: Path) -> None:
        assert build_startup_changelog(tmp_path / "no-repo", tmp_path / "state.json") is None


class TestFormat:
    def test_basic(self) -> None:
        text = format_startup_changelog("📦 Изменения с прошлого запуска:", ["A", "B"])
        assert text == "📦 Изменения с прошлого запуска:\n• A\n• B"

    def test_truncation(self) -> None:
        items = [f"коммит {i}" for i in range(12)]
        text = format_startup_changelog("H:", items, max_items=10)
        assert "• коммит 0" in text and "• коммит 9" in text
        assert "коммит 10" not in text  # усечено до 10 пунктов
        assert "… и ещё несколько коммитов" in text


class TestSend:
    def test_send_and_save_marker(self, git_repo: Path, tmp_path: Path) -> None:
        import asyncio

        from hunttech_bot_common.services.startup import send_startup_changelog

        sent: list[tuple] = []

        class FakeBot:
            async def send_message(self, chat_id, text, parse_mode=None):
                sent.append((chat_id, text, parse_mode))

        state = tmp_path / "startup_state.json"
        ok = asyncio.run(send_startup_changelog(FakeBot(), 123, git_repo, state))
        assert ok is True
        assert sent[0][0] == 123
        assert sent[0][2] is None  # plain text
        assert "📦 Последние изменения бота:" in sent[0][1]
        # маркер сохранён → повторный запуск молчит
        ok2 = asyncio.run(send_startup_changelog(FakeBot(), 123, git_repo, state))
        assert ok2 is False
        assert len(sent) == 1
