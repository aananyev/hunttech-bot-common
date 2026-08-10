"""Regression tests for document-type hints (recognition/text_hints.py).

Key case: a services contract (договор возмездного оказания услуг) contains
"расчетный счет" and "Заказчик" — the old unconditional `_looks_like_invoice`
hint misclassified such contracts as INVOICE (docs-bot bug 10.08.2026,
record d9ec24083bb8-1281).
"""
from __future__ import annotations

from hunttech_bot_common.recognition.text_hints import (
    _apply_text_hints,
    _infer_document_type,
    _looks_like_contract,
    _looks_like_invoice,
)

CONTRACT_TEXT = """\
Договор возмездного оказания услуг
ООО "ХАНТТЕК", в лице Ананьев Алексей Павлович («Заказчик»), и ИВАНОВ ПАВЕЛ
ВЛАДИСЛАВОВИЧ, являющийся самозанятым («Исполнитель»), заключили настоящий
договор возмездного оказания услуг через платформу Qugo.
3.2. ...денежные средства, ранее перечисленные Заказчиком на расчетный счет
Компании.
4. Заверения об обстоятельствах
Документ подписан сторонами электронной подписью на платформе Qugo
Заказчик: ХАНТТЕК ИНН: 6455073518
Исполнитель: ИВАНОВ ПАВЕЛ ВЛАДИСЛАВОВИЧ ИНН: 781436079000
"""

INVOICE_TEXT = """\
Счет на оплату № 45 от 12.05.2026
Поставщик: ООО "Ромашка" ИНН 7701234567
Покупатель: ООО "ХАНТТЕК"
Расчетный счет: 40702810...
Банк: Сбербанк
Всего к оплате: 15 000,00
"""


def _base(data: dict | None = None) -> dict:
    base = {
        "document_type": "",
        "flow_type": "PRIMARY",
        "document_number": None,
        "document_date": None,
        "counterparty_name": None,
        "counterparty_inn": None,
        "amount": None,
        "currency": None,
        "expense_category": None,
        "receipt_organization": None,
        "confidence": 0.5,
        "needs_manual_review": True,
        "summary": "",
    }
    base.update(data or {})
    return base


def test_contract_with_bank_details_is_not_invoice() -> None:
    assert _looks_like_contract(CONTRACT_TEXT.lower()) is True
    assert _looks_like_invoice(CONTRACT_TEXT.lower()) is False


def test_contract_survives_hints_when_llm_said_invoice() -> None:
    # LLM вернул INVOICE (старая инструкция могла ввести в заблуждение) —
    # текст-хинты обязаны вернуть CONTRACT по заголовку.
    out = _apply_text_hints(_base({"document_type": "INVOICE"}), CONTRACT_TEXT)
    assert out["document_type"] == "CONTRACT"


def test_contract_survives_hints_when_llm_empty() -> None:
    out = _apply_text_hints(_base({"document_type": ""}), CONTRACT_TEXT)
    assert out["document_type"] == "CONTRACT"


def test_invoice_still_detected() -> None:
    assert _looks_like_invoice(INVOICE_TEXT.lower()) is True
    out = _apply_text_hints(_base({"document_type": ""}), INVOICE_TEXT)
    assert out["document_type"] == "INVOICE"
    assert out["flow_type"] == "PRIMARY"


def test_latin_filename_hint() -> None:
    assert _infer_document_type("dogovor-zakazchik-ispolnitel-jobofferid-9947629.pdf") == "CONTRACT"
    assert _infer_document_type("dogovor-2025-11-07.pdf") == "CONTRACT"
    assert _infer_document_type("contract-2026.pdf") == "CONTRACT"


def test_act_not_overridden_by_contract_mention() -> None:
    # Договор может упоминать «акт выполненных работ» — тип остаётся CONTRACT.
    text = CONTRACT_TEXT + "\nПриемка оформляется актом выполненных работ."
    out = _apply_text_hints(_base({"document_type": ""}), text)
    assert out["document_type"] == "CONTRACT"


REPORT_TEXT = """\
ОТЧЁТ № 2026/07
об оказанных услугах по поиску и первичному отбору кандидатов
г. Саратов Дата: «31» июля 2026 г.
1. Основание
Настоящий отчёт составлен в рамках Договора возмездного оказания услуг № 161-У от
24.06.2022 и Дополнительного соглашения № 2026-1 от 01.01.2026 между ООО «ХантТек» и
ИП Либерман Екатериной Сергеевной.
2. Период оказания услуг
Услуги оказывались в период с 01 июля 2026 года по 31 июля 2026 года.
3. Содержание оказанных услуг
Исполнителем выполнены работы по анализу рынка труда, поиску кандидатов, проведению
первичного отбора, организации собеседований.
"""


def test_report_referencing_contract_is_act_not_contract() -> None:
    # Отчёт ссылается на договор-основание («в рамках Договора №...») —
    # тип обязан быть ACT, а не CONTRACT (кейс Либермана 10.08.2026).
    assert _looks_like_contract(REPORT_TEXT.lower()) is False
    for llm_type in ("CONTRACT", "ACT", "UNKNOWN", ""):
        out = _apply_text_hints(_base({"document_type": llm_type}), REPORT_TEXT)
        assert out["document_type"] == "ACT", f"LLM={llm_type!r} → {out['document_type']}"


def test_report_filename_hint() -> None:
    assert _infer_document_type("2026-07-31 Отчет за июль ИП Либерман.pdf") == "ACT"
    assert _infer_document_type("otchet-2026-07.pdf") == "ACT"
    # Упоминание договора в тексте отчёта не должно дать CONTRACT
    hint = "2026-07-31 Отчет за июль ИП Либерман.pdf  ОТЧЁТ № 2026/07 ... в рамках Договора возмездного оказания услуг № 161-У"
    assert _infer_document_type(hint) == "ACT"


def test_act_still_detected() -> None:
    act_text = "Акт выполненных работ № 12 от 01.06.2026\nЗаказчик: ООО ХАНТТЕК\nИсполнитель: ИП Иванов"
    out = _apply_text_hints(_base({"document_type": ""}), act_text)
    assert out["document_type"] == "ACT"
