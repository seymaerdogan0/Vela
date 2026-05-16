"""NVIDIA Nemotron integration for Turkish operational reports."""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_URL = os.getenv(
    "NVIDIA_API_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
NVIDIA_MODEL = os.getenv(
    "NVIDIA_MODEL",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
)
NVIDIA_TIMEOUT_SECONDS = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "25"))

SYSTEM_PROMPT = """
Sen ThermaIQ'in veri merkezi enerji danismani ajanisin.
Hedef kitlen teknik tesis muduru: net, uygulanabilir ve riskleri acikca soyleyen
Turkce operasyon raporlari yaz. Verilen sayilari uydurma; sadece girdideki
metrikleri kullan. ASHRAE guvenlik limitleri, fizik dogrulama sonucu ve tasarruf
etkisini karar odakli anlat.
""".strip()


class NemotronError(RuntimeError):
    """Raised when NVIDIA report generation fails unexpectedly."""


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "hesaplanmadi"
    return f"{value:,.0f} TL".replace(",", ".")


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "belirtilmedi"
    return f"%{value:.0f}"


def normalize_report_input(raw: dict[str, Any]) -> dict[str, Any]:
    """Create a stable report payload from optimizer/backend raw values."""

    current_pue = float(raw["current_pue"])
    optimum_pue = float(raw["optimum_pue"])
    pue_delta = current_pue - optimum_pue
    improvement_pct = (pue_delta / current_pue) * 100 if current_pue else 0.0

    return {
        "scenario_name": raw.get("scenario_name", "Canli operasyon"),
        "current_pue": current_pue,
        "optimum_pue": optimum_pue,
        "pue_delta": pue_delta,
        "improvement_pct": improvement_pct,
        "ambient_temp_c": raw.get("ambient_temp_c"),
        "server_workload_pct": raw.get("server_workload_pct"),
        "inlet_temp_c": raw.get("inlet_temp_c"),
        "current_chiller_pct": raw.get("current_chiller_pct"),
        "optimized_chiller_pct": raw.get("optimized_chiller_pct"),
        "current_fan_pct": raw.get("current_fan_pct"),
        "optimized_fan_pct": raw.get("optimized_fan_pct"),
        "monthly_savings_tl": raw.get("monthly_savings_tl", raw.get("savings_tl")),
        "co2_savings_ton_month": raw.get("co2_savings_ton_month"),
        "physics_status": raw.get("physics_status", "not_checked"),
        "physics_notes": raw.get("physics_notes", []),
        "anomalies": raw.get("anomalies", []),
        "recommended_actions": raw.get("recommended_actions", []),
    }


def validate_report_payload(payload: dict[str, Any]) -> list[str]:
    """Return human-readable validation warnings without blocking the demo."""

    warnings: list[str] = []

    if not 1.0 <= payload["current_pue"] <= 3.0:
        warnings.append("Mevcut PUE beklenen veri merkezi araliginin disinda.")
    if not 1.0 <= payload["optimum_pue"] <= 3.0:
        warnings.append("Optimum PUE beklenen veri merkezi araliginin disinda.")
    if payload["optimum_pue"] > payload["current_pue"]:
        warnings.append("Optimum PUE mevcut PUE'den yuksek gorunuyor.")

    inlet_temp = payload.get("inlet_temp_c")
    if inlet_temp is not None and float(inlet_temp) > 27.0:
        warnings.append("ASHRAE TC 9.9 sunucu giris sicakligi limiti asilmis olabilir.")

    physics_status = payload.get("physics_status")
    if physics_status not in {"ok", "warning", "rejected", "not_checked"}:
        warnings.append("Fizik dogrulama durumu taninmiyor.")

    return warnings


def build_report_prompt(payload: dict[str, Any], validation_warnings: list[str]) -> str:
    """Turn raw backend metrics into a constrained Nemotron prompt."""

    return f"""
Asagidaki ThermaIQ optimizasyon ciktisini tesis mudurune yonelik 3 paragraflik
Turkce operasyon raporuna donustur.

Kurallar:
- Ilk paragraf mevcut durum ve PUE iyilesmesini aciklasin.
- Ikinci paragraf chiller/fan ayarlarini ve fizik/ASHRAE dogrulamasini anlatsin.
- Ucuncu paragraf TL tasarruf, CO2 etkisi ve uygulanacak aksiyonu versin.
- Sonunda "Oncelikli aksiyon:" ile tek cumlelik net karar yaz.
- Verilmeyen metrikleri uydurma.

Veri:
- Senaryo: {payload['scenario_name']}
- Mevcut PUE: {payload['current_pue']:.2f}
- Onerilen PUE: {payload['optimum_pue']:.2f}
- PUE iyilesmesi: {payload['improvement_pct']:.1f}%
- Dis sicaklik: {payload.get('ambient_temp_c', 'belirtilmedi')} C
- Sunucu yuku: {_fmt_pct(payload.get('server_workload_pct'))}
- Inlet sicakligi: {payload.get('inlet_temp_c', 'belirtilmedi')} C
- Chiller: {_fmt_pct(payload.get('current_chiller_pct'))} -> {_fmt_pct(payload.get('optimized_chiller_pct'))}
- Fan/AHU: {_fmt_pct(payload.get('current_fan_pct'))} -> {_fmt_pct(payload.get('optimized_fan_pct'))}
- Aylik tasarruf: {_fmt_money(payload.get('monthly_savings_tl'))}
- CO2 etkisi: {payload.get('co2_savings_ton_month', 'hesaplanmadi')} ton/ay
- Fizik dogrulama: {payload.get('physics_status')}
- Fizik notlari: {payload.get('physics_notes') or 'yok'}
- Anomali notlari: {payload.get('anomalies') or 'yok'}
- Onerilen aksiyonlar: {payload.get('recommended_actions') or 'yok'}
- Veri uyarilari: {validation_warnings or 'yok'}
""".strip()


def build_local_report(payload: dict[str, Any], validation_warnings: list[str]) -> str:
    """Deterministic fallback used when API key/network is unavailable."""

    pue_sentence = (
        f"{payload['scenario_name']} senaryosunda mevcut PUE {payload['current_pue']:.2f}, "
        f"onerilen calisma noktasinda {payload['optimum_pue']:.2f}. "
        f"Bu, yaklasik %{payload['improvement_pct']:.1f} iyilesme anlamina geliyor."
    )
    thermal_sentence = (
        f"Dis sicaklik {payload.get('ambient_temp_c', 'belirtilmedi')} C ve sunucu yuku "
        f"{_fmt_pct(payload.get('server_workload_pct'))}. Chiller ayari "
        f"{_fmt_pct(payload.get('current_chiller_pct'))} seviyesinden "
        f"{_fmt_pct(payload.get('optimized_chiller_pct'))} seviyesine, fan/AHU ayari "
        f"{_fmt_pct(payload.get('current_fan_pct'))} seviyesinden "
        f"{_fmt_pct(payload.get('optimized_fan_pct'))} seviyesine cekilebilir."
    )
    savings_sentence = (
        f"Aylik beklenen tasarruf {_fmt_money(payload.get('monthly_savings_tl'))}; "
        f"CO2 etkisi {payload.get('co2_savings_ton_month', 'hesaplanmadi')} ton/ay. "
        f"Fizik dogrulama durumu: {payload.get('physics_status')}."
    )

    warning_text = ""
    if validation_warnings:
        warning_text = " Veri uyarisi: " + " ".join(validation_warnings)

    return (
        f"{pue_sentence}\n\n"
        f"{thermal_sentence} ASHRAE inlet limiti icin mevcut inlet sicakligi "
        f"{payload.get('inlet_temp_c', 'belirtilmedi')} C olarak izlenmelidir.{warning_text}\n\n"
        f"{savings_sentence}\n\n"
        "Oncelikli aksiyon: Onerilen chiller ve fan setlerini kademeli uygulayin, "
        "ilk 30 dakika inlet sicakligi ve PUE trendini canli takip edin."
    )


def call_nemotron(prompt: str) -> str:
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key or api_key == "nvapi-xxx":
        raise NemotronError("NVIDIA_API_KEY is not configured.")

    response = requests.post(
        NVIDIA_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": NVIDIA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 650,
        },
        timeout=NVIDIA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise NemotronError("Unexpected NVIDIA API response format.") from exc


def generate_operational_report(
    raw_payload: dict[str, Any],
    *,
    use_mock: bool = False,
) -> dict[str, Any]:
    """Generate a Turkish operational report from raw optimizer output."""

    payload = normalize_report_input(raw_payload)
    validation_warnings = validate_report_payload(payload)
    prompt = build_report_prompt(payload, validation_warnings)

    provider = "nvidia-nemotron"
    model = NVIDIA_MODEL
    api_warning = None

    if use_mock:
        provider = "local-template"
        model = "thermaiq-local-template"
        report = build_local_report(payload, validation_warnings)
    else:
        try:
            report = call_nemotron(prompt)
        except (NemotronError, requests.RequestException) as exc:
            provider = "local-template"
            model = "thermaiq-local-template"
            api_warning = str(exc)
            report = build_local_report(payload, validation_warnings)

    return {
        "provider": provider,
        "model": model,
        "report": report,
        "validated": not validation_warnings,
        "validation_warnings": validation_warnings,
        "api_warning": api_warning,
        "source_metrics": payload,
    }
