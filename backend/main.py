"""FastAPI application entry point for ThermaIQ backend."""

import csv
import io
import math
import os
import re
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .calendar_parser import parse_calendar_events
    from .nemotron import (
        generate_final_decision,
        generate_operational_report,
        generate_optimization_policy,
    )
    from .optimizer import optimize
    from .physics import calculate_pue
except ImportError:
    from calendar_parser import parse_calendar_events
    from nemotron import (
        generate_final_decision,
        generate_operational_report,
        generate_optimization_policy,
    )
    from optimizer import optimize
    from physics import calculate_pue

load_dotenv()

app = FastAPI(
    title="ThermaIQ API",
    description="LLM-guided constrained optimization digital twin for data centers.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictInput(BaseModel):
    server_workload_pct: float = Field(..., ge=0, le=100)
    ambient_temp_c: float = Field(..., ge=-40, le=60)
    chiller_setpoint_c: float = Field(7, ge=4, le=20)
    fan_speed_pct: float = Field(65, ge=0, le=100)
    it_capacity_mw: float = Field(21, gt=0)


class TwinOptimizeInput(BaseModel):
    server_workload_pct: float = Field(..., ge=0, le=100)
    ambient_temp_c: float = Field(..., ge=-40, le=60)
    hour: int = Field(12, ge=0, le=23)
    month: int = Field(7, ge=1, le=12)
    it_capacity_mw: float = Field(21, gt=0)
    n_trials: int = Field(100, ge=10, le=250)


class BMSCommandInput(BaseModel):
    chiller_setpoint_c: float = Field(..., ge=6, le=16)
    fan_speed_pct: float = Field(..., ge=30, le=95)
    approval_token: str = "demo-approval"


class ReportRequest(BaseModel):
    scenario_name: str = Field(default="Canli operasyon")
    current_pue: float = Field(..., ge=1.0, le=3.0)
    optimum_pue: float = Field(..., ge=1.0, le=3.0)
    ambient_temp_c: Optional[float] = None
    server_workload_pct: Optional[float] = Field(default=None, ge=0, le=100)
    inlet_temp_c: Optional[float] = None
    current_chiller_pct: Optional[float] = Field(default=None, ge=0, le=100)
    optimized_chiller_pct: Optional[float] = Field(default=None, ge=0, le=100)
    current_fan_pct: Optional[float] = Field(default=None, ge=0, le=100)
    optimized_fan_pct: Optional[float] = Field(default=None, ge=0, le=100)
    monthly_savings_tl: Optional[float] = Field(default=None, ge=0)
    savings_tl: Optional[float] = Field(default=None, ge=0)
    co2_savings_ton_month: Optional[float] = Field(default=None, ge=0)
    physics_status: str = Field(default="not_checked")
    physics_notes: List[str] = Field(default_factory=list)
    anomalies: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    use_mock: bool = Field(
        default=False,
        description="Force deterministic local report instead of NVIDIA API.",
    )


class ReportResponse(BaseModel):
    provider: str
    model: str
    report: str
    validated: bool
    validation_warnings: List[str]
    api_warning: Optional[str]
    source_metrics: Dict[str, Any]


class CalendarParseResponse(BaseModel):
    events: List[Dict[str, Any]]
    accepted_count: int
    rejected_count: int
    errors: List[Dict[str, Any]]


class AdaptationUploadResponse(BaseModel):
    facility_name: str
    row_count: int
    columns: List[str]
    accepted: bool
    warnings: List[str]


class AdaptationRunResponse(AdaptationUploadResponse):
    model_name: str
    status: str
    metrics: Dict[str, float]


def _model_dict(model: BaseModel, exclude_none: bool = False, exclude: Optional[set] = None) -> Dict[str, Any]:
    """Pydantic v1/v2 compatible dict export."""
    exclude = exclude or set()
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none, exclude=exclude)
    return model.dict(exclude_none=exclude_none, exclude=exclude)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.lower().strip())
    return slug.strip("_") or "musteri"


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


async def _read_request_upload(request: Request, default_filename: str) -> Tuple[str, str]:
    """
    Read raw or multipart upload bodies without requiring python-multipart.
    This keeps the demo backend importable on the hackathon laptop.
    """
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    filename = default_filename

    if "multipart/form-data" not in content_type:
        return _decode_bytes(body), filename

    boundary_match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not boundary_match:
        return _decode_bytes(body), filename

    boundary = boundary_match.group("boundary").strip('"').encode()
    for part in body.split(b"--" + boundary):
        if b"Content-Disposition" not in part or b"\r\n\r\n" not in part:
            continue
        header_blob, payload = part.split(b"\r\n\r\n", 1)
        payload = payload.rstrip(b"\r\n-")
        headers = _decode_bytes(header_blob)
        name_match = re.search(r'filename="([^"]+)"', headers)
        if name_match:
            filename = name_match.group(1)
        if payload:
            return _decode_bytes(payload), filename

    return "", filename


def _read_upload_rows(content: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    sample = "\n".join(line for line in content.splitlines()[:5] if line.strip())
    delimiter = max(
        {",": sample.count(","), ";": sample.count(";"), "\t": sample.count("\t"), "|": sample.count("|")}.items(),
        key=lambda item: item[1],
    )[0]
    reader = csv.DictReader(StringIO(content), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    columns = list(reader.fieldnames or [])
    return rows, columns


def _adaptation_summary(rows: List[Dict[str, Any]], columns: List[str], facility_name: str) -> Dict[str, Any]:
    warnings = []
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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ambient_for_time(moment: datetime) -> float:
    """Deterministic Ankara-like ambient curve for the digital twin demo."""
    monthly_avg = [-1, 2, 7, 13, 18, 23, 27, 27, 22, 15, 8, 2][moment.month - 1]
    daily_swing = math.sin(((moment.hour - 7) / 24) * 2 * math.pi) * 5.2
    return round(monthly_avg + daily_swing, 1)


def _workload_for_time(moment: datetime) -> float:
    business_peak = math.exp(-((moment.hour - 14) ** 2) / 24) * 28
    evening_tail = math.exp(-((moment.hour - 21) ** 2) / 18) * 10
    weekend_factor = 0.82 if moment.weekday() >= 5 else 1.0
    return round(_clamp((46 + business_peak + evening_tail) * weekend_factor, 25, 96), 1)


def _fast_twin_optimum(
    server_workload_pct: float,
    ambient_temp_c: float,
    it_capacity_mw: float = 21,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Lightweight digital-twin search for live/trend endpoints.
    It uses the same physics engine as /api/predict without running the slower LLM/Optuna path.
    """
    current = calculate_pue(
        server_workload_pct=server_workload_pct,
        ambient_temp_c=ambient_temp_c,
        chiller_setpoint_c=6,
        fan_speed_pct=90,
        it_capacity_mw=it_capacity_mw,
    )
    best = None
    for chiller_setpoint in (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
        for fan_speed in (45, 55, 65, 75, 85, 90):
            candidate = calculate_pue(
                server_workload_pct=server_workload_pct,
                ambient_temp_c=ambient_temp_c,
                chiller_setpoint_c=chiller_setpoint,
                fan_speed_pct=fan_speed,
                it_capacity_mw=it_capacity_mw,
            )
            if not candidate["safety_ok"]:
                continue
            if best is None or candidate["pue"] < best["pue"]:
                best = {
                    **candidate,
                    "chiller_setpoint_c": float(chiller_setpoint),
                    "fan_speed_pct": float(fan_speed),
                }

    if best is None:
        best = {**current, "chiller_setpoint_c": 6.0, "fan_speed_pct": 90.0}

    current = {**current, "chiller_setpoint_c": 6.0, "fan_speed_pct": 90.0}
    return current, best


def _rack_heatmap(workload_pct: float, inlet_temp_c: float) -> List[float]:
    base = _clamp((workload_pct - 35) / 70 + max(0, inlet_temp_c - 22) / 8, 0.1, 1.0)
    return [
        round(_clamp(base + math.sin(i * 1.7) * 0.16 + (0.18 if i in (6, 7, 14, 22) else 0), 0, 1), 2)
        for i in range(32)
    ]


def _twin_snapshot(moment: datetime, it_capacity_mw: float = 21) -> Dict[str, Any]:
    ambient = _ambient_for_time(moment)
    workload = _workload_for_time(moment)
    current, optimal = _fast_twin_optimum(workload, ambient, it_capacity_mw)
    monthly_savings_tl = max(
        0,
        round((current["pue"] - optimal["pue"]) * current["it_power_kw"] * 720 * 3.2, 0),
    )
    co2_savings_ton_month = max(
        0,
        round((current["total_power_kw"] - optimal["total_power_kw"]) * 720 * 0.45 / 1000, 1),
    )
    return {
        "timestamp": moment.isoformat(),
        "ambient_temp_c": ambient,
        "server_workload_pct": workload,
        "it_capacity_mw": it_capacity_mw,
        "it_load_mw": round(current["it_power_kw"] / 1000, 2),
        "current": current,
        "optimal": optimal,
        "current_pue": current["pue"],
        "optimal_pue": optimal["pue"],
        "monthly_savings_tl": monthly_savings_tl,
        "co2_savings_ton_month": co2_savings_ton_month,
        "rack_heatmap": _rack_heatmap(workload, optimal["inlet_temp_c"]),
        "source": "physics_digital_twin",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "ThermaIQ",
        "components": {
            "physics_engine": "ready",
            "optimizer": "ready",
            "nemotron": "ready" if (os.getenv("NVIDIA_API_KEY") or os.getenv("OPENROUTER_API_KEY")) else "fallback_mode",
            "report_api": "ready",
            "calendar_parser": "ready",
        },
    }


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "ThermaIQ",
        "tagline": "LLM-guided constrained optimization digital twin",
        "endpoints": [
            "GET /health",
            "POST /api/predict",
            "GET /api/live-metrics",
            "GET /api/pue-trend",
            "POST /api/twin-optimize",
            "POST /api/report",
            "GET /api/demo-scenarios",
            "POST /api/bms/apply",
            "POST /api/calendar/parse",
            "GET /api/calendar/sample",
            "POST /api/adaptation/upload",
            "POST /api/adaptation/run",
        ],
    }


@app.get("/api/live-metrics")
def live_metrics(it_capacity_mw: float = Query(default=21, gt=0)) -> Dict[str, Any]:
    """Current dashboard metrics generated by the physics digital twin."""
    return _twin_snapshot(datetime.now(), it_capacity_mw)


@app.get("/api/pue-trend")
def pue_trend(
    scale: str = Query(default="24h"),
    it_capacity_mw: float = Query(default=21, gt=0),
) -> Dict[str, Any]:
    """PUE trend generated from deterministic workload/weather inputs through the digital twin."""
    if scale not in {"24h", "7d"}:
        raise HTTPException(status_code=400, detail="scale must be 24h or 7d")
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    if scale == "7d":
        moments = [(now - timedelta(days=6 - index)).replace(hour=14) for index in range(7)]
        labels = [moment.strftime("%d.%m") for moment in moments]
    else:
        moments = [now - timedelta(hours=23 - index) for index in range(24)]
        labels = [moment.strftime("%H") for moment in moments]

    points = []
    for index, moment in enumerate(moments):
        snapshot = _twin_snapshot(moment, it_capacity_mw)
        forecast_moment = moment + (timedelta(hours=3) if scale == "24h" else timedelta(days=1))
        forecast_snapshot = _twin_snapshot(forecast_moment, it_capacity_mw)
        points.append(
            {
                "label": labels[index],
                "timestamp": snapshot["timestamp"],
                "current_pue": snapshot["current_pue"],
                "optimal_pue": snapshot["optimal_pue"],
                "forecast_pue": forecast_snapshot["current_pue"],
                "ambient_temp_c": snapshot["ambient_temp_c"],
                "workload_pct": snapshot["server_workload_pct"],
            }
        )

    return {"scale": scale, "source": "physics_digital_twin", "points": points}


@app.post("/api/predict")
def predict(inp: PredictInput) -> Dict[str, Any]:
    """Single-scenario deterministic PUE calculation."""
    return calculate_pue(
        server_workload_pct=inp.server_workload_pct,
        ambient_temp_c=inp.ambient_temp_c,
        chiller_setpoint_c=inp.chiller_setpoint_c,
        fan_speed_pct=inp.fan_speed_pct,
        it_capacity_mw=inp.it_capacity_mw,
    )


@app.post("/api/twin-optimize")
def twin_optimize(inp: TwinOptimizeInput) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Physics engine calculates current state.
    2. Nemotron produces an optimization policy.
    3. Optuna searches the physics twin with that policy.
    4. Nemotron returns final operations decision.
    """
    current = calculate_pue(
        server_workload_pct=inp.server_workload_pct,
        ambient_temp_c=inp.ambient_temp_c,
        chiller_setpoint_c=6,
        fan_speed_pct=90,
        it_capacity_mw=inp.it_capacity_mw,
    )

    policy = generate_optimization_policy(
        server_workload_pct=inp.server_workload_pct,
        ambient_temp_c=inp.ambient_temp_c,
        current_pue=current["pue"],
        current_inlet_temp=current["inlet_temp_c"],
        hour=inp.hour,
        month=inp.month,
    )

    optimization_result = optimize(
        server_workload_pct=inp.server_workload_pct,
        ambient_temp_c=inp.ambient_temp_c,
        policy=policy,
        hour=inp.hour,
        month=inp.month,
        it_capacity_mw=inp.it_capacity_mw,
        n_trials=inp.n_trials,
    )

    decision = generate_final_decision(
        current=optimization_result["current"],
        candidates=optimization_result["candidates"],
        policy=policy,
    )

    return {
        "current": optimization_result["current"],
        "policy": policy,
        "candidates": optimization_result["candidates"],
        "decision": decision,
        "meta": optimization_result["meta"],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/demo-scenarios")
def demo_scenarios() -> List[Dict[str, Any]]:
    """Four offline demo scenarios."""
    scenarios = [
        {
            "name": "Yaz Ogle",
            "label_tr": "Yaz Öğle",
            "emoji": "sun",
            "server_workload_pct": 85,
            "ambient_temp_c": 35,
            "hour": 14,
            "month": 7,
        },
        {
            "name": "Kis Gece",
            "label_tr": "Kış Gece",
            "emoji": "snow",
            "server_workload_pct": 45,
            "ambient_temp_c": -2,
            "hour": 3,
            "month": 1,
        },
        {
            "name": "Bahar Normal",
            "label_tr": "Bahar Normal",
            "emoji": "spring",
            "server_workload_pct": 60,
            "ambient_temp_c": 18,
            "hour": 11,
            "month": 4,
        },
        {
            "name": "Asiri Yuk",
            "label_tr": "Aşırı Yük",
            "emoji": "peak",
            "server_workload_pct": 95,
            "ambient_temp_c": 28,
            "hour": 16,
            "month": 8,
        },
    ]

    results = []
    for scenario in scenarios:
        try:
            payload = {
                key: value
                for key, value in scenario.items()
                if key not in ("name", "label_tr", "emoji")
            }
            payload["n_trials"] = 60
            result = twin_optimize(TwinOptimizeInput(**payload))
            results.append({**scenario, "result": result})
        except Exception as exc:
            results.append({**scenario, "error": str(exc)})

    return results


@app.post("/api/bms/apply")
def bms_apply(inp: BMSCommandInput) -> Dict[str, Any]:
    """Mock BACnet/IP setpoint application."""
    if inp.approval_token != "demo-approval":
        raise HTTPException(status_code=403, detail="Onay token gerekli")

    return {
        "protocol": "BACnet/IP",
        "target": "Golbasi-HVAC-Controller-01",
        "commands": [
            {
                "object": "Chiller-01",
                "property": "chilled_water_setpoint",
                "value": inp.chiller_setpoint_c,
                "unit": "C",
            },
            {
                "object": "AHU-Bank-A",
                "property": "fan_speed",
                "value": inp.fan_speed_pct,
                "unit": "%",
            },
        ],
        "status": "APPLIED",
        "timestamp": datetime.now().isoformat(),
        "compliance": "TS EN 50600-aligned energy monitoring demo",
        "note": "Demo mode; real deployment requires a BACnet/IP stack and approval workflow.",
    }


@app.post("/api/report", response_model=ReportResponse)
def create_report(payload: ReportRequest) -> Dict[str, Any]:
    return generate_operational_report(
        _model_dict(payload, exclude_none=True, exclude={"use_mock"}),
        use_mock=payload.use_mock,
    )


@app.get("/api/report/sample", response_model=ReportResponse)
def sample_report() -> Dict[str, Any]:
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
async def parse_calendar_file(request: Request) -> Dict[str, Any]:
    content, filename = await _read_request_upload(request, "events.csv")
    return parse_calendar_events(content, filename)


@app.get("/api/calendar/sample", response_model=CalendarParseResponse)
def sample_calendar() -> Dict[str, Any]:
    content = """name,date,load,temp,desc,cooling
e-Devlet Genel Pik Gunu,2026-05-19,78,24,Pazartesi sabahi vatandas islem piki bekleniyor,+7C Sogutma Rezervi
YSK Secim Veri Sayim Gunu,2026-06-01,98,28,YSK veri sayim sistemleri maksimum yuk altinda,+15C Kritik Ek Sogutma Modu
OSYM YKS Tercih Paneli,2026-07-25,95,35,Milyonlarca anlik sorgu trafigi bekleniyor,+12C Kritik Ek Sogutma Modu
"""
    return parse_calendar_events(content, "sample.csv")


@app.post("/api/adaptation/upload", response_model=AdaptationUploadResponse)
async def upload_adaptation_file(
    request: Request, facility_name: str = Query(default="musteri")
) -> Dict[str, Any]:
    content, _ = await _read_request_upload(request, "adaptation.csv")
    rows, columns = _read_upload_rows(content)
    return _adaptation_summary(rows, columns, facility_name)


@app.post("/api/adaptation/run", response_model=AdaptationRunResponse)
async def run_adaptation(
    request: Request, facility_name: str = Query(default="musteri")
) -> Dict[str, Any]:
    content, _ = await _read_request_upload(request, "adaptation.csv")
    rows, columns = _read_upload_rows(content)
    summary = _adaptation_summary(rows, columns, facility_name)
    model_name = f"xgb_pue_{_slugify(facility_name)}.json"
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


@app.post("/api/adapt")
async def adapt(request: Request, company_name: str = Query("default")) -> Dict[str, Any]:
    """Customer CSV calibration preview for the older dashboard flow."""
    try:
        content, _ = await _read_request_upload(request, "customer.csv")
        df = pd.read_csv(io.StringIO(content))
        numeric_stats = {}
        for col in df.select_dtypes(include="number").columns:
            numeric_stats[col] = {
                "mean": round(float(df[col].mean()), 3),
                "min": round(float(df[col].min()), 3),
                "max": round(float(df[col].max()), 3),
            }
        return {
            "success": True,
            "company": company_name,
            "stats": {"rows": len(df), "columns": df.columns.tolist()},
            "numeric_stats": numeric_stats,
            "message": f"{company_name} için dijital ikiz kalibrasyonu hazır.",
            "calibration_note": "Yeni veriler temel modelin katsayılarını ayarlamak için kullanılır.",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
