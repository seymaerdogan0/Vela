# evaluate_optimization.py - Batch evaluation for ThermaIQ optimization impact

import argparse
import os
from statistics import mean
from typing import Optional

import pandas as pd

from optimizer import optimize


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(
    BASE_DIR, "..", "data", "processed", "golbasi_dc_dataset.csv"
)


def _policy_for_row(row) -> dict:
    """Local proxy for Nemotron strategy classes during batch evaluation."""
    workload = float(row["server_workload_pct"])
    ambient = float(row["ambient_temp_c"])
    hour = int(row.get("hour", 12))

    if ambient < 8:
        return {
            "strategy": "free_cooling",
            "objective_weights": {"pue": 0.75, "thermal_risk": 0.15, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [10, 16], "fan_speed_pct": [30, 70]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 25.0},
            "reason_tr": "Soğuk hava nedeniyle free cooling ve tasarruf önceliklendirildi.",
            "source": "batch_policy",
        }

    if workload >= 90 or hour in (10, 11, 12, 13, 14, 15, 16, 17):
        return {
            "strategy": "peak_load",
            "objective_weights": {"pue": 0.50, "thermal_risk": 0.40, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [6, 12], "fan_speed_pct": [70, 95]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 26.0},
            "reason_tr": "Yoğun saat/yük nedeniyle termal güvenlik ağırlıklı optimizasyon.",
            "source": "batch_policy",
        }

    if workload < 45 and ambient < 18:
        return {
            "strategy": "aggressive_savings",
            "objective_weights": {"pue": 0.80, "thermal_risk": 0.10, "setpoint_change": 0.10},
            "search_space": {"chiller_setpoint_c": [9, 16], "fan_speed_pct": [30, 70]},
            "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 26.2},
            "reason_tr": "Düşük yük ve serin hava nedeniyle agresif tasarruf güvenli.",
            "source": "batch_policy",
        }

    return {
        "strategy": "balanced",
        "objective_weights": {"pue": 0.65, "thermal_risk": 0.25, "setpoint_change": 0.10},
        "search_space": {"chiller_setpoint_c": [7, 14], "fan_speed_pct": [50, 90]},
        "risk_policy": {"max_inlet_temp_c": 27, "preferred_inlet_temp_c": 26.0},
        "reason_tr": "Normal koşullarda PUE ve termal risk dengelendi.",
        "source": "batch_policy",
    }


def _sample_dataframe(df: pd.DataFrame, sample_size: int, months: Optional[list]) -> pd.DataFrame:
    if months:
        df = df[df["month"].isin(months)].copy()
    if sample_size <= 0 or sample_size >= len(df):
        return df.reset_index(drop=True)
    step = max(1, len(df) // sample_size)
    sampled = df.iloc[::step].head(sample_size).copy()
    return sampled.reset_index(drop=True)


def evaluate(
    dataset_path: str = DEFAULT_DATASET,
    sample_size: int = 120,
    n_trials: int = 40,
    months: Optional[list] = None,
) -> dict:
    df = pd.read_csv(dataset_path)
    sample = _sample_dataframe(df, sample_size=sample_size, months=months)

    rows = []
    for _, row in sample.iterrows():
        policy = _policy_for_row(row)
        result = optimize(
            server_workload_pct=float(row["server_workload_pct"]),
            ambient_temp_c=float(row["ambient_temp_c"]),
            policy=policy,
            hour=int(row["hour"]),
            month=int(row["month"]),
            n_trials=n_trials,
        )
        best = result["candidates"][0]
        current = result["current"]
        saved_kw = max(0.0, (current["pue"] - best["pue"]) * (float(row["server_workload_pct"]) / 100 * 21000))

        rows.append({
            "timestamp": row.get("timestamp"),
            "month": int(row["month"]),
            "ambient_temp_c": float(row["ambient_temp_c"]),
            "server_workload_pct": float(row["server_workload_pct"]),
            "strategy": policy["strategy"],
            "current_pue": current["pue"],
            "optimized_pue": best["pue"],
            "pue_improvement": current["pue"] - best["pue"],
            "pue_improvement_pct": (current["pue"] - best["pue"]) / current["pue"] * 100,
            "saved_kw": saved_kw,
            "monthly_savings_tl": best["monthly_savings_tl"],
            "risk_level": best["risk_level"],
            "ashrae_status": best["ashrae_status"],
            "chiller_setpoint_c": best["chiller_setpoint_c"],
            "fan_speed_pct": best["fan_speed_pct"],
            "inlet_temp_c": best["inlet_temp_c"],
        })

    out = pd.DataFrame(rows)
    summary = {
        "dataset_path": os.path.abspath(dataset_path),
        "rows_evaluated": int(len(out)),
        "months": sorted(out["month"].unique().tolist()) if len(out) else [],
        "n_trials_per_row": n_trials,
        "avg_current_pue": round(float(out["current_pue"].mean()), 4),
        "avg_optimized_pue": round(float(out["optimized_pue"].mean()), 4),
        "avg_pue_improvement": round(float(out["pue_improvement"].mean()), 4),
        "avg_pue_improvement_pct": round(float(out["pue_improvement_pct"].mean()), 2),
        "avg_saved_kw": round(float(out["saved_kw"].mean()), 1),
        "annualized_savings_tl": round(float(out["saved_kw"].mean()) * 8760 * 3.2, 0),
        "annualized_co2_tons": round(float(out["saved_kw"].mean()) * 8760 * 0.45 / 1000, 1),
        "risk_distribution": out["risk_level"].value_counts().to_dict(),
        "strategy_distribution": out["strategy"].value_counts().to_dict(),
        "ashrae_distribution": out["ashrae_status"].value_counts().to_dict(),
    }
    return {"summary": summary, "rows": out}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--sample-size", type=int, default=120)
    parser.add_argument("--n-trials", type=int, default=40)
    parser.add_argument("--months", default="", help="Comma-separated month numbers, e.g. 1,2,7")
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "..", "data", "processed", "optimization_eval.csv"))
    args = parser.parse_args()

    months = [int(m.strip()) for m in args.months.split(",") if m.strip()] or None
    result = evaluate(args.dataset, args.sample_size, args.n_trials, months)
    result["rows"].to_csv(args.out, index=False)

    print("=== THERMAIQ OPTIMIZATION EVALUATION ===")
    for key, value in result["summary"].items():
        print(f"{key}: {value}")
    print(f"detail_csv: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
