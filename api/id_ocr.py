from __future__ import annotations

import json
import os
import re
from typing import Any

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _norm_text(v: Any, max_len: int) -> str:
    s = str(v or "").strip()
    return s[:max_len]


def _norm_date(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    if ISO_DATE.match(s):
        return s
    m = re.match(r"^(\d{2})[./-](\d{2})[./-](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def _json_from_text(raw: str) -> dict[str, Any] | None:
    t = (raw or "").strip()
    if not t:
        return None
    try:
        j = json.loads(t)
        return j if isinstance(j, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        return j if isinstance(j, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_document_fields_core(photo: str) -> tuple[dict[str, str] | None, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, ""
    src = str(photo or "").strip()
    if not src:
        return None, ""

    model = os.getenv("OPENAI_DOC_PARSER_MODEL", "gpt-5.4").strip() or "gpt-5.4"
    try:
        from openai import OpenAI  # lazy import: dependency yo'q bo'lsa oqim yiqilmasin
    except Exception:
        return None, ""
    client = OpenAI(api_key=api_key)
    try:
        resp = client.responses.create(
            model=model,
            temperature=0,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You extract structured fields from a single identity document image. "
                                "Return JSON only."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract fields and return strict JSON object with keys:\n"
                                "full_name, birth_date, expiry_date, citizenship, document_number, document_type.\n"
                                "Rules:\n"
                                "- document_type: passport | id_card | driver_license | other\n"
                                "- dates must be yyyy-mm-dd when possible, otherwise empty string\n"
                                "- unknown values as empty string\n"
                            ),
                        },
                        {"type": "input_image", "image_url": src, "detail": "low"},
                    ],
                },
            ],
        )
    except Exception:
        return None, ""

    raw_text = str(getattr(resp, "output_text", "") or "").strip()[:8000]
    payload = _json_from_text(raw_text)
    if not payload:
        return None, raw_text

    document_type = _norm_text(payload.get("document_type"), 40).lower()
    if document_type not in ("passport", "id_card", "driver_license", "other"):
        document_type = "other" if document_type else ""

    out = {
        "doc_full_name": _norm_text(payload.get("full_name"), 200),
        "doc_birth_date": _norm_date(payload.get("birth_date")),
        "doc_expiry_date": _norm_date(payload.get("expiry_date")),
        "doc_citizenship": _norm_text(payload.get("citizenship"), 64),
        "doc_number": _norm_text(payload.get("document_number"), 64),
        "doc_type": document_type,
    }
    if not any(out.values()):
        return None, raw_text
    return out, raw_text


def parse_document_fields_from_photo(photo: str) -> dict[str, str] | None:
    """
    OpenAI Vision orqali hujjat matnidan asosiy maydonlarni ajratadi.
    photo: data URL yoki https URL.
    """
    doc, _raw_text = _parse_document_fields_core(photo)
    return doc


def parse_document_fields_from_photo_with_raw(photo: str) -> tuple[dict[str, str] | None, str]:
    return _parse_document_fields_core(photo)
