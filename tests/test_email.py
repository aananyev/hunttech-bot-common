"""Tests for hunttech_bot_common.email module.

Covers:
- Validation functions (email, hostname, port, password)
- Default config from env
- Format config display
- Save / load / clear persistence
- Connection test result dataclass
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from hunttech_bot_common.email import (
    ConnectionTestResult,
    clear_email_config,
    default_email_config,
    format_email_config,
    load_email_config,
    save_email_config,
    validate_email,
    validate_hostname,
    validate_port,
    validate_password,
)

# ═══════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════


class TestValidateEmail:
    def test_valid(self):
        assert validate_email("user@example.com") is None
        assert validate_email("alan@hunttech.ru") is None
        assert validate_email("i.russkova@key-success.ru") is None

    def test_missing_at(self):
        msg = validate_email("userexample.com")
        assert msg is not None
        assert "@" in msg

    def test_missing_domain(self):
        msg = validate_email("user@")
        assert msg is not None
        assert "домен" in msg

    def test_empty(self):
        assert validate_email("") is not None


class TestValidateHostname:
    def test_valid(self):
        assert validate_hostname("imap.yandex.ru") is None
        assert validate_hostname("smtp.yandex.ru") is None
        assert validate_hostname("mail.example.com") is None

    def test_too_short(self):
        msg = validate_hostname("x")
        assert msg is not None
        assert "домен" in msg

    def test_no_dot(self):
        msg = validate_hostname("localhost")
        assert msg is not None
        assert "домен" in msg or "хост" in msg.lower()

    def test_empty(self):
        assert validate_hostname("") is not None


class TestValidatePort:
    def test_valid(self):
        assert validate_port("993") is None
        assert validate_port("465") is None
        assert validate_port("143") is None
        assert validate_port(993) is None
        assert validate_port(25) is None

    def test_too_low(self):
        msg = validate_port("0")
        assert msg is not None
        assert "1 до 65535" in msg

    def test_too_high(self):
        msg = validate_port("65536")
        assert msg is not None
        assert "1 до 65535" in msg

    def test_not_a_number(self):
        msg = validate_port("abc")
        assert msg is not None
        assert "числ" in msg

    def test_empty(self):
        assert validate_port("") is not None


class TestValidatePassword:
    def test_valid(self):
        assert validate_password("abcd") is None
        assert validate_password("longenough") is None
        assert validate_password("x" * 100) is None

    def test_too_short(self):
        msg = validate_password("ab")
        assert msg is not None
        assert "4" in msg

    def test_empty(self):
        msg = validate_password("")
        assert msg is not None
        assert "4" in msg


# ═══════════════════════════════════════════════════════════════════
# Default config
# ═══════════════════════════════════════════════════════════════════


class TestDefaultConfig:
    def test_defaults_from_env(self):
        """Default config should read from env vars with fallbacks."""
        cfg = default_email_config()
        assert cfg["sender"] == os.getenv("MAIL_SENDER", "alan@hunttech.ru")
        assert cfg["smtp_host"] == os.getenv("MAIL_SMTP_HOST", "smtp.yandex.ru")
        assert cfg["smtp_port"] == int(os.getenv("MAIL_SMTP_PORT", "465"))
        assert cfg["imap_host"] == os.getenv("MAIL_IMAP_HOST", "imap.yandex.ru")
        assert cfg["imap_port"] == int(os.getenv("MAIL_IMAP_PORT", "993"))

    def test_defaults_no_env(self, monkeypatch: pytest.MonkeyPatch):
        """When env is not set, defaults should be Yandex."""
        monkeypatch.delenv("MAIL_SENDER", raising=False)
        monkeypatch.delenv("MAIL_SMTP_HOST", raising=False)
        cfg = default_email_config()
        assert cfg["sender"] == "alan@hunttech.ru"
        assert cfg["smtp_host"] == "smtp.yandex.ru"

    def test_password_default_empty(self):
        cfg = default_email_config()
        assert "password" in cfg


# ═══════════════════════════════════════════════════════════════════
# Format
# ═══════════════════════════════════════════════════════════════════


class TestFormatConfig:
    def test_contains_fields(self):
        cfg = {
            "sender": "test@test.ru",
            "smtp_host": "smtp.test.ru",
            "smtp_port": 465,
            "imap_host": "imap.test.ru",
            "imap_port": 993,
            "password": "secret123",
        }
        text = format_email_config(cfg)
        assert "test@test.ru" in text
        assert "smtp.test.ru" in text
        assert "465" in text
        assert "imap.test.ru" in text
        assert "993" in text

    def test_password_masked(self):
        cfg = {"password": "longpassword", "sender": "a@a.ru",
               "smtp_host": "s", "smtp_port": 465,
               "imap_host": "i", "imap_port": 993}
        text = format_email_config(cfg)
        assert "long" in text  # first 4 chars shown
        assert "****" in text  # rest masked

    def test_password_not_set(self):
        cfg = {"password": "", "sender": "a@a.ru",
               "smtp_host": "s", "smtp_port": 465,
               "imap_host": "i", "imap_port": 993}
        text = format_email_config(cfg)
        assert "не задан" in text


# ═══════════════════════════════════════════════════════════════════
# Persistence (save / load / clear)
# ═══════════════════════════════════════════════════════════════════


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path):
        config_path = tmp_path / "test_email.json"
        data = {"sender": "test@test.ru", "smtp_host": "smtp.test.ru",
                "smtp_port": 465, "imap_host": "imap.test.ru",
                "imap_port": 993, "password": "testpass"}
        save_email_config(data, config_path)
        assert config_path.exists()

        loaded = load_email_config(config_path)
        assert loaded["sender"] == "test@test.ru"
        assert loaded["password"] == "testpass"

    def test_clear(self, tmp_path: Path):
        config_path = tmp_path / "test_email.json"
        save_email_config({"sender": "x"}, config_path)
        assert config_path.exists()
        clear_email_config(config_path)
        assert not config_path.exists()

    def test_load_fallback_to_defaults(self, tmp_path: Path):
        """When file does not exist, should return defaults."""
        cfg = load_email_config(tmp_path / "nonexistent.json")
        assert cfg["sender"] == os.getenv("MAIL_SENDER", "alan@hunttech.ru")

    def test_load_corrupted_file(self, tmp_path: Path):
        config_path = tmp_path / "corrupted.json"
        config_path.write_text("not valid json", "utf-8")
        cfg = load_email_config(config_path)
        assert cfg["sender"] == os.getenv("MAIL_SENDER", "alan@hunttech.ru")


# ═══════════════════════════════════════════════════════════════════
# ConnectionTestResult
# ═══════════════════════════════════════════════════════════════════


class TestConnectionTestResult:
    def test_success_emoji(self):
        r = ConnectionTestResult(service="SMTP", success=True, message="ok", host="s", port=1)
        assert r.emoji == "✅"
        assert "✅" in r.short

    def test_failure_emoji(self):
        r = ConnectionTestResult(service="IMAP", success=False, message="fail", host="s", port=1)
        assert r.emoji == "❌"
        assert "❌" in r.short

    def test_short_format(self):
        r = ConnectionTestResult(service="SMTP", success=True, message="письмо отправлено", host="s", port=1)
        assert "SMTP" in r.short
        assert "письмо отправлено" in r.short
