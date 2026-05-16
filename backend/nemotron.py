"""NVIDIA Nemotron helpers for ThermaIQ digital twin and reports."""

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    urllib3 = None

NVIDIA_API_URL = os.getenv(
    "NVIDIA_API_URL",
    os.getenv("NVIDIA_API", "https://integrate.api.nvidia.com/v1/chat/completions"),
)
NVIDIA_MODEL = os.getenv(
    "NVIDIA_MODEL",
    os.getenv("NVIDIA_MODEL_ID", "nvidia/llama-3.3-nemotron-super-49b-v1"),
)
NVIDIA_TIMEOUT_SECONDS = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "25"))
NVIDIA_VERIFY_SSL = os.getenv("NVIDIA_VERIFY_SSL", "false").lower() in {"1", "true", "yes"}


class NemotronError(RuntimeError):
    """Raised when NVIDIA report generation fails unexpectedly."""


POLICY_SYSTEM_PROMPT = """Sen Türksat Gölbaşı Veri Merkezi'nin Dijital İkiz Kontrolcüsüsün.
21 MW IT kapasiteli, ASHRAE 90.4 ve TS EN 50600 uyumlu bir tesissin.

Görevin: Mevcut tesis durumuna bakıp optimizasyon stratejisi belirlemek.
Stratejiler:
- safety_first: Yüksek yük veya yüksek sıcaklıkta termal risk öncelikli
- aggressive_savings: Düşük yük veya soğuk havada agresif tasarruf
- balanced: Normal koşullarda dengeli yaklaşım
- free_cooling: Dış sıcaklık 8°C altında, free cooling maksimize edilir
- peak_load: Yük %90+ veya tepe saatlerde stabilite öncelikli

Çıktı SADECE şu JSON formatında olsun, başka hiçbir şey yazma:
{
  "strategy": "safety_first|aggressive_savings|balanced|free_cooling|peak_load",
  "objective_weights": {
    "pue": 0.0-1.0,
    "thermal_risk": 0.0-1.0,
    "setpoint_change": 0.0-1.0
  },
  "search_space": {
    "chiller_setpoint_c": [min, max],
    "fan_speed_pct": [min, max]
  },
  "risk_policy": {
    "max_inlet_temp_c": <=27,
    "preferred_inlet_temp_c": 20-26.5
  },
  "reason_tr": "Türkçe gerekçe, 1-2 cümle"
}

Sınırlar:
- chiller_setpoint_c global: 6-16°C
- fan_speed_pct global: 30-95
- objective_weights toplamı 1.0 olmalı
- max_inlet_temp_c maksimum 27"""


DECISION_SYSTEM_PROMPT = """Sen Türksat Gölbaşı Veri Merkezi'nin Operasyon Karar Vericisisin.
Sana mevcut durum ve Optuna'nın bulduğu top 3 aday sunulacak.
Görevin: En iyi adayı seçmek ve operasyonel kararı vermek.

Karar kriterleri:
- En düşük PUE her zaman en iyi değildir
- Termal risk (inlet temp) ile tasarruf arasında denge
- ASHRAE-Recommended bandı tercih edilir, Allowable kabul edilebilir, VIOLATION asla
- Setpoint değişimi büyükse risk artar

Çıktı SADECE şu JSON formatında olsun:
{
  "decision": "APPROVE|REVIEW|REJECT",
  "selected_candidate_rank": 1|2|3,
  "risk_level": "low|medium|high",
  "standards_check": {
    "ashrae": "PASS|WARNING|FAIL",
    "pue": "IMPROVED|NEUTRAL|DEGRADED",
    "bms": "HUMAN_APPROVAL_REQUIRED|AUTO_APPLY_OK"
  },
  "operator_message_tr": "Türkçe operasyonel rapor, 3-4 cümle, sayısal değerlerle",
  "approval_question_tr": "Tesis müdürüne sorulacak Türkçe onay sorusu",
  "fallback_action": "Eğer öneri uygulandıktan sonra inlet sıcaklığı yükselirse yapılacak Türkçe aksiyon"
}"""


REPORT_SYSTEM_PROMPT = """
Sen ThermaIQ'in veri merkezi enerji danışmanı ajanısın.
Hedef kitlen teknik tesis müdürü: net, uygulanabilir ve riskleri açıkça söyleyen
Türkçe operasyon raporları yaz. Verilen sayıları uydurma; sadece girdideki
metrikleri kullan. ASHRAE güvenlik limitleri, fizik doğrulama sonucu ve tasarruf
etkisini karar odaklı anlat.
""".strip()


def _extract_json(content: str) -> Dict[str, Any]:
    """Parse JSON from plain content, fenced blocks, or text containing one object."""
    text = content.strip()
    if "```" in text:
        for block in text.split("```"):
            cleaned = block.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                text = cleaned
                break

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _api_key() -> Optional[str]:
    key = os.getenv("NVIDIA_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not key or key in {"nvapi-xxx", "sk-or-v1-xxx"}:
        return None
    return key


def _provider_headers(api_key: str) -> Dict[str, str]:
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in NVIDIA_API_URL:
        headers["HTTP-Referer"] = "http://localhost:8001"
        headers["X-Title"] = "ThermaIQ Data Center Twin"
    return headers


def _call_chat(system_prompt: str, user_message: str, max_tokens: int, temperature: float) -> str:
    api_key = _api_key()
    if not api_key:
        raise NemotronError("NVIDIA_API_KEY is not configured.")

    response = requests.post(
        NVIDIA_API_URL,
        headers=_provider_headers(api_key),
        json={
            "model": NVIDIA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "top_p": 0.7,
            "max_tokens": max_tokens,
        },
        timeout=NVIDIA_TIMEOUT_SECONDS,
        verify=NVIDIA_VERIFY_SSL,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        content = (message.get("reasoning") or "").strip()
    if not content:
        raise NemotronError("Empty NVIDIA response.")
    return content


def _call_nemotron_json(system_prompt: str, user_message: str, max_tokens: int = 500) -> Dict[str, Any]:
    return _extract_json(_call_chat(system_prompt, user_message, max_tokens, temperature=0.2))


def _fallback_policy(server_workload_pct: float, ambient_temp_c: float) -> Dict[str, Any]:
    """Rule-based fallback if API key is missing or the API fails."""
    if ambient_temp_c < 8:
        return {
            "strategy": "free_cooling",
            "objective_weights": {"pue": 0.65, "thermal_risk": 0.20, "setpoint_change": 0.15},
            "search_space": {"chiller_setpoint_c": [10, 16], "fan_speed_pct": [30, 60]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 24},
            "reason_tr": "Dış sıcaklık düşük. Free cooling maksimize edilebilir.",
            "source": "fallback",
        }
    if server_workload_pct >= 90:
        return {
            "strategy": "peak_load",
            "objective_weights": {"pue": 0.35, "thermal_risk": 0.55, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [6, 10], "fan_speed_pct": [75, 95]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 23},
            "reason_tr": "Yük tepe seviyede. Termal stabilite ve fan kapasitesi önceliklendirildi.",
            "source": "fallback",
        }
    if server_workload_pct > 85 or ambient_temp_c > 30:
        return {
            "strategy": "safety_first",
            "objective_weights": {"pue": 0.40, "thermal_risk": 0.50, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [6, 11], "fan_speed_pct": [65, 90]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 23},
            "reason_tr": "Yük veya dış sıcaklık yüksek. Güvenlik öncelikli optimizasyon seçildi.",
            "source": "fallback",
        }
    if server_workload_pct < 40 and ambient_temp_c < 18:
        return {
            "strategy": "aggressive_savings",
            "objective_weights": {"pue": 0.70, "thermal_risk": 0.20, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [9, 14], "fan_speed_pct": [35, 65]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 25},
            "reason_tr": "Düşük yük ve serin hava nedeniyle agresif tasarruf modu güvenli görünüyor.",
            "source": "fallback",
        }
    return {
        "strategy": "balanced",
        "objective_weights": {"pue": 0.55, "thermal_risk": 0.30, "setpoint_change": 0.15},
        "search_space": {"chiller_setpoint_c": [7, 13], "fan_speed_pct": [60, 90]},
        "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 25.5},
        "reason_tr": "Koşullar normal aralıkta. Tasarruf ve termal güvenlik dengelendi.",
        "source": "fallback",
    }


def _fallback_decision(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rule-based final decision if Nemotron is unavailable."""
    if not candidates:
        return {
            "decision": "REJECT",
            "selected_candidate_rank": None,
            "risk_level": "high",
            "standards_check": {
                "ashrae": "FAIL",
                "pue": "DEGRADED",
                "bms": "HUMAN_APPROVAL_REQUIRED",
            },
            "operator_message_tr": "Geçerli aday bulunamadı. Mevcut ayarlar korunmalı ve manuel inceleme başlatılmalı.",
            "approval_question_tr": "Manuel kontrol için operasyon ekibi çağırılsın mı?",
            "fallback_action": "Mevcut ayarlar korunur.",
            "source": "fallback",
        }

    valid = [c for c in candidates if c.get("ashrae_status") != "VIOLATION"]
    if not valid:
        return _fallback_decision([])

    risk_rank = {"low": 0, "medium": 1, "high": 2}
    best = sorted(valid, key=lambda c: (risk_rank.get(c.get("risk_level", "high"), 2), c.get("pue", 9)))[0]
    rank = best["rank"]
    decision = "APPROVE" if best.get("risk_level") in ("low", "medium") else "REVIEW"

    return {
        "decision": decision,
        "selected_candidate_rank": rank,
        "risk_level": best.get("risk_level", "medium"),
        "standards_check": {
            "ashrae": "PASS" if best.get("risk_level") != "high" else "WARNING",
            "pue": "IMPROVED",
            "bms": "HUMAN_APPROVAL_REQUIRED",
        },
        "operator_message_tr": (
            f"Rank {rank} adayı önerildi. PUE {best['pue']} seviyesine düşerken "
            f"inlet sıcaklığı {best['inlet_temp_c']}°C ve ASHRAE durumu {best['ashrae_status']}. "
            f"Beklenen aylık tasarruf {best['monthly_savings_tl']:,.0f} TL. "
            "Komut insan onayı sonrası BACnet/IP payload olarak uygulanmalıdır."
        ),
        "approval_question_tr": (
            f"CHILLER-01 için {best['chiller_setpoint_c']}°C setpoint ve "
            f"%{best['fan_speed_pct']} fan hızını BACnet/IP üzerinden uygulamak istiyor musunuz?"
        ),
        "fallback_action": (
            f"Inlet 26.5°C üzerine çıkarsa fan hızı %{min(95, best['fan_speed_pct'] + 10):.0f} "
            "seviyesine alınır ve chiller setpoint 1°C düşürülür."
        ),
        "source": "fallback",
    }


def _validate_policy_shape(policy: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(policy, dict):
        return fallback
    required = ("strategy", "objective_weights", "search_space", "risk_policy")
    if not all(key in policy for key in required):
        return fallback
    policy.setdefault("reason_tr", fallback.get("reason_tr", ""))
    policy["source"] = "nemotron"
    return policy


def _validate_decision_shape(
    decision: Dict[str, Any], candidates: List[Dict[str, Any]], fallback: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(decision, dict):
        return fallback
    ranks = {c.get("rank") for c in candidates}
    if decision.get("selected_candidate_rank") not in ranks:
        return fallback
    if decision.get("decision") not in ("APPROVE", "REVIEW", "REJECT"):
        return fallback
    decision.setdefault("source", "nemotron")
    return decision


def generate_optimization_policy(
    server_workload_pct: float,
    ambient_temp_c: float,
    current_pue: float,
    current_inlet_temp: float,
    hour: int = 12,
    month: int = 7,
) -> Dict[str, Any]:
    """Nemotron Call #1: strategy planner."""
    fallback = _fallback_policy(server_workload_pct, ambient_temp_c)
    user_msg = f"""Mevcut tesis durumu:
- Sunucu yükü: %{server_workload_pct}
- Dış sıcaklık: {ambient_temp_c}°C
- Mevcut PUE: {current_pue}
- Inlet sıcaklık: {current_inlet_temp}°C
- Saat: {hour}:00, Ay: {month}

Bu duruma uygun optimizasyon politikasını JSON olarak üret."""

    try:
        policy = _call_nemotron_json(POLICY_SYSTEM_PROMPT, user_msg, max_tokens=1200)
        return _validate_policy_shape(policy, fallback)
    except Exception as exc:
        print(f"[Nemotron policy fallback] {exc}")
        return fallback


def generate_final_decision(
    current: Dict[str, Any], candidates: List[Dict[str, Any]], policy: Dict[str, Any]
) -> Dict[str, Any]:
    """Nemotron Call #2: operations controller."""
    fallback = _fallback_decision(candidates)
    candidates_summary = [
        {
            "rank": candidate["rank"],
            "pue": candidate["pue"],
            "chiller_setpoint_c": candidate["chiller_setpoint_c"],
            "fan_speed_pct": candidate["fan_speed_pct"],
            "inlet_temp_c": candidate["inlet_temp_c"],
            "ashrae_status": candidate["ashrae_status"],
            "risk_level": candidate["risk_level"],
            "monthly_savings_tl": candidate["monthly_savings_tl"],
        }
        for candidate in candidates
    ]

    user_msg = f"""Mevcut durum:
PUE: {current['pue']}, Inlet: {current['inlet_temp_c']}°C, ASHRAE: {current['ashrae_status']}

Optimizasyon stratejisi: {policy.get('strategy', 'balanced')}
Strateji gerekçesi: {policy.get('reason_tr', '')}

Top 3 aday:
{json.dumps(candidates_summary, ensure_ascii=False, indent=2)}

En uygun adayı seç ve operasyon kararını JSON olarak ver."""

    try:
        decision = _call_nemotron_json(DECISION_SYSTEM_PROMPT, user_msg, max_tokens=1500)
        return _validate_decision_shape(decision, candidates, fallback)
    except Exception as exc:
        print(f"[Nemotron decision fallback] {exc}")
        return fallback


def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "hesaplanmadı"
    return f"{value:,.0f} TL".replace(",", ".")


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "belirtilmedi"
    return f"%{value:.0f}"


def normalize_report_input(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Create a stable report payload from optimizer/frontend raw values."""
    current_pue = float(raw["current_pue"])
    optimum_pue = float(raw["optimum_pue"])
    pue_delta = current_pue - optimum_pue
    improvement_pct = (pue_delta / current_pue) * 100 if current_pue else 0.0

    return {
        "scenario_name": raw.get("scenario_name", "Canlı operasyon"),
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


def validate_report_payload(payload: Dict[str, Any]) -> List[str]:
    """Return human-readable validation warnings without blocking the demo."""
    warnings = []
    if not 1.0 <= payload["current_pue"] <= 3.0:
        warnings.append("Mevcut PUE beklenen veri merkezi aralığının dışında.")
    if not 1.0 <= payload["optimum_pue"] <= 3.0:
        warnings.append("Optimum PUE beklenen veri merkezi aralığının dışında.")
    if payload["optimum_pue"] > payload["current_pue"]:
        warnings.append("Optimum PUE mevcut PUE'den yüksek görünüyor.")
    inlet_temp = payload.get("inlet_temp_c")
    if inlet_temp is not None and float(inlet_temp) > 27.0:
        warnings.append("ASHRAE TC 9.9 sunucu giriş sıcaklığı limiti aşılmış olabilir.")
    if payload.get("physics_status") not in {"ok", "warning", "rejected", "not_checked"}:
        warnings.append("Fizik doğrulama durumu tanınmıyor.")
    return warnings


def build_report_prompt(payload: Dict[str, Any], validation_warnings: List[str]) -> str:
    """Turn raw backend metrics into a constrained Nemotron prompt."""
    return f"""
Aşağıdaki ThermaIQ optimizasyon çıktısını tesis müdürüne yönelik 3 paragraflık
Türkçe operasyon raporuna dönüştür.

Kurallar:
- İlk paragraf mevcut durum ve PUE iyileşmesini açıklasın.
- İkinci paragraf chiller/fan ayarlarını ve fizik/ASHRAE doğrulamasını anlatsın.
- Üçüncü paragraf TL tasarruf, CO2 etkisi ve uygulanacak aksiyonu versin.
- Sonunda "Öncelikli aksiyon:" ile tek cümlelik net karar yaz.
- Verilmeyen metrikleri uydurma.

Veri:
- Senaryo: {payload['scenario_name']}
- Mevcut PUE: {payload['current_pue']:.2f}
- Önerilen PUE: {payload['optimum_pue']:.2f}
- PUE iyileşmesi: {payload['improvement_pct']:.1f}%
- Dış sıcaklık: {payload.get('ambient_temp_c', 'belirtilmedi')} C
- Sunucu yükü: {_fmt_pct(payload.get('server_workload_pct'))}
- Inlet sıcaklığı: {payload.get('inlet_temp_c', 'belirtilmedi')} C
- Chiller: {_fmt_pct(payload.get('current_chiller_pct'))} -> {_fmt_pct(payload.get('optimized_chiller_pct'))}
- Fan/AHU: {_fmt_pct(payload.get('current_fan_pct'))} -> {_fmt_pct(payload.get('optimized_fan_pct'))}
- Aylık tasarruf: {_fmt_money(payload.get('monthly_savings_tl'))}
- CO2 etkisi: {payload.get('co2_savings_ton_month', 'hesaplanmadı')} ton/ay
- Fizik doğrulama: {payload.get('physics_status')}
- Fizik notları: {payload.get('physics_notes') or 'yok'}
- Anomali notları: {payload.get('anomalies') or 'yok'}
- Önerilen aksiyonlar: {payload.get('recommended_actions') or 'yok'}
- Veri uyarıları: {validation_warnings or 'yok'}
""".strip()


def build_local_report(payload: Dict[str, Any], validation_warnings: List[str]) -> str:
    """Deterministic fallback used when API key/network is unavailable."""
    pue_sentence = (
        f"{payload['scenario_name']} senaryosunda mevcut PUE {payload['current_pue']:.2f}, "
        f"önerilen çalışma noktasında {payload['optimum_pue']:.2f}. "
        f"Bu, yaklaşık %{payload['improvement_pct']:.1f} iyileşme anlamına geliyor."
    )
    thermal_sentence = (
        f"Dış sıcaklık {payload.get('ambient_temp_c', 'belirtilmedi')} C ve sunucu yükü "
        f"{_fmt_pct(payload.get('server_workload_pct'))}. Chiller ayarı "
        f"{_fmt_pct(payload.get('current_chiller_pct'))} seviyesinden "
        f"{_fmt_pct(payload.get('optimized_chiller_pct'))} seviyesine, fan/AHU ayarı "
        f"{_fmt_pct(payload.get('current_fan_pct'))} seviyesinden "
        f"{_fmt_pct(payload.get('optimized_fan_pct'))} seviyesine çekilebilir."
    )
    savings_sentence = (
        f"Aylık beklenen tasarruf {_fmt_money(payload.get('monthly_savings_tl'))}; "
        f"CO2 etkisi {payload.get('co2_savings_ton_month', 'hesaplanmadı')} ton/ay. "
        f"Fizik doğrulama durumu: {payload.get('physics_status')}."
    )
    warning_text = ""
    if validation_warnings:
        warning_text = " Veri uyarısı: " + " ".join(validation_warnings)

    return (
        f"{pue_sentence}\n\n"
        f"{thermal_sentence} ASHRAE inlet limiti için mevcut inlet sıcaklığı "
        f"{payload.get('inlet_temp_c', 'belirtilmedi')} C olarak izlenmelidir.{warning_text}\n\n"
        f"{savings_sentence}\n\n"
        "Öncelikli aksiyon: Önerilen chiller ve fan setlerini kademeli uygulayın, "
        "ilk 30 dakika inlet sıcaklığı ve PUE trendini canlı takip edin."
    )


def call_nemotron(prompt: str) -> str:
    """Call Nemotron for free-form report text."""
    try:
        return _call_chat(REPORT_SYSTEM_PROMPT, prompt, max_tokens=650, temperature=0.2).strip()
    except requests.RequestException as exc:
        raise NemotronError(str(exc)) from exc


def generate_operational_report(raw_payload: Dict[str, Any], use_mock: bool = False) -> Dict[str, Any]:
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
