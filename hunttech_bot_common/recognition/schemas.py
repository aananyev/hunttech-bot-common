"""Document recognition schemas and prompts for HuntTech bots."""
from __future__ import annotations
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "flow_type": {"type": "string", "enum": ["PRIMARY", "ADVANCE_REPORT", "UNKNOWN"]},
        "document_type": {
            "type": "string",
            "enum": ["CONTRACT", "ACT", "UPD", "INVOICE", "TASK", "RECEIPT", "OTHER", "UNKNOWN"],
        },
        "document_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "document_number": {"type": ["string", "null"]},
        "counterparty_name": {"type": ["string", "null"]},
        "counterparty_inn": {"type": ["string", "null"]},
        "amount": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
        "expense_category": {"type": ["string", "null"]},
        "receipt_organization": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "needs_manual_review": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": [
        "flow_type",
        "document_type",
        "document_date",
        "document_number",
        "counterparty_name",
        "counterparty_inn",
        "amount",
        "currency",
        "expense_category",
        "receipt_organization",
        "confidence",
        "needs_manual_review",
        "summary",
    ],
}

INSTRUCTIONS = """\
You recognize Russian accounting primary documents and advance-report receipts for HRM HuntTech.

Return only one JSON object. Do not wrap it in Markdown. Do not invent missing fields.

Rules:
- PRIMARY: contracts, acts, UPD, invoices (счет, счёт), tasks, appendices and other counterparty documents.
- ADVANCE_REPORT: cash-register receipts (кассовый чек), fuel, taxi, parking, communication, services and other expense confirmations.
- A "счёт на оплату" (payment invoice) is always PRIMARY, never ADVANCE_REPORT.
- If the text contains "Получатель" or "Банк" with bank details AND "Заказчик" or "Покупатель" — it is likely an invoice (PRIMARY).
- If at least one legal entity is visible in a PRIMARY document, counterparty_name must not be null.
- For acts with "Заказчик" and "Исполнитель", prefer "Заказчик" as the primary organization when HRM HuntTech's own side is unclear; keep needs_manual_review=true and mention both parties in summary.
- Dates must be ISO YYYY-MM-DD when confidently visible.
- Amount is numeric with dot separator.
- Currency defaults to RUB only when the document is clearly Russian/ruble-denominated.
- If the exact counterparty role is unclear but organizations are visible, fill counterparty_name with the best visible candidate and set needs_manual_review=true.
- For ADVANCE_REPORT receipts, receipt_organization is the seller, merchant, fiscal cash-register user, fuel station, service provider or visible legal entity from the receipt. Prefer it over a buyer/person name.
- If receipt organization is unclear on an ADVANCE_REPORT receipt, set receipt_organization to null and needs_manual_review=true.
- Be conservative: low confidence is better than a false confident answer.

JSON keys:
flow_type, document_type, document_date, document_number, counterparty_name,
counterparty_inn, amount, currency, expense_category, receipt_organization,
confidence, needs_manual_review, summary.
"""

@dataclass(frozen=True)
class RecognitionResult:
    parsed: dict[str, Any]
    provider: str
    model: str
    raw_text: str

def _guess_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _is_supported_image(mime_type: str) -> bool:
    return mime_type in {"image/jpeg", "image/png", "image/webp"}


def _is_pdf(mime_type: str, path: Path) -> bool:
    return mime_type == "application/pdf" or path.suffix.lower() == ".pdf"

def _normalize_result(data: dict[str, Any], *, hint_text: str = "") -> dict[str, Any]:
    normalized = dict(data)
    normalized["flow_type"] = _normalize_enum(
        normalized.get("flow_type"),
        {
            "primary": "PRIMARY",
            "advance_report": "ADVANCE_REPORT",
            "advance report": "ADVANCE_REPORT",
            "receipt": "ADVANCE_REPORT",
        },
        _infer_flow_type(hint_text),
    )
    normalized["document_type"] = _normalize_enum(
        normalized.get("document_type"),
        {
            "contract": "CONTRACT",
            "договор": "CONTRACT",
            "act": "ACT",
            "акт": "ACT",
            "upd": "UPD",
            "упд": "UPD",
            "invoice": "INVOICE",
            "счет": "INVOICE",
            "счёт": "INVOICE",
            "task": "TASK",
            "задание": "TASK",
            "receipt": "RECEIPT",
            "чек": "RECEIPT",
            "other": "OTHER",
        },
        _infer_document_type(hint_text),
    )
    normalized.setdefault("needs_manual_review", True)
    normalized["confidence"] = _normalize_confidence(normalized.get("confidence"))
    return normalized




def _parse_json_fallback(text: str) -> dict[str, Any]:
    candidate = _extract_json_object(text)
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {
            "flow_type": "UNKNOWN",
            "document_type": "UNKNOWN",
            "document_date": None,
            "document_number": None,
            "counterparty_name": None,
            "counterparty_inn": None,
            "amount": None,
            "currency": None,
            "expense_category": None,
            "receipt_organization": None,
            "confidence": 0,
            "needs_manual_review": True,
            "summary": "AI returned non-JSON text",
        }

def _extract_json_object(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        return cleaned[first:last + 1]
    return cleaned

def _extract_text(path: Path, mime_type: str) -> str:
    if mime_type != "application/pdf" and path.suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "") for page in reader.pages[:5]]
        return "\n".join(part for part in parts if part).strip()
    except Exception:
        return ""