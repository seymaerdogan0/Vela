# model.py - XGBoost model training and prediction

import os
import json
from typing import Tuple
import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import shap

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "cold_source_control_dataset.csv")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

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

    # PUE derivation
    it_power = df["Server_Workload(%)"] / 100 * 21_000
    cooling_power = df["Cooling_Unit_Power_Consumption(kW)"]
    aux_power = it_power * 0.08
    df["pue"] = (it_power + cooling_power + aux_power) / it_power

    # Timestamp features
    df["hour"]        = df["Timestamp"].dt.hour
    df["month"]       = df["Timestamp"].dt.month
    df["day_of_week"] = df["Timestamp"].dt.dayofweek

    # Rolling workload average (3-hour window, assumes 1 row = 1 hour)
    df["workload_3h_avg"] = (
        df["Server_Workload(%)"].rolling(window=3, min_periods=1).mean()
    )

    # Free-cooling flag
    df["is_free_cooling"] = (df["Ambient_Temperature(°C)"] < 12).astype(int)

    # Temperature delta
    df["temp_delta"] = df["Outlet_Temperature(°C)"] - df["Inlet_Temperature(°C)"]

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

    X = df[FEATURES]
    y_pue   = df["pue"]
    y_inlet = df["Inlet_Temperature(°C)"]

    X_train, X_test, yp_train, yp_test, yi_train, yi_test = train_test_split(
        X, y_pue, y_inlet, test_size=0.2, random_state=42
    )

    # --- PUE model ---
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
    print(f"[PUE model]   R²={pue_metrics['r2']}  RMSE={pue_metrics['rmse']}  MAPE={pue_metrics['mape']}%")

    # --- Inlet temperature model ---
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
    print(f"[Inlet model] R²={inlet_metrics['r2']}  RMSE={inlet_metrics['rmse']}  MAPE={inlet_metrics['mape']}%")

    # --- SHAP feature importance for PUE model ---
    explainer   = shap.TreeExplainer(model_pue)
    shap_values = explainer.shap_values(X_test)
    shap_importance = {
        feat: round(float(np.abs(shap_values[:, i]).mean()), 6)
        for i, feat in enumerate(FEATURES)
    }
    print(f"[SHAP]        {json.dumps(shap_importance, indent=2)}")

    # --- Persist models ---
    os.makedirs(MODELS_DIR, exist_ok=True)
    model_pue.save_model(os.path.join(MODELS_DIR, "xgb_pue.json"))
    model_inlet.save_model(os.path.join(MODELS_DIR, "xgb_inlet.json"))
    print(f"[Saved]       models/xgb_pue.json  models/xgb_inlet.json")

    return {
        "pue_metrics":   pue_metrics,
        "inlet_metrics": inlet_metrics,
        "shap":          shap_importance,
    }


def load_models() -> Tuple[XGBRegressor, XGBRegressor]:
    model_pue = XGBRegressor()
    model_pue.load_model(os.path.join(MODELS_DIR, "xgb_pue.json"))

    model_inlet = XGBRegressor()
    model_inlet.load_model(os.path.join(MODELS_DIR, "xgb_inlet.json"))

    return model_pue, model_inlet


def predict(features_dict: dict) -> dict:
    row = {FEATURE_MAP[k]: v for k, v in features_dict.items()}
    X = pd.DataFrame([row])[FEATURES]

    model_pue, model_inlet = load_models()

    pue_pred   = float(model_pue.predict(X)[0])
    inlet_pred = float(model_inlet.predict(X)[0])

    return {
        "predicted_pue":        round(pue_pred, 4),
        "predicted_inlet_temp": round(inlet_pred, 4),
    }


if __name__ == "__main__":
    metrics = train_model()
    print(metrics)
