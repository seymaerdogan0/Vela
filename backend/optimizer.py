# optimizer.py - LLM-guided constrained optimization over the physics twin

from copy import deepcopy
from typing import Optional

import optuna

from physics import calculate_pue, validate_recommendation

optuna.logging.set_verbosity(optuna.logging.WARNING)


DEFAULT_POLICY = {
    "strategy": "balanced",
    "objective_weights": {
        "pue": 0.60,
        "thermal_risk": 0.25,
        "setpoint_change": 0.15,
    },
    "search_space": {
        "chiller_setpoint_c": [6, 16],
        "fan_speed_pct": [30, 90],
    },
    "risk_policy": {
        "max_inlet_temp_c": 27,
        "preferred_inlet_temp_c": 25.5,
    },
}

BASELINE_CHILLER_SETPOINT_C = 6
BASELINE_FAN_SPEED_PCT = 90


def _as_float(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp_range(values, default, low: float, high: float) -> list:
    """Clamp a two-value range and recover if an LLM returns bad or reversed bounds."""
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        values = default

    start = _as_float(values[0], default[0])
    end = _as_float(values[1], default[1])
    start = max(low, min(high, start))
    end = max(low, min(high, end))

    if start > end:
        return list(default)
    if start == end:
        end = min(high, start + 0.1)
    return [start, end]


def _clamp_policy(policy: Optional[dict]) -> dict:
    """
    Clamp LLM output to physical limits.
    Guardrail: fixes reversed ranges, extreme values, missing weights, and unsafe limits.
    """
    safe_policy = deepcopy(DEFAULT_POLICY)
    if policy:
        for key, value in policy.items():
            if isinstance(value, dict) and isinstance(safe_policy.get(key), dict):
                safe_policy[key].update(value)
            else:
                safe_policy[key] = value

    sp = safe_policy.get("search_space", {})
    sp["chiller_setpoint_c"] = _clamp_range(
        sp.get("chiller_setpoint_c"),
        DEFAULT_POLICY["search_space"]["chiller_setpoint_c"],
        6,
        16,
    )
    sp["fan_speed_pct"] = _clamp_range(
        sp.get("fan_speed_pct"),
        [30, 95],
        30,
        95,
    )

    weights = safe_policy.get("objective_weights", {})
    normalized_weights = {}
    for key in ("pue", "thermal_risk", "setpoint_change"):
        normalized_weights[key] = max(0.0, _as_float(weights.get(key), 0.0))
    total = sum(normalized_weights.values())
    if total <= 0:
        normalized_weights = deepcopy(DEFAULT_POLICY["objective_weights"])
    else:
        normalized_weights = {
            key: value / total for key, value in normalized_weights.items()
        }

    risk_policy = safe_policy.get("risk_policy", {})
    max_inlet = _as_float(risk_policy.get("max_inlet_temp_c"), 27)
    preferred_inlet = _as_float(risk_policy.get("preferred_inlet_temp_c"), 24)
    risk_policy["max_inlet_temp_c"] = max(24, min(27, max_inlet))
    risk_policy["preferred_inlet_temp_c"] = max(20, min(26.5, preferred_inlet))
    if risk_policy["preferred_inlet_temp_c"] >= risk_policy["max_inlet_temp_c"]:
        risk_policy["preferred_inlet_temp_c"] = max(
            20, risk_policy["max_inlet_temp_c"] - 1
        )

    safe_policy["search_space"] = sp
    safe_policy["objective_weights"] = normalized_weights
    safe_policy["risk_policy"] = risk_policy
    return safe_policy


def _risk_level(inlet_temp_c: float) -> str:
    if inlet_temp_c > 26.5:
        return "high"
    if inlet_temp_c > 24:
        return "medium"
    return "low"


def _build_candidate(rank: int, score: float, params: dict, current: dict, scenario: dict) -> dict:
    result = calculate_pue(
        scenario["server_workload_pct"],
        scenario["ambient_temp_c"],
        chiller_setpoint_c=params["chiller_setpoint_c"],
        fan_speed_pct=params["fan_speed_pct"],
        it_capacity_mw=scenario["it_capacity_mw"],
    )
    validation = validate_recommendation(current, result)
    saved_kw = max(0, (current["pue"] - result["pue"]) * result["it_power_kw"])

    return {
        "rank": rank,
        "score": round(score, 4),
        "pue": result["pue"],
        "chiller_setpoint_c": round(params["chiller_setpoint_c"], 2),
        "fan_speed_pct": round(params["fan_speed_pct"], 2),
        "inlet_temp_c": result["inlet_temp_c"],
        "ashrae_status": result["ashrae_status"],
        "cop_real": result["cop_real"],
        "safety_ok": result["safety_ok"],
        "risk_level": _risk_level(result["inlet_temp_c"]),
        "monthly_savings_tl": round(saved_kw * 720 * 3.2, 0),
        "yearly_savings_tl": round(saved_kw * 8760 * 3.2, 0),
        "co2_tons_year": round(saved_kw * 8760 * 0.45 / 1000, 1),
        "bms_command": result["bms_command"],
        "validation": validation,
    }


def optimize(
    server_workload_pct: float,
    ambient_temp_c: float,
    policy: Optional[dict] = None,
    hour: int = 12,
    month: int = 7,
    it_capacity_mw: float = 21,
    n_trials: int = 100,
) -> dict:
    """
    Policy-guided Optuna search.
    Nemotron provides policy; Optuna searches setpoints against physics.py and returns top 3 candidates.
    """
    policy = _clamp_policy(policy)
    search_space = policy["search_space"]
    weights = policy["objective_weights"]
    risk = policy["risk_policy"]

    scenario = {
        "server_workload_pct": server_workload_pct,
        "ambient_temp_c": ambient_temp_c,
        "hour": hour,
        "month": month,
        "it_capacity_mw": it_capacity_mw,
    }

    current = calculate_pue(
        server_workload_pct,
        ambient_temp_c,
        chiller_setpoint_c=BASELINE_CHILLER_SETPOINT_C,
        fan_speed_pct=BASELINE_FAN_SPEED_PCT,
        it_capacity_mw=it_capacity_mw,
    )

    pue_min, pue_max = 1.10, 1.80

    def objective(trial):
        chiller_sp = trial.suggest_float(
            "chiller_setpoint_c",
            search_space["chiller_setpoint_c"][0],
            search_space["chiller_setpoint_c"][1],
        )
        fan_sp = trial.suggest_float(
            "fan_speed_pct",
            search_space["fan_speed_pct"][0],
            search_space["fan_speed_pct"][1],
        )

        result = calculate_pue(
            server_workload_pct,
            ambient_temp_c,
            chiller_setpoint_c=chiller_sp,
            fan_speed_pct=fan_sp,
            it_capacity_mw=it_capacity_mw,
        )

        if result["inlet_temp_c"] > risk["max_inlet_temp_c"]:
            return 10.0
        if result["cop_real"] < 1.5:
            return 10.0
        if result["pue"] >= current["pue"]:
            return 10.0

        normalized_pue = (result["pue"] - pue_min) / (pue_max - pue_min)
        normalized_pue = max(0, min(1, normalized_pue))

        thermal_excess = max(
            0, result["inlet_temp_c"] - risk["preferred_inlet_temp_c"]
        )
        thermal_range = risk["max_inlet_temp_c"] - risk["preferred_inlet_temp_c"]
        thermal_risk = min(1, thermal_excess / max(0.1, thermal_range))

        setpoint_change = (
            abs(chiller_sp - BASELINE_CHILLER_SETPOINT_C) / 10
            + abs(fan_sp - BASELINE_FAN_SPEED_PCT) / 65
        )
        setpoint_change = min(1.0, setpoint_change)

        return (
            weights.get("pue", 0.5) * normalized_pue
            + weights.get("thermal_risk", 0.35) * thermal_risk
            + weights.get("setpoint_change", 0.15) * setpoint_change
        )

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    valid_trials = [t for t in study.trials if t.value is not None and t.value < 10.0]
    valid_trials.sort(key=lambda t: t.value)

    candidates = []
    for rank, trial in enumerate(valid_trials[:3], 1):
        candidates.append(
            _build_candidate(rank, trial.value, trial.params, current, scenario)
        )

    if not candidates:
        fallback_params = {"chiller_setpoint_c": 7, "fan_speed_pct": 85}
        fallback = _build_candidate(1, 9.999, fallback_params, current, scenario)
        fallback["validation"]["issues"].append(
            "Optuna güvenli iyileştirme bulamadı; fallback güvenli operasyon önerildi."
        )
        candidates = [fallback]

    return {
        "current": {
            "pue": current["pue"],
            "chiller_setpoint_c": BASELINE_CHILLER_SETPOINT_C,
            "fan_speed_pct": BASELINE_FAN_SPEED_PCT,
            "inlet_temp_c": current["inlet_temp_c"],
            "ashrae_status": current["ashrae_status"],
            "hourly_cost_tl": current["hourly_cost_tl"],
            "cop_real": current["cop_real"],
        },
        "policy_used": policy,
        "candidates": candidates,
        "meta": {
            "n_trials": n_trials,
            "valid_trials": len(valid_trials),
            "rejected_trials": n_trials - len(valid_trials),
            "server_workload_pct": server_workload_pct,
            "ambient_temp_c": ambient_temp_c,
            "hour": hour,
            "month": month,
        },
    }


if __name__ == "__main__":
    print("=" * 60)
    print("DEFAULT POLICY - YAZ OGLE (35C, %85 yuk)")
    print("=" * 60)
    r1 = optimize(85, 35)
    print(f"Mevcut PUE: {r1['current']['pue']}, Inlet: {r1['current']['inlet_temp_c']}C")
    print(f"Toplam {r1['meta']['n_trials']} deneme, {r1['meta']['valid_trials']} gecerli\n")
    for c in r1["candidates"]:
        print(
            f"Rank {c['rank']}: PUE={c['pue']}, "
            f"Chiller={c['chiller_setpoint_c']}C, "
            f"Fan=%{c['fan_speed_pct']}, "
            f"Inlet={c['inlet_temp_c']}C, "
            f"Risk={c['risk_level']}, "
            f"Aylik={c['monthly_savings_tl']:,.0f} TL"
        )

    print("\n" + "=" * 60)
    print("SAFETY-FIRST POLICY - YAZ OGLE")
    print("=" * 60)
    safety_policy = {
        "strategy": "safety_first",
        "objective_weights": {"pue": 0.40, "thermal_risk": 0.50, "setpoint_change": 0.10},
        "search_space": {"chiller_setpoint_c": [6, 12], "fan_speed_pct": [60, 90]},
        "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 23},
    }
    r2 = optimize(85, 35, policy=safety_policy)
    for c in r2["candidates"]:
        print(f"Rank {c['rank']}: PUE={c['pue']}, Inlet={c['inlet_temp_c']}C, Risk={c['risk_level']}")

    print("\n" + "=" * 60)
    print("AGGRESSIVE SAVINGS POLICY - KIS GECE")
    print("=" * 60)
    aggressive_policy = {
        "strategy": "aggressive_savings",
        "objective_weights": {"pue": 0.75, "thermal_risk": 0.15, "setpoint_change": 0.10},
        "search_space": {"chiller_setpoint_c": [10, 16], "fan_speed_pct": [30, 65]},
        "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 25},
    }
    r3 = optimize(45, -2, policy=aggressive_policy)
    for c in r3["candidates"]:
        print(f"Rank {c['rank']}: PUE={c['pue']}, Inlet={c['inlet_temp_c']}C")
