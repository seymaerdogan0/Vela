# model.py - XGBoost model training and prediction (Türksat Gölbaşı scale)

import os
import json
from typing import Tuple
import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import shap

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "..", "data", "raw", "cold_source_control_dataset.csv")
MODELS_DIR = os.path.join(BASE_DIR, "..", "models")

FEATURES = [
    "Server_Workload(%)",
    "Ambient_Temperature(°C)",
    "Inlet_Temperature(°C)",
    "Chiller_Usage(%)",
    "AHU_Usage(%)",
    "hour",
    "month",
    "workload_3h_avg",
    "is_free_cooling",
    "temp_delta",
]

FEATURE_MAP = {
    "server_workload":   "Server_Workload(%)",
    "ambient_temp":      "Ambient_Temperature(°C)",
    "inlet_temp":        "Inlet_Temperature(°C)",
    "chiller_usage":     "Chiller_Usage(%)",
    "ahu_usage":         "AHU_Usage(%)",
    "hour":              "hour",
    "month":             "month",
    "workload_3h_avg":   "workload_3h_avg",
    "is_free_cooling":   "is_free_cooling",
    "temp_delta":        "temp_delta",
}


def _load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["Timestamp"])

    # Timestamp features
    df["hour"]        = df["Timestamp"].dt.hour
    df["month"]       = df["Timestamp"].dt.month
    df["day_of_week"] = df["Timestamp"].dt.dayofweek

    # Rolling workload average (3-hour window)
    df["workload_3h_avg"] = (
        df["Server_Workload(%)"].rolling(window=3, min_periods=1).mean()
    )

    # Free-cooling flag (Ankara iklimine göre 12°C eşiği)
    df["is_free_cooling"] = (df["Ambient_Temperature(°C)"] < 12).astype(int)

    # Temperature delta
    df["temp_delta"] = df["Outlet_Temperature(°C)"] - df["Inlet_Temperature(°C)"]

    # Türksat Gölbaşı DC ölçeğine normalize et (21 MW IT kapasitesi)
    df["it_power_kw"]      = df["Server_Workload(%)"] / 100 * 21_000
    raw_cooling            = df["Cooling_Unit_Power_Consumption(kW)"]
    max_raw                = raw_cooling.max()
    # Ham cooling değerini IT gücünün %45'i olacak şekilde ölçekle
    df["cooling_power_kw"] = (raw_cooling / max_raw) * df["it_power_kw"] * 0.45
    df["aux_power_kw"]     = df["it_power_kw"] * 0.08

    df["pue"] = (
        (df["it_power_kw"] + df["cooling_power_kw"] + df["aux_power_kw"])
        / df["it_power_kw"]
    )

    print(f"PUE araligi: {df['pue'].min():.3f} - {df['pue'].max():.3f}, "
          f"ortalama: {df['pue'].mean():.3f}")

    return df


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _build_xgb() -> XGBRegressor:
    return XGBRegressor(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        early_stopping_rounds=20,
        eval_metric="rmse",
        random_state=42,
    )


def train_model() -> dict:
    df = _load_data()

    X       = df[FEATURES]
    y_pue   = df["pue"]
    y_inlet = df["Inlet_Temperature(°C)"]

    X_train, X_test, yp_train, yp_test, yi_train, yi_test = train_test_split(
        X, y_pue, y_inlet, test_size=0.2, random_state=42
    )

    # --- Model A: PUE ---
    model_pue = _build_xgb()
    model_pue.fit(
        X_train, yp_train,
        eval_set=[(X_test, yp_test)],
        verbose=False,
    )

    yp_pred = model_pue.predict(X_test)
    pue_metrics = {
        "r2":   round(r2_score(yp_test, yp_pred), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(yp_test, yp_pred))), 4),
        "mape": round(_mape(yp_test.values, yp_pred), 4),
    }
    print(f"[PUE model]   R2={pue_metrics['r2']}  RMSE={pue_metrics['rmse']}  MAPE={pue_metrics['mape']}%")

    # --- Model B: Inlet Temperature ---
    model_inlet = _build_xgb()
    model_inlet.fit(
        X_train, yi_train,
        eval_set=[(X_test, yi_test)],
        verbose=False,
    )

    yi_pred = model_inlet.predict(X_test)
    inlet_metrics = {
        "r2":   round(r2_score(yi_test, yi_pred), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(yi_test, yi_pred))), 4),
        "mape": round(_mape(yi_test.values, yi_pred), 4),
    }
    print(f"[Inlet model] R2={inlet_metrics['r2']}  RMSE={inlet_metrics['rmse']}  MAPE={inlet_metrics['mape']}%")

    # --- SHAP feature importance (PUE modeli) ---
    explainer   = shap.TreeExplainer(model_pue)
    shap_values = explainer.shap_values(X_test)
    shap_importance = {
        feat: round(float(np.abs(shap_values[:, i]).mean()), 6)
        for i, feat in enumerate(FEATURES)
    }
    sorted_shap = dict(sorted(shap_importance.items(), key=lambda x: x[1], reverse=True))
    print(f"[SHAP]        {json.dumps(sorted_shap, indent=2)}")

    # --- Modelleri kaydet ---
    os.makedirs(MODELS_DIR, exist_ok=True)
    model_pue.save_model(os.path.join(MODELS_DIR, "xgb_pue.json"))
    model_inlet.save_model(os.path.join(MODELS_DIR, "xgb_inlet.json"))
    print("[Saved]       models/xgb_pue.json  models/xgb_inlet.json")

    return {
        "pue_metrics":   pue_metrics,
        "inlet_metrics": inlet_metrics,
        "shap":          sorted_shap,
    }


def load_models() -> Tuple[XGBRegressor, XGBRegressor]:
    model_pue = XGBRegressor()
    model_pue.load_model(os.path.join(MODELS_DIR, "xgb_pue.json"))

    model_inlet = XGBRegressor()
    model_inlet.load_model(os.path.join(MODELS_DIR, "xgb_inlet.json"))

    return model_pue, model_inlet


def predict(features_dict: dict) -> dict:
    X = pd.DataFrame([{FEATURE_MAP[k]: v for k, v in features_dict.items()}])[FEATURES]

    model_pue, model_inlet = load_models()

    pue        = float(model_pue.predict(X)[0])
    inlet_temp = float(model_inlet.predict(X)[0])

    it_power_kw      = features_dict["server_workload"] / 100 * 21_000
    cooling_power_kw = (pue - 1.08) * it_power_kw  # aux=0.08 çıkarınca cooling kalır

    return {
        "pue":              round(pue, 4),
        "cooling_power_kw": round(cooling_power_kw, 2),
        "inlet_temp":       round(inlet_temp, 4),
        "it_power_kw":      round(it_power_kw, 2),
        "safety_ok":        inlet_temp < 27.0,
    }


if __name__ == "__main__":
    metrics = train_model()
    print("\n--- Metrics ---")
    print(metrics)

    test_input = {
        "server_workload": 85.0,
        "ambient_temp":    35.0,
        "inlet_temp":      22.0,
        "chiller_usage":   78.0,
        "ahu_usage":       82.0,
        "hour":            14,
        "month":           7,
        "workload_3h_avg": 80.0,
        "is_free_cooling": 0,
        "temp_delta":      10.0,
    }
    print("\n--- Sample Prediction ---")
    print(predict(test_input))
