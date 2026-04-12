"""
Pasport / ID rasmdan MRZ va maydonlar.

1) PassportEye — MRZ topish va tahlil (tavsiya etiladi; Tesseract tizimda bo‘lishi kerak).
2) Zaxira: to‘g‘ridan-to‘g‘ri Tesseract + sodda MRZ / heuristika.

Tashqi AI API ishlatilmaydi.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import re
import shutil
from typing import Any

from PIL import Image, ImageFilter, ImageOps

_MAX_IMAGE_CHARS = 10_500_000
_MAX_BINARY = 12 * 1024 * 1024

_NOISE_LABELS = re.compile(
    r"PASSPORT|PASPORT|RESPUBLIC|REPUBLIC|UZBEKISTAN|O[‘']ZBEKISTON|"
    r"SURNAME|GIVEN|ISM|FAMILIYA|SHAXSIY|TURI|TYPE|SEX|JSHSH|PINFL|"
    r"DATE|BIRTH|EXPIR|VALID|AUTHORITY|MINISTRY",
    re.I,
)


def _decode_data_url_bytes(data_url: str) -> tuple[bytes | None, str | None]:
    raw = (data_url or "").strip()
    if not raw.startswith("data:image/") or ";base64," not in raw:
        return None, "Rasm data:image/...;base64,... bo‘lishi kerak"
    if len(raw) > _MAX_IMAGE_CHARS:
        return None, "Rasm juda katta"
    try:
        b64 = raw.split(",", 1)[1]
        binary = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error, IndexError):
        return None, "Base64 dekodlashda xato"
    if len(binary) > _MAX_BINARY:
        return None, "Rasm fayli 12 MB dan oshmasin"
    return binary, None


def _decode_data_url_image(data_url: str) -> tuple[Image.Image | None, str | None]:
    binary, err = _decode_data_url_bytes(data_url)
    if err or binary is None:
        return None, err
    try:
        return Image.open(io.BytesIO(binary)).convert("RGB"), None
    except Exception as e:
        return None, f"Rasm ochilmadi: {e}"


def _try_passporteye(binary: bytes) -> dict[str, Any] | None:
    """
    PassportEye `read_mrz` — MRZ aniqlansa maydonlarni qaytaradi.
    MRZ yo‘q yoki xatolik bo‘lsa None.
    """
    try:
        from passporteye import read_mrz
    except ImportError:
        return None
    try:
        params = (os.environ.get("PASSPORTEYE_TESSERACT_PARAMS") or "").strip()
        mrz = read_mrz(io.BytesIO(binary), extra_cmdline_params=params)
    except Exception:
        return None
    if mrz is None or mrz.mrz_type is None:
        return None

    sn = str(getattr(mrz, "surname", "") or "").replace("<", " ").strip()
    nm = str(getattr(mrz, "names", "") or "").replace("<", " ").strip()
    full = f"{sn} {nm}".strip()[:200]
    doc = str(getattr(mrz, "number", "") or "").replace("<", "").strip()[:30]
    dob_raw = str(getattr(mrz, "date_of_birth", "") or "").strip()
    exp_raw = str(getattr(mrz, "expiration_date", "") or "").strip()
    dob = _yyMMDD_to_iso(dob_raw) if len(dob_raw) == 6 and dob_raw.isdigit() else ""
    exp = _yyMMDD_to_iso(exp_raw) if len(exp_raw) == 6 and exp_raw.isdigit() else ""

    raw_mrz = ""
    if isinstance(getattr(mrz, "aux", None), dict):
        raw_mrz = str(mrz.aux.get("raw_text") or mrz.aux.get("text") or "")

    return {
        "full_name": full,
        "document_number": doc,
        "date_of_birth": dob,
        "expiry_date": exp,
        "mrz_detected": True,
        "mrz_source": "passporteye",
        "mrz_type": mrz.mrz_type or "",
        "mrz_valid_score": int(getattr(mrz, "valid_score", 0) or 0),
        "mrz_valid": bool(getattr(mrz, "valid", False)),
        "country": str(getattr(mrz, "country", "") or ""),
        "nationality": str(getattr(mrz, "nationality", "") or ""),
        "sex": str(getattr(mrz, "sex", "") or ""),
        "document_type": str(getattr(mrz, "type", "") or ""),
        "mrz_raw_text": raw_mrz[:1200],
        "raw_text_preview": (raw_mrz.strip()[:800] if raw_mrz.strip() else ""),
    }


def _resolve_tesseract_binary() -> str | None:
    """
    Tesseract bajariladigan fayl: TESSERACT_CMD, macOS Homebrew yo‘llari, PATH.
    """
    env = (os.environ.get("TESSERACT_CMD") or "").strip()
    if env and os.path.isfile(env):
        return env
    for p in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        if os.path.isfile(p):
            return p
    w = shutil.which("tesseract")
    return w if w else None


def _prepare_for_ocr(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=2)
    w, h = g.size
    if max(w, h) < 900:
        scale = 900 / max(w, h)
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        g = g.resize((int(w * scale), int(h * scale)), resample)
    g = g.filter(ImageFilter.SHARPEN)
    return g


def _ocr_text(img: Image.Image) -> tuple[str, str | None]:
    try:
        import pytesseract
    except ImportError:
        return "", "pytesseract kutubxonasi o‘rnatilmagan (pip install pytesseract)"

    cmd = _resolve_tesseract_binary()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    langs = (os.environ.get("TESSERACT_LANGS") or "eng+rus").strip()
    try:
        text = pytesseract.image_to_string(
            img,
            lang=langs,
            config="--oem 3 --psm 6 -c preserve_interword_spaces=1",
        )
    except pytesseract.TesseractNotFoundError:
        return (
            "",
            "Tesseract topilmadi. macOS: brew install tesseract tesseract-lang. "
            "O‘rnatgach: TESSERACT_CMD=/opt/homebrew/bin/tesseract (yoki which tesseract)",
        )
    except Exception as e:
        return "", f"OCR xatosi: {e}"
    return text, None


def _clean_mrz_token(s: str) -> str:
    return re.sub(r"[^A-Z0-9<]", "", s.upper().replace(" ", ""))


def _find_mrz_pair(lines: list[str]) -> tuple[str, str] | None:
    cleaned = [_clean_mrz_token(L) for L in lines if L.strip()]
    for i in range(len(cleaned) - 1):
        a, b = cleaned[i], cleaned[i + 1]
        if len(a) >= 40 and len(b) >= 40 and a[0] in "PIAC" and "<" in a and "<" in b:
            return (a.ljust(44, "<")[:44], b.ljust(44, "<")[:44])
    blob = _clean_mrz_token("\n".join(lines))
    if len(blob) >= 80:
        for start in range(0, min(120, len(blob) - 79)):
            chunk = blob[start : start + 88]
            if len(chunk) < 80:
                continue
            a, b = chunk[:44], chunk[44:88]
            if a[0] in "PIAC" and a.count("<") >= 2 and b.count("<") >= 2:
                return (a.ljust(44, "<")[:44], b.ljust(44, "<")[:44])
    return None


def _parse_td3_names(line1: str) -> str:
    if len(line1) < 10:
        return ""
    name_field = line1[5:44] if len(line1) >= 44 else line1[5:]
    if "<<" not in name_field:
        name_field = name_field.replace("<", " ").strip()
        return re.sub(r"\s+", " ", name_field)[:200]
    surname, rest = name_field.split("<<", 1)
    surname = surname.replace("<", " ").strip()
    given = rest.replace("<", " ").strip()
    full = f"{surname} {given}".strip()
    return re.sub(r"\s+", " ", full)[:200]


def _parse_td3_line2(line2: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if len(line2) < 28:
        return out
    line2 = line2.ljust(44, "<")[:44]
    doc = line2[0:9].replace("<", "").strip()
    if doc and re.match(r"^[A-Z0-9]{5,}$", doc, re.I):
        out["document_number"] = doc[:30]
    dob = line2[13:19]
    if re.match(r"^\d{6}$", dob):
        out["date_of_birth"] = _yyMMDD_to_iso(dob)
    exp = line2[21:27]
    if re.match(r"^\d{6}$", exp):
        out["expiry_date"] = _yyMMDD_to_iso(exp)
    return out


def _yyMMDD_to_iso(yy_mm_dd: str) -> str:
    if len(yy_mm_dd) != 6 or not yy_mm_dd.isdigit():
        return ""
    yy, mm, dd = int(yy_mm_dd[0:2]), int(yy_mm_dd[2:4]), int(yy_mm_dd[4:6])
    year = 2000 + yy if yy < 50 else 1900 + yy
    try:
        return f"{year:04d}-{mm:02d}-{dd:02d}"
    except Exception:
        return ""


def _heuristic_full_name(ocr_text: str, skip_lines: set[str]) -> str:
    lines = [L.strip() for L in ocr_text.splitlines() if L.strip()]
    best = ""
    best_score = 0
    for L in lines:
        if L in skip_lines or _NOISE_LABELS.search(L):
            continue
        if len(L) < 6 or len(L) > 120:
            continue
        if re.search(r"\d{5,}", L):
            continue
        letters = len(re.findall(r"[^\W\d_]", L, flags=re.UNICODE))
        if letters < len(L) * 0.55:
            continue
        words = len(L.split())
        if words < 2:
            continue
        score = letters + words * 3
        if score > best_score:
            best_score = score
            best = L
    return re.sub(r"\s+", " ", best).strip()[:200]


def _dates_from_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"\b(\d{2})[.\-/](\d{2})[.\-/](\d{4})\b", text):
        d = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if "date_of_birth" not in out:
            out["date_of_birth"] = d
        else:
            out["expiry_date"] = d
            break
    return out


def _fallback_tesseract_pipeline(img: Image.Image) -> tuple[dict[str, Any], str | None]:
    prep = _prepare_for_ocr(img)
    text, err = _ocr_text(prep)
    if err:
        return {}, err

    raw_preview = text.strip()[:800]
    result: dict[str, Any] = {
        "full_name": "",
        "document_number": "",
        "date_of_birth": "",
        "expiry_date": "",
        "mrz_detected": False,
        "mrz_source": "tesseract_heuristic",
        "raw_text_preview": raw_preview,
    }

    skip: set[str] = set()
    pair = _find_mrz_pair(text.splitlines())
    if pair:
        l1, l2 = pair
        result["mrz_detected"] = True
        result["full_name"] = _parse_td3_names(l1)
        result.update({k: v for k, v in _parse_td3_line2(l2).items() if v})
        skip.add(l1.strip())
        skip.add(l2.strip())

    if not (result.get("full_name") or "").strip():
        guess = _heuristic_full_name(text, skip)
        if guess:
            result["full_name"] = guess

    if not result.get("date_of_birth") or not result.get("expiry_date"):
        for k, v in _dates_from_text(text).items():
            if v and not result.get(k):
                result[k] = v

    return result, None


def extract_passport_from_data_url(data_url: str) -> tuple[dict[str, Any], str | None]:
    """
    Qaytaradi: (maydonlar, xato).
    Avvalo PassportEye; MRZ bo‘lmasa yoki ism bo‘sh bo‘lsa — Tesseract zaxirasi.
    """
    binary, err = _decode_data_url_bytes(data_url)
    if err or binary is None:
        return {}, err or "Rasm yo‘q"

    pe = _try_passporteye(binary)
    if pe is not None:
        if not (pe.get("full_name") or "").strip():
            img, ierr = _decode_data_url_image(data_url)
            if not ierr and img is not None:
                fb, ferr = _fallback_tesseract_pipeline(img)
                if not ferr:
                    guess = (fb.get("full_name") or "").strip()
                    if guess:
                        pe["full_name"] = guess
                    if not (pe.get("raw_text_preview") or "").strip() and (fb.get("raw_text_preview") or "").strip():
                        pe["raw_text_preview"] = str(fb.get("raw_text_preview"))[:800]
                    pe["name_fallback"] = "tesseract_heuristic"
        return pe, None

    img, err = _decode_data_url_image(data_url)
    if err or img is None:
        return {}, err or "Rasm yo‘q"
    return _fallback_tesseract_pipeline(img)


def extract_full_name_from_id_data_url(data_url: str) -> tuple[str, str | None]:
    data, err = extract_passport_from_data_url(data_url)
    if err:
        return "", err
    return str(data.get("full_name") or "").strip()[:200], None
