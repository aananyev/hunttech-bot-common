"""Regression tests for PDF text-layer routing (recognition/engine.py).

Key case (17.08.2026, record 98edfabb0660-2265): a receipt PDF from
check.yandex.ru has a "thin" text layer — only "Чек https://check.yandex.ru/?fn=..."
and the browser print footer "1 of 1 8/17/2026" (94 chars) — while the actual
receipt (seller, amount) is an image inside the PDF. The engine treated the
non-empty junk as a valid text layer, skipped OCR, and the LLM had nothing to
recognize. Fix: PDF text shorter than _PDF_TEXT_MIN_CHARS now falls back to
OCR of the rendered first page, combined with the extracted layer.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hunttech_bot_common.recognition.engine import (
    _PDF_TEXT_MIN_CHARS,
    _combine_pdf_texts,
    recognize_document,
)

THIN_LAYER_TEXT = (
    "Чекhttps://check.yandex.ru/?fn=7380440801182802&fpd=4228964757&n...\n"
    "1 of 18/17/2026, 12:12 PM"
)
NORMAL_TEXT = "ООО «Ромашка»\nИНН 7701234567\nСчет № 45 от 12.05.2026\nВсего к оплате: 15 000,00 руб.\n" * 10


class _FakeLlm:
    def __init__(self, parsed: dict):
        self._parsed = parsed

    def complete_structured(self, **kwargs):
        class _Result:
            def __init__(self, parsed):
                self.parsed = parsed
                self.text = ""
                self.provider = "fake"
                self.model = "fake"

        return _Result(self._parsed)


class _FakeSettings:
    yandex_vision_enabled = False
    ocr_space_enabled = False
    yandex_ocr_model = "page"


def _fake_pdf(tmp_path) -> Path:
    p = tmp_path / "check.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def test_thin_text_layer_routes_to_pdf_mixed(tmp_path):
    """PDF c «тонким» текстовым слоем (< порога) уходит в OCR-ветку."""
    path = _fake_pdf(tmp_path)
    with patch(
        "hunttech_bot_common.recognition.engine._extract_text",
        return_value=THIN_LAYER_TEXT,
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_pdf_mixed",
        return_value="MIXED",
    ) as mixed, patch(
        "hunttech_bot_common.recognition.engine._recognize_pdf_scan",
        side_effect=AssertionError("scan-ветка не должна вызываться"),
    ) as scan, patch(
        "hunttech_bot_common.recognition.engine._recognize_text_document",
        side_effect=AssertionError("text-ветка не должна вызываться напрямую"),
    ):
        result = recognize_document(None, path)
    assert result == "MIXED"
    mixed.assert_called_once()
    scan.assert_not_called()


def test_empty_text_routes_to_pdf_scan(tmp_path):
    """PDF без текстового слоя по-прежнему идёт в _recognize_pdf_scan."""
    path = _fake_pdf(tmp_path)
    with patch(
        "hunttech_bot_common.recognition.engine._extract_text",
        return_value="",
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_pdf_mixed",
        side_effect=AssertionError("mixed-ветка не должна вызываться"),
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_pdf_scan",
        return_value="SCAN",
    ) as scan:
        result = recognize_document(None, path)
    assert result == "SCAN"
    scan.assert_called_once()


def test_normal_text_skips_ocr(tmp_path):
    """PDF с нормальным текстовым слоем (>= порога) OCR не требует."""
    assert len(NORMAL_TEXT) >= _PDF_TEXT_MIN_CHARS
    path = _fake_pdf(tmp_path)
    with patch(
        "hunttech_bot_common.recognition.engine._extract_text",
        return_value=NORMAL_TEXT,
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_pdf_mixed",
        side_effect=AssertionError("mixed-ветка не должна вызываться"),
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_text_document",
        return_value="TEXT",
    ) as text_doc:
        result = recognize_document(None, path)
    assert result == "TEXT"
    text_doc.assert_called_once()


def test_combine_pdf_texts_order_and_empties():
    """OCR-текст идёт первым, пустые части отбрасываются."""
    combined = _combine_pdf_texts("  слой  ", "OCR текст")
    assert combined == "OCR текст\nслой"
    assert _combine_pdf_texts("", "") == ""
    assert _combine_pdf_texts("  ", "OCR") == "OCR"
    assert _combine_pdf_texts("слой", "   ") == "слой"


def test_pdf_mixed_combines_ocr_and_layer(tmp_path):
    """_recognize_pdf_mixed склеивает OCR и текстовый слой для LLM."""
    from hunttech_bot_common.recognition.engine import _recognize_pdf_mixed

    path = _fake_pdf(tmp_path)
    captured = {}

    class _FakeResult:
        parsed = {"document_type": "RECEIPT"}
        provider = "fake"
        model = "fake"
        raw_text = ""

    with patch(
        "hunttech_bot_common.recognition.engine._render_first_pdf_page",
        return_value=tmp_path / "page.jpg",
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_image_text",
        return_value=("OCR ПРОДАВЕЦ 600", "yandex-vision-ocr", "page"),
    ), patch(
        "hunttech_bot_common.recognition.engine._recognize_text_document",
        return_value=_FakeResult(),
    ) as text_doc:
        result = _recognize_pdf_mixed(
            _FakeLlm({"document_type": "RECEIPT"}),
            path,
            THIN_LAYER_TEXT,
            settings=_FakeSettings(),
        )
    assert result is not None
    call_kwargs = text_doc.call_args.kwargs
    assert "OCR ПРОДАВЕЦ 600" in call_kwargs["extracted_text"]
    assert "check.yandex.ru" in call_kwargs["extracted_text"]
    assert call_kwargs["source_provider"] == "yandex-vision-ocr"
    assert call_kwargs["source_model"] == "page"
