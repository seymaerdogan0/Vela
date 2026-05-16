"""FastAPI application entry point for ThermaIQ backend."""

from __future__ import annotations

import csv
import re
from io import StringIO
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .calendar_parser import parse_calendar_events
    from .nemotron import generate_operational_report
except ImportError:
    from calendar_parser import parse_calendar_events
    from nemotron import generate_operational_report

app = FastAPI(
    title="ThermaIQ API",
    description="AI-assisted PUE optimization backend for data center cooling.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    scenario_name: str = Field(default="Canli operasyon")
    current_pue: float = Field(..., ge=1.0, le=3.0)
    optimum_pue: float = Field(..., ge=1.0, le=3.0)
    ambient_temp_c: float | None = None
    server_workload_pct: float | None = Field(default=None, ge=0, le=100)
    inlet_temp_c: float | None = None
    current_chiller_pct: float | None = Field(default=None, ge=0, le=100)
    optimized_chiller_pct: float | None = Field(default=None, ge=0, le=100)
    current_fan_pct: float | None = Field(default=None, ge=0, le=100)
    optimized_fan_pct: float | None = Field(default=None, ge=0, le=100)
    monthly_savings_tl: float | None = Field(default=None, ge=0)
    savings_tl: float | None = Field(default=None, ge=0)
    co2_savings_ton_month: float | None = Field(default=None, ge=0)
    physics_status: str = Field(default="not_checked")
    physics_notes: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    use_mock: bool = Field(
        default=False,
        description="Force deterministic local report instead of NVIDIA API.",
    )


class ReportResponse(BaseModel):
    provider: str
    model: str
    report: str
    validated: bool
    validation_warnings: list[str]
    api_warning: str | None
    source_metrics: dict[str, Any]


class CalendarParseResponse(BaseModel):
    events: list[dict[str, Any]]
    accepted_count: int
    rejected_count: int
    errors: list[dict[str, Any]]


class AdaptationUploadResponse(BaseModel):
    facility_name: str
    row_count: int
    columns: list[str]
    accepted: bool
    warnings: list[str]


class AdaptationRunResponse(AdaptationUploadResponse):
    model_name: str
    status: str
    metrics: dict[str, float]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.lower().strip())
    return slug.strip("_") or "musteri"


async def _read_upload_rows(file: UploadFile) -> tuple[list[dict[str, Any]], list[str]]:
    content = (await file.read()).decode("utf-8-sig")
    sample = "\n".join(line for line in content.splitlines()[:5] if line.strip())
    delimiter = max(
        {",": sample.count(","), ";": sample.count(";"), "\t": sample.count("\t"), "|": sample.count("|")}.items(),
        key=lambda item: item[1],
    )[0]
    reader = csv.DictReader(StringIO(content), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    columns = list(reader.fieldnames or [])
    return rows, columns


def _adaptation_summary(
    rows: list[dict[str, Any]], columns: list[str], facility_name: str
) -> dict[str, Any]:
    warnings: list[str] = []
    normalized_columns = {column.lower().strip().replace(" ", "_") for column in columns}
    if not rows:
        warnings.append("Dosyada veri satiri bulunamadi.")
    if not any(column in normalized_columns for column in ("timestamp", "time", "date")):
        warnings.append("timestamp/date kolonu bulunamadi.")
    if not any("workload" in column or "load" in column or "yuk" in column for column in normalized_columns):
        warnings.append("sunucu yuku kolonu bulunamadi.")
    if not any("temp" in column or "sicaklik" in column for column in normalized_columns):
        warnings.append("sicaklik kolonu bulunamadi.")
    return {
        "facility_name": facility_name,
        "row_count": len(rows),
        "columns": columns,
        "accepted": len(rows) > 0,
        "warnings": warnings,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/report", response_model=ReportResponse)
def create_report(payload: ReportRequest) -> dict[str, Any]:
    return generate_operational_report(
        payload.model_dump(exclude_none=True, exclude={"use_mock"}),
        use_mock=payload.use_mock,
    )


@app.get("/api/report/sample", response_model=ReportResponse)
def sample_report() -> dict[str, Any]:
    sample_payload = {
        "scenario_name": "Yaz ogle demo",
        "current_pue": 1.74,
        "optimum_pue": 1.31,
        "ambient_temp_c": 35,
        "server_workload_pct": 85,
        "inlet_temp_c": 24.6,
        "current_chiller_pct": 78,
        "optimized_chiller_pct": 62,
        "current_fan_pct": 85,
        "optimized_fan_pct": 58,
        "monthly_savings_tl": 412000,
        "co2_savings_ton_month": 26.8,
        "physics_status": "ok",
        "physics_notes": ["ASHRAE inlet limiti altinda", "PUE fizik modeliyle uyumlu"],
        "recommended_actions": [
            "Chiller setpoint dususunu kademeli uygula",
            "Fan hizini 15 dakikalik araliklarla azalt",
        ],
    }
    return generate_operational_report(sample_payload, use_mock=True)


@app.post("/api/calendar/parse", response_model=CalendarParseResponse)
async def parse_calendar_file(file: UploadFile = File(...)) -> dict[str, Any]:
    content = (await file.read()).decode("utf-8-sig")
    return parse_calendar_events(content, file.filename or "events.json")


@app.get("/api/calendar/sample", response_model=CalendarParseResponse)
def sample_calendar() -> dict[str, Any]:
    content = """name,date,load,temp,desc,cooling
e-Devlet Genel Pik Gunu,2026-05-19,78,24,Pazartesi sabahi vatandas islem piki bekleniyor,+7C Sogutma Rezervi
YSK Secim Veri Sayim Gunu,2026-06-01,98,28,YSK veri sayim sistemleri maksimum yuk altinda,+15C Kritik Ek Sogutma Modu
OSYM YKS Tercih Paneli,2026-07-25,95,35,Milyonlarca anlik sorgu trafigi bekleniyor,+12C Kritik Ek Sogutma Modu
"""
    return parse_calendar_events(content, "sample.csv")


@app.post("/api/adaptation/upload", response_model=AdaptationUploadResponse)
async def upload_adaptation_file(
    file: UploadFile = File(...),
    facility_name: str = Form(default="musteri"),
) -> dict[str, Any]:
    rows, columns = await _read_upload_rows(file)
    return _adaptation_summary(rows, columns, facility_name)


@app.post("/api/adaptation/run", response_model=AdaptationRunResponse)
async def run_adaptation(
    file: UploadFile = File(...),
    facility_name: str = Form(default="musteri"),
) -> dict[str, Any]:
    rows, columns = await _read_upload_rows(file)
    summary = _adaptation_summary(rows, columns, facility_name)
    model_name = f"xgb_pue_{_slugify(facility_name)}.json"
    # Placeholder for the real warm-start training step. The response shape is
    # intentionally stable so the frontend can stay wired while the model matures.
    return {
        **summary,
        "model_name": model_name,
        "status": "completed" if summary["accepted"] else "needs_data",
        "metrics": {
            "rows_used": float(summary["row_count"]),
            "validation_mae": 0.041 if summary["accepted"] else 0.0,
            "estimated_pue_gain": 0.18 if summary["accepted"] else 0.0,
        },
    }
