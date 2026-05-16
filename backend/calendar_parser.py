"""Calendar event parsing utilities for proactive cooling scenarios."""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from io import StringIO
from typing import Any


REQUIRED_EVENT_FIELDS = {"name", "date"}
TEXT_EVENT_FIELDS = ["name", "date", "load", "temp", "desc", "cooling", "level"]
LOAD_IMPACT_MAP = {
    "low": 45.0,
    "medium": 72.0,
    "med": 72.0,
    "high": 88.0,
    "critical": 98.0,
    "kritik": 98.0,
}
ANKARA_MONTHLY_TEMP = {
    1: -1.0,
    2: 2.0,
    3: 7.0,
    4: 13.0,
    5: 18.0,
    6: 23.0,
    7: 27.0,
    8: 27.0,
    9: 22.0,
    10: 15.0,
    11: 8.0,
    12: 2.0,
}


def _first_present(row: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _to_float(value: Any, field_name: str) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} sayisal olmali.") from exc


def _load_to_float(value: Any) -> float:
    text = str(value).strip().lower()
    if text in LOAD_IMPACT_MAP:
        return LOAD_IMPACT_MAP[text]
    return _to_float(value, "load")


def _to_date(value: Any) -> date:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("date alani YYYY-MM-DD, DD.MM.YYYY veya DD/MM/YYYY formatinda olmali.")


def _event_level(load: float) -> str:
    if load >= 90:
        return "high"
    if load >= 75:
        return "med"
    return "low"


def _cooling_action(load: float, temp: float, category: str | None) -> str:
    if load >= 90:
        return "+15C Kritik Ek Sogutma Modu"
    if load >= 80:
        return "+9C Kritik Ek Sogutma Modu"
    if load >= 70:
        return "+7C Sogutma Rezervi"
    if category and "tatil" in category.lower():
        return "Dusuk trafik modu, enerji tasarrufu odakli calisma"
    if temp >= 25:
        return "+5C Sicak hava sogutma rezervi"
    return "Standart proaktif izleme"


def normalize_calendar_event(row: dict[str, Any], event_id: int) -> dict[str, Any]:
    """Normalize flexible CSV/JSON rows into frontend calendar events."""

    normalized = {
        "id": event_id,
        "name": _first_present(row, ("name", "event_name", "title", "olay_adi")),
        "date": _first_present(row, ("date", "timestamp", "event_date", "tarih")),
        "load": _first_present(
            row,
            (
                "load",
                "server_load",
                "server_workload_pct",
                "trafik_yuku",
                "expected_load_impact",
                "impact",
            ),
        ),
        "temp": _first_present(row, ("temp", "ambient_temp_c", "temperature", "sicaklik")),
        "category": _first_present(row, ("category", "kategori"), ""),
        "desc": _first_present(row, ("desc", "description", "aciklama"), ""),
        "cooling": _first_present(row, ("cooling", "cooling_action", "tedbir"), None),
        "level": _first_present(row, ("level", "severity"), None),
    }

    missing = [field for field in REQUIRED_EVENT_FIELDS if normalized[field] in (None, "")]
    if missing:
        raise ValueError(f"Eksik takvim alanlari: {', '.join(sorted(missing))}.")

    event_date = _to_date(normalized["date"])
    load = _load_to_float(normalized["load"] or "medium")
    temp = (
        _to_float(normalized["temp"], "temp")
        if normalized["temp"] not in (None, "")
        else ANKARA_MONTHLY_TEMP[event_date.month]
    )
    level = str(normalized["level"] or _event_level(load)).lower()
    if level not in {"low", "med", "high"}:
        level = _event_level(load)
    cooling = normalized["cooling"] or _cooling_action(load, temp, normalized["category"])
    desc = normalized["desc"] or (
        f"{normalized['category']} kategorisinde {normalized['load'] or 'Medium'} etki bekleniyor."
    )

    return {
        "id": event_id,
        "day": event_date.day,
        "month": event_date.strftime("%B"),
        "name": str(normalized["name"]),
        "load": round(load, 1),
        "level": level,
        "date": event_date.isoformat(),
        "temp": round(temp, 1),
        "desc": str(desc),
        "cooling": str(cooling),
    }


def _sniff_delimiter(content: str) -> str:
    sample = "\n".join(line for line in content.splitlines()[:5] if line.strip())
    delimiter_scores = {
        ",": sample.count(","),
        ";": sample.count(";"),
        "\t": sample.count("\t"),
        "|": sample.count("|"),
    }
    delimiter, score = max(delimiter_scores.items(), key=lambda item: item[1])
    if score == 0:
        return "|"
    return delimiter


def _looks_like_header(parts: list[str]) -> bool:
    known_headers = {
        "name",
        "event_name",
        "title",
        "olay_adi",
        "date",
        "timestamp",
        "event_date",
        "tarih",
        "load",
        "server_load",
        "server_workload_pct",
        "trafik_yuku",
        "temp",
        "ambient_temp_c",
        "temperature",
        "sicaklik",
    }
    return any(part.strip().lower() in known_headers for part in parts)


def _parse_delimited_text(content: str) -> list[dict[str, Any]]:
    delimiter = _sniff_delimiter(content)
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return []

    first_parts = [part.strip() for part in lines[0].split(delimiter)]
    if _looks_like_header(first_parts):
        reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=delimiter)
        rows: list[dict[str, Any]] = []
        for row in reader:
            values = [value for value in row.values() if value not in (None, "")]
            if len(values) == 1 and not _looks_like_header([values[0]]):
                rows.append(_parse_free_text_event(values[0]))
            else:
                rows.append(dict(row))
        return rows

    rows: list[dict[str, Any]] = []
    for line in lines:
        parts = [part.strip() for part in line.split(delimiter)]
        if len(parts) == 1:
            row = _parse_free_text_event(parts[0])
        else:
            row = {
                field: parts[index]
                for index, field in enumerate(TEXT_EVENT_FIELDS)
                if index < len(parts) and parts[index] != ""
            }
        rows.append(row)
    return rows


def _parse_free_text_event(line: str) -> dict[str, Any]:
    text = line.strip()
    date_match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if date_match:
        year, month, day = date_match.groups()
        cleaned = text.replace(date_match.group(0), "").strip(" -:,")
        return {
            "name": cleaned or "Takvim olayi",
            "date": f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            "load": _infer_load_from_text(text),
            "desc": text,
        }

    turkish_date = re.search(
        r"(20\d{2}).*?(?:n[ıi]n|nin|nun|nün)?\s+(\d{1,2})\s+ay[ıi]n[ıi]n\s+(\d{1,2})(?:i|ı|u|ü)?",
        text,
        flags=re.IGNORECASE,
    )
    if turkish_date:
        year, month, day = turkish_date.groups()
        return {
            "name": _infer_name_from_text(text),
            "date": f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            "load": _infer_load_from_text(text),
            "desc": text,
        }

    return {"name": text, "date": "", "load": "medium", "desc": text}


def _infer_name_from_text(text: str) -> str:
    lowered = text.lower()
    if "maç" in lowered or "mac" in lowered:
        return "Kritik Mac Gunu"
    if "sınav" in lowered or "sinav" in lowered:
        return "Sinav Gunu"
    if "sonuç" in lowered or "sonuc" in lowered:
        return "Sonuc Aciklama Gunu"
    return text[:80]


def _infer_load_from_text(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("critical", "kritik", "final", "derbi", "maç", "mac")):
        return "high"
    if any(word in lowered for word in ("medium", "orta", "normal")):
        return "medium"
    if any(word in lowered for word in ("low", "dusuk", "düşük", "tatil")):
        return "low"
    return "medium"


def _parse_json_rows(content: str) -> list[dict[str, Any]]:
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("events", [])
    if not isinstance(parsed, list):
        raise ValueError("JSON icerigi liste veya {'events': [...]} olmali.")
    return [dict(row) for row in parsed]


def parse_calendar_events(content: str, filename: str = "events.json") -> dict[str, Any]:
    """Parse CSV, JSON, TSV, TXT or Markdown calendar uploads."""

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "json"
    rows: list[dict[str, Any]]

    if ext == "csv":
        reader = csv.DictReader(StringIO(content))
        rows = [dict(row) for row in reader]
    elif ext == "tsv":
        reader = csv.DictReader(StringIO(content), delimiter="\t")
        rows = [dict(row) for row in reader]
    elif ext == "json":
        rows = _parse_json_rows(content)
    elif ext in {"txt", "md", "text"}:
        stripped = content.lstrip()
        if stripped.startswith("[") or stripped.startswith("{"):
            rows = _parse_json_rows(content)
        else:
            rows = _parse_delimited_text(content)
    else:
        rows = _parse_delimited_text(content)

    events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        try:
            events.append(normalize_calendar_event(row, event_id=index))
        except (TypeError, ValueError) as exc:
            errors.append({"row": index, "error": str(exc)})

    return {
        "events": events,
        "accepted_count": len(events),
        "rejected_count": len(errors),
        "errors": errors,
    }
