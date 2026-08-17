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


def test_report_referencing_contract_is_report_not_contract() -> None:
    # Отчёт ссылается на договор-основание («в рамках Договора №...») —
    # тип обязан быть REPORT, а не CONTRACT и не ACT (кейс Либермана 10.08.2026).
    assert _looks_like_contract(REPORT_TEXT.lower()) is False
    for llm_type in ("CONTRACT", "ACT", "REPORT", "UNKNOWN", ""):
        out = _apply_text_hints(_base({"document_type": llm_type}), REPORT_TEXT)
        assert out["document_type"] == "REPORT", f"LLM={llm_type!r} → {out['document_type']}"


def test_report_filename_hint() -> None:
    assert _infer_document_type("2026-07-31 Отчет за июль ИП Либерман.pdf") == "REPORT"
    assert _infer_document_type("otchet-2026-07.pdf") == "REPORT"
    # Упоминание договора в тексте отчёта не должно дать CONTRACT
    hint = "2026-07-31 Отчет за июль ИП Либерман.pdf  ОТЧЁТ № 2026/07 ... в рамках Договора возмездного оказания услуг № 161-У"
    assert _infer_document_type(hint) == "REPORT"


def test_act_still_detected() -> None:
    act_text = "Акт выполненных работ № 12 от 01.06.2026\nЗаказчик: ООО ХАНТТЕК\nИсполнитель: ИП Иванов"
    out = _apply_text_hints(_base({"document_type": ""}), act_text)
    assert out["document_type"] == "ACT"


def test_report_not_overridden_by_act_mention() -> None:
    # Отчёт может упоминать акт выполненных работ в тексте — тип остаётся REPORT.
    text = REPORT_TEXT + "\nПриемка оформляется актом выполненных работ."
    out = _apply_text_hints(_base({"document_type": ""}), text)
    assert out["document_type"] == "REPORT"


DECISION_TEXT = """\
Решение о привлечении страхователя к ответственности за совершение правонарушения в сфере законодательства об индивидуальном (персонифицированном) учете
Отделение Фонда пенсионного и социального страхования Российской Федерации по Саратовской области
№ 073S19260002053 от 04.08.2026
ООО «ХАНТТЕК» ИНН 6455073518
"""


def test_decision_from_title_not_act() -> None:
    """«Решение ... о привлечении к ответственности» — DECISION, а не ACT
    (docs-bot, кейс 10.08.2026: документ СФР определён как акт)."""
    out = _apply_text_hints(_base({"document_type": "ACT"}), DECISION_TEXT)
    assert out["document_type"] == "DECISION"


def test_decision_survives_hints_when_llm_was_act() -> None:
    for llm_type in ("ACT", "CONTRACT", "UNKNOWN", ""):
        out = _apply_text_hints(_base({"document_type": llm_type}), DECISION_TEXT)
        assert out["document_type"] == "DECISION", f"LLM={llm_type!r} → {out['document_type']}"


def test_decision_not_overridden_by_act_phrase() -> None:
    # Решение может упоминать акт/счёт в тексте — тип остаётся DECISION.
    text = DECISION_TEXT + "\nК акту камеральной проверки прилагается расчет."
    out = _apply_text_hints(_base({"document_type": ""}), text)
    assert out["document_type"] == "DECISION"


def test_decision_filename_hint() -> None:
    assert _infer_document_type("2026-08-04 Решение СФР 073S19260002053.pdf") == "DECISION"
    assert _infer_document_type("reshenie-073S19260002053.pdf") == "DECISION"


def test_act_still_detected_with_decision_word() -> None:
    # Обычный акт, в тексте которого есть слово «решение» — остаётся ACT.
    act_text = "Акт выполненных работ № 12 от 01.06.2026\nРешение о приемке работ подписано сторонами.\nЗаказчик: ООО ХАНТТЕК"
    out = _apply_text_hints(_base({"document_type": ""}), act_text)
    assert out["document_type"] == "ACT"


GPH_ACT_TEXT = """\
Акт № 2026-07 об оказании услуг
Заказчик: ООО «ХантТек» ИНН 6455073518
Исполнитель: Левина Юлия Сергеевна ИНН 644007676887
Стоимость услуг: 30 000,00 руб.
"""


def test_act_counterparty_never_own_company() -> None:
    """Акт ГПХ: LLM вернул «ООО «ХантТек»» (заказчик) — хинт заменяет на
    внешнюю сторону (Исполнитель — Левина). Кейс 11.08.2026: акт Левиной
    распознавался с контрагентом ХантТек, папка не находилась и карта
    отравлялась ключом 'ханттек' → папка ГПХ Левиной."""
    out = _apply_text_hints(
        _base({"document_type": "ACT", "counterparty_name": "ООО «ХантТек»"}),
        GPH_ACT_TEXT,
    )
    assert out["counterparty_name"] == "Левина Юлия Сергеевна"
    assert out["needs_manual_review"] is True


def test_act_counterparty_empty_picks_external_party() -> None:
    """Акт ГПХ с пустым контрагентом: выбирается Исполнитель (внешняя
    сторона), а не Заказчик-ХантТек."""
    out = _apply_text_hints(
        _base({"document_type": "ACT", "counterparty_name": None}),
        GPH_ACT_TEXT,
    )
    assert out["counterparty_name"] == "Левина Юлия Сергеевна"


def test_sales_upd_counterparty_is_client_not_own() -> None:
    """УПД от HRM клиенту: Поставщик — ХантТек (своя компания), контрагент —
    Покупатель (клиент)."""
    text = "УПД № 5 от 01.08.2026\nПоставщик: ООО «ХантТек» ИНН 6455073518\nПокупатель: ООО «Ромашка» ИНН 7701234567\n"
    out = _apply_text_hints(
        _base({"document_type": "UPD", "counterparty_name": "ООО «ХантТек»"}),
        text,
    )
    assert out["counterparty_name"] == "ООО «Ромашка»"


def test_own_company_alone_no_override() -> None:
    """Внешней стороны в тексте нет — контрагент остаётся как есть
    (карта папок защищена отдельно: запись по своей компании не пишется)."""
    text = "Акт № 1 от 01.01.2026\nОрганизация: ООО «ХантТек»\n"
    out = _apply_text_hints(
        _base({"document_type": "ACT", "counterparty_name": "ООО «ХантТек»"}),
        text,
    )
    assert out["counterparty_name"] == "ООО «ХантТек»"


RECONCILIATION_TEXT = """\
Акт сверки взаимных расчетов № 14 от 31.07.2026
ООО «ХАНТТЕК» ИНН 6455073518
Контрагент: ООО «Ромашка» ИНН 7701234567
Сальдо на начало периода: 0,00
Итоговое сальдо: 125 400,00
"""


def test_reconciliation_from_title_not_act() -> None:
    """«Акт сверки взаимных расчетов» — RECONCILIATION, а не ACT:
    акт сверки — отдельный тип документа (требование владельца 12.08.2026)."""
    out = _apply_text_hints(_base({"document_type": "ACT"}), RECONCILIATION_TEXT)
    assert out["document_type"] == "RECONCILIATION"


def test_reconciliation_survives_hints_when_llm_was_act() -> None:
    for llm_type in ("ACT", "OTHER", "UNKNOWN", ""):
        out = _apply_text_hints(_base({"document_type": llm_type}), RECONCILIATION_TEXT)
        assert out["document_type"] == "RECONCILIATION", f"LLM={llm_type!r} → {out['document_type']}"


def test_reconciliation_not_overridden_by_act_phrase() -> None:
    # «акт сверки» в тексте не должен уйти в ACT-хинт «акт выполненных работ».
    text = RECONCILIATION_TEXT + "\nОснование: акт оказанных услуг от 30.06.2026."
    out = _apply_text_hints(_base({"document_type": ""}), text)
    assert out["document_type"] == "RECONCILIATION"


def test_reconciliation_filename_hint() -> None:
    assert _infer_document_type("2026-07-31 Акт сверки ООО Ромашка.pdf") == "RECONCILIATION"
    assert _infer_document_type("Акт_сверки_взаимных_расчетов_14.pdf") == "RECONCILIATION"
    assert _infer_document_type("sverka-romashka-2026-07.pdf") == "RECONCILIATION"


def test_act_still_detected_without_sverka() -> None:
    # Обычный акт выполненных работ без слова «сверк» — остаётся ACT.
    act_text = "Акт выполненных работ № 12 от 01.06.2026\nЗаказчик: ООО ХАНТТЕК\nИсполнитель: ИП Иванов"
    out = _apply_text_hints(_base({"document_type": ""}), act_text)
    assert out["document_type"] == "ACT"


# ─── APPLICATION / NOTICE (заявление / уведомление) ───

NOTICE_TEXT = """\
Уведомление о расторжении договора возмездного оказания услуг № 14 от 01.08.2026
ООО «ХАНТТЕК» ИНН 6455073518
В соответствии с п. 5.2 Договора № 14 от 01.01.2026 уведомляем о расторжении.
"""

APPLICATION_TEXT = """\
Заявление на отпуск
ООО «ХАНТТЕК»
Прошу предоставить ежегодный оплачиваемый отпуск с 01.09.2026.
"""


def test_notice_from_title_not_contract() -> None:
    """«Уведомление о расторжении договора» — NOTICE, а не CONTRACT:
    уведомление — отдельный тип документа, даже если в тексте упомянут договор."""
    out = _apply_text_hints(_base({"document_type": "CONTRACT"}), NOTICE_TEXT)
    assert out["document_type"] == "NOTICE"
    assert out["flow_type"] == "PRIMARY"


def test_application_from_title() -> None:
    out = _apply_text_hints(_base({"document_type": ""}), APPLICATION_TEXT)
    assert out["document_type"] == "APPLICATION"
    assert out["flow_type"] == "PRIMARY"


def test_notice_survives_hints_when_llm_weak() -> None:
    for llm_type in ("OTHER", "UNKNOWN", "", "ACT"):
        out = _apply_text_hints(_base({"document_type": llm_type}), NOTICE_TEXT)
        assert out["document_type"] == "NOTICE", f"LLM={llm_type!r} → {out['document_type']}"


def test_contract_with_notice_clause_stays_contract() -> None:
    # Договор может содержать пункт про уведомления — тип остаётся CONTRACT.
    text = CONTRACT_TEXT + "\n5.2. Стороны направляют друг другу уведомления по e-mail."
    out = _apply_text_hints(_base({"document_type": "CONTRACT"}), text)
    assert out["document_type"] == "CONTRACT"


def test_application_and_notice_filename_hint() -> None:
    assert _infer_document_type("2026-08-01 Уведомление о расторжении договора.pdf") == "NOTICE"
    assert _infer_document_type("Уведомление_о_сокращении_Иванов.pdf") == "NOTICE"
    assert _infer_document_type("Заявление на отпуск Ананьев.pdf") == "APPLICATION"
    assert _infer_document_type("Заявление_о_приеме_на_работу.pdf") == "APPLICATION"


def test_contract_filename_still_contract_with_notice_marker() -> None:
    # Маркеры «уведомлени»/«заявлени» идут ДО «договор», но сам договор
    # в имени файла первым словом — CONTRACT (маркер «договор» по \b-границе
    # в начале head не сработает только если «уведомлени» встретился раньше).
    assert _infer_document_type("Договор_аренды_2026.pdf") == "CONTRACT"
