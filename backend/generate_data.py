# generate_data.py - Synthetic Türksat Gölbaşı DC dataset generator

import os
import json
import pandas as pd
import numpy as np


_BASE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_OUT = os.path.join(_BASE, "..", "data", "processed", "golbasi_dc_dataset.csv")


def generate_dc_dataset(output_path=_DEFAULT_OUT):
    np.random.seed(42)
    timestamps = pd.date_range("2025-01-01", periods=8760, freq="h")

    # Ankara aylık sıcaklık ortalamaları (MGM 2024)
    monthly_avg = {1: -0.3, 2: 1.6, 3: 6.3, 4: 11.7, 5: 16.6,
                   6: 20.7, 7: 24.0, 8: 23.7, 9: 18.6, 10: 12.7,
                   11: 6.3, 12: 1.9}

    rows = []
    for ts in timestamps:
        m = ts.month
        h = ts.hour

        # Dış sıcaklık (Ankara profili)
        base_temp   = monthly_avg[m]
        daily_swing = 8 * np.sin((h - 6) * np.pi / 12)
        ambient     = base_temp + daily_swing + np.random.normal(0, 1.5)

        # Sunucu yükü (e-Devlet profili)
        if 2 <= h <= 6:
            base_load = np.random.uniform(15, 30)
        elif 9 <= h <= 18:
            base_load = np.random.uniform(55, 80)
        else:
            base_load = np.random.uniform(35, 55)

        # Türkiye e-Devlet spike takvimi
        spike = 1.0
        if m == 7 and ts.day in [12, 13] and 10 <= h <= 16:
            spike = np.random.uniform(1.8, 2.5)   # YKS sonucu
        elif m == 3 and ts.day in [25, 26] and 9 <= h <= 14:
            spike = np.random.uniform(1.5, 2.0)   # Vergi beyanname
        elif ts.day == 1 and 9 <= h <= 12:
            spike = np.random.uniform(1.3, 1.6)   # Aybaşı SGK

        server_workload = min(95, base_load * spike + np.random.normal(0, 2))

        # IT gücü (21 MW kapasite)
        it_power_kw = server_workload / 100 * 21_000

        # UCI AT-PE korelasyonu transfer: AT arttıkça soğutma maliyeti artar
        uci_efficiency_factor = 1 - (ambient - 19.65) * 0.00485

        # Chiller COP (Carnot bazlı, UCI faktörüyle kalibre)
        T_cold    = 12 + 273.15
        T_hot     = max(ambient + 10, 25) + 273.15
        cop_carnot = T_cold / (T_hot - T_cold)
        cop_real   = max(1.5, cop_carnot * 0.35 * uci_efficiency_factor)

        # Free cooling (Ankara kışı avantajı)
        free_cooling = 0.0
        if ambient < 8:
            free_cooling = min(0.65, (8 - ambient) / 15)

        # Soğutma gücü
        cooling_load   = it_power_kw * 0.97
        chiller_power  = cooling_load * (1 - free_cooling) / cop_real

        # Fan gücü (kübik yasa)
        fan_speed = min(90, server_workload * 0.85 + 10)
        fan_power = it_power_kw * 0.05 * (fan_speed / 100) ** 3

        # Aux güç
        aux_power = it_power_kw * 0.08

        # PUE
        total_power = it_power_kw + chiller_power + fan_power + aux_power
        pue         = total_power / it_power_kw

        # EPİAŞ ortalaması (TL/kWh) — mevsimsel
        electricity_price = 3.2 + (0.3 if 7 <= m <= 9 else 0)
        hourly_cost       = total_power * electricity_price

        # CO2
        co2_kg = total_power * 0.45

        # --- Yeni kolonlar ---
        inlet_temp_c = round(
            18 + (server_workload / 100) * 8 + (ambient - 20) * 0.1 - free_cooling * 2,
            2
        )

        if inlet_temp_c < 21:
            ashrae_status = "A1-Optimal"
        elif inlet_temp_c < 24:
            ashrae_status = "A2-Recommended"
        elif inlet_temp_c < 27:
            ashrae_status = "A3-Allowable"
        else:
            ashrae_status = "VIOLATION"

        if ambient < 8:
            chiller_setpoint_c = 14
        elif ambient <= 20:
            chiller_setpoint_c = 12
        else:
            chiller_setpoint_c = 10

        fan_speed_pct = round(min(90, server_workload * 0.85 + 10), 1)

        if ambient < 8:
            cooling_mode = "free_cooling"
        elif ambient <= 18:
            cooling_mode = "mixed"
        else:
            cooling_mode = "mechanical"

        baseline_pue   = round(pue * np.random.uniform(1.15, 1.25), 4)
        optimized_pue  = round(pue, 4)
        pue_improvement_pct = round(
            (baseline_pue - optimized_pue) / baseline_pue * 100, 2
        )

        saved_kw = (baseline_pue - optimized_pue) * it_power_kw
        monthly_savings_tl = round(saved_kw * 720 * electricity_price, 2)

        bms_command_payload = json.dumps({
            "device": "CHILLER-01",
            "chilled_water_setpoint_c": chiller_setpoint_c,
            "fan_speed_pct": fan_speed_pct,
            "protocol": "BACnet/IP",
            "approval_required": True,
        })

        rows.append({
            "timestamp":                ts,
            "ambient_temp_c":           round(ambient, 2),
            "server_workload_pct":      round(server_workload, 2),
            "it_power_kw":              round(it_power_kw, 1),
            "chiller_power_kw":         round(chiller_power, 1),
            "fan_power_kw":             round(fan_power, 1),
            "aux_power_kw":             round(aux_power, 1),
            "total_power_kw":           round(total_power, 1),
            "pue":                      round(pue, 4),
            "cop_real":                 round(cop_real, 4),
            "free_cooling_active":      1 if free_cooling > 0 else 0,
            "traffic_spike":            round(spike, 3),
            "electricity_price_tl_kwh": electricity_price,
            "hourly_cost_tl":           round(hourly_cost, 2),
            "co2_kg_per_hour":          round(co2_kg, 2),
            "hour":                     h,
            "month":                    m,
            "inlet_temp_c":             inlet_temp_c,
            "ashrae_status":            ashrae_status,
            "chiller_setpoint_c":       chiller_setpoint_c,
            "fan_speed_pct":            fan_speed_pct,
            "cooling_mode":             cooling_mode,
            "baseline_pue":             baseline_pue,
            "optimized_pue":            optimized_pue,
            "pue_improvement_pct":      pue_improvement_pct,
            "monthly_savings_tl":       monthly_savings_tl,
            "bms_command_payload":      bms_command_payload,
        })

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)

    print("=== VERİ SETİ ÖZETİ ===")
    print(f"Toplam satir:          {len(df)}")
    print(f"optimized_pue:         min={df.optimized_pue.min():.3f}  max={df.optimized_pue.max():.3f}  mean={df.optimized_pue.mean():.3f}")
    print(f"baseline_pue:          min={df.baseline_pue.min():.3f}  max={df.baseline_pue.max():.3f}  mean={df.baseline_pue.mean():.3f}")
    print(f"Ort. monthly_savings:  {df.monthly_savings_tl.mean():,.0f} TL")
    print(f"\ncooling_mode dagilimi:\n{df.cooling_mode.value_counts().to_string()}")
    print(f"\nashrae_status dagilimi:\n{df.ashrae_status.value_counts().to_string()}")
    print(f"\ninlet_temp_c:          min={df.inlet_temp_c.min():.2f}  max={df.inlet_temp_c.max():.2f}  mean={df.inlet_temp_c.mean():.2f}")
    print(f"AT-PUE korelasyonu:    {df.ambient_temp_c.corr(df.optimized_pue):.4f}")

    return df


if __name__ == "__main__":
    generate_dc_dataset()
