"""Recognition engine — orchestrates document processing pipeline."""
from __future__ import annotations
import asyncio
import json
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from agent.plugin_llm import PluginLlmTextInput
except Exception:
    PluginLlmTextInput = None

from hunttech_bot_common.recognition.schemas import (
    DOCUMENT_SCHEMA, INSTRUCTIONS, RecognitionResult,
    _extract_json_object, _parse_json_fallback,
    _guess_mime, _is_pdf, _is_supported_image,
    _extract_text, _normalize_result,
)
from hunttech_bot_common.recognition.text_hints import _apply_text_hints
from hunttech_bot_common.recognition.ocr_space import recognize_text_with_ocr_space
from hunttech_bot_common.recognition.yandex_vision import recognize_text_with_yandex_vision

def recognize_document(
    llm: Any,
    path: Path,
    *,
    caption: str = "",
    original_name: str = "",
    settings: Any = None,
) -> RecognitionResult:
    settings = settings or load_settings()
    mime_type = _guess_mime(path)
    if _is_supported_image(mime_type):
        return _recognize_image_document(llm, path, mime_type, caption=caption, original_name=original_name, settings=settings)

    extracted_text = _extract_text(path, mime_type)
    if _is_pdf(mime_type, path) and not extracted_text.strip():
        return _recognize_pdf_scan(llm, path, caption=caption, original_name=original_name, settings=settings)

    return _recognize_text_document(
        llm,
        path,
        mime_type,
        extracted_text,
        caption=caption,
        original_name=original_name,
    )

def _recognize_text_document(
    llm: Any,
    path: Path,
    mime_type: str,
    extracted_text: str,
    *,
    caption: str = "",
    original_name: str = "",
    source_provider: str = "",
    source_model: str = "",
) -> RecognitionResult:
    if llm is None:
        raise RuntimeError("Hermes plugin LLM is unavailable")
    if PluginLlmTextInput is None:
        raise RuntimeError("Hermes plugin LLM input classes are unavailable")

    inputs: list[Any] = [
        PluginLlmTextInput(
            text=(
                f"Original file name: {original_name or path.name}\n"
                f"MIME type: {mime_type}\n"
                f"Telegram caption: {caption or ''}\n"
                f"Extracted document text:\n{extracted_text[:12000]}\n"
            )
        )
    ]

    result = llm.complete_structured(
        instructions=INSTRUCTIONS,
        input=inputs,
        json_schema=None,
        json_mode=False,
        schema_name="hunttech_accounting_document",
        temperature=0,
        timeout=90,
        purpose="hunttech_docs_recognition",
    )
    parsed = result.parsed if isinstance(result.parsed, dict) else _parse_json_fallback(result.text)
    parsed = _normalize_result(parsed, hint_text=f"{original_name} {caption} {extracted_text[:2000]}")
    parsed = _apply_text_hints(parsed, extracted_text)
    provider = result.provider
    model = result.model
    if source_provider:
        provider = f"{source_provider}+{provider}"
        model = f"{source_model}+{model}" if source_model else model
    return RecognitionResult(
        parsed=parsed,
        provider=provider,
        model=model,
        raw_text=result.text,
    )

def _recognize_image_document(
    llm: Any,
    path: Path,
    mime_type: str,
    *,
    caption: str = "",
    original_name: str = "",
    settings: Any,
) -> RecognitionResult:
    ocr_text, ocr_provider, ocr_model = _recognize_image_text(path, mime_type, settings)
    return _recognize_text_document(
        llm,
        path,
        mime_type,
        ocr_text,
        caption=caption,
        original_name=original_name,
        source_provider=ocr_provider,
        source_model=ocr_model,
    )

def _recognize_image_text(path: Path, mime_type: str, settings: Any) -> tuple[str, str, str]:
    yandex_error: Exception | None = None
    if getattr(settings, "yandex_vision_enabled", False):
        try:
            ocr = recognize_text_with_yandex_vision(path, mime_type, settings)
            return ocr.text, "yandex-vision-ocr", getattr(settings, "yandex_ocr_model", "page") or "page"
        except Exception as exc:
            yandex_error = exc
            if not getattr(settings, "ocr_space_enabled", False):
                raise

    if getattr(settings, "ocr_space_enabled", False):
        try:
            ocr = recognize_text_with_ocr_space(path, mime_type, settings)
            return ocr.text, "ocr-space", f"engine-{getattr(settings, 'ocr_space_engine', '2') or '2'}"
        except Exception as exc:
            if yandex_error is not None:
                raise RuntimeError(f"Yandex OCR failed: {yandex_error}; OCR.space failed: {exc}") from exc
            raise

    if yandex_error is not None:
        raise yandex_error
    raise RuntimeError("Не настроен OCR для фотографий: включите Yandex Vision OCR или OCR.space fallback.")

def _recognize_pdf_scan(
    llm: Any,
    path: Path,
    *,
    caption: str = "",
    original_name: str = "",
    settings: Any,
) -> RecognitionResult:
    with tempfile.TemporaryDirectory(prefix="hunttech-docs-pdf-") as temp_dir:
        rendered = _render_first_pdf_page(path, Path(temp_dir))
        return _recognize_image_document(
            llm,
            rendered,
            "image/jpeg",
            caption=caption,
            original_name=original_name or path.name,
            settings=settings,
        )

def _render_first_pdf_page(path: Path, temp_dir: Path) -> Path:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError(
            "PDF похож на скан без текстового слоя, но pdftoppm не найден. "
            "Нужно установить Poppler или отправить документ как фото."
        )
    output_stem = temp_dir / "page-1"
    completed = subprocess.run(
        [
            pdftoppm,
            "-singlefile",
            "-f",
            "1",
            "-l",
            "1",
            "-r",
            "220",
            "-jpeg",
            str(path),
            str(output_stem),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    rendered = output_stem.with_suffix(".jpg")
    if completed.returncode != 0 or not rendered.is_file():
        detail = (completed.stderr or completed.stdout or "unknown pdftoppm error").strip()
        raise RuntimeError(f"Не удалось подготовить PDF-скан для vision-распознавания: {detail}")
    return rendered

def _resolve_vision_backend() -> tuple[str, str]:
    try:
        from agent.auxiliary_client import resolve_vision_provider_client
    except Exception as exc:  # pragma: no cover - Hermes import path is checked at runtime.
        raise RuntimeError("Hermes vision routing is unavailable") from exc

    provider, client, model = resolve_vision_provider_client(provider="auto")
    if client is None:
        raise RuntimeError(
            "Для фотографий не настроена доступная Hermes vision-модель. "
            "Нужно включить auxiliary.vision или подключить vision-провайдер в Hermes."
        )
    return provider or "vision", model or "auto"

def _run_vision_analysis(path: Path, prompt: str) -> str:
    try:
        return asyncio.run(_run_vision_analysis_async(path, prompt))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" not in str(exc):
            raise
        raise RuntimeError("Image recognition must run outside an active event loop") from exc

async def _run_vision_analysis_async(path: Path, prompt: str) -> str:
    from tools.vision_tools import vision_analyze_tool

    payload = await vision_analyze_tool(str(path), prompt)
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Hermes vision returned non-JSON tool payload: {payload[:200]}") from exc
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or result.get("analysis") or "Hermes vision failed"))
    return str(result.get("analysis") or "")