# physics.py - Physics-based constraints and thermodynamic calculations

import json


def calculate_cop(
    ambient_temp_c: float,
    chiller_setpoint_c: float = 7,
    part_load_ratio: float = 1.0,
) -> float:
    """
    AHRI 550/590 rated conditions + ASHRAE 90.1 part-load EIR curve.

    Bilimsel referanslar:
    - AHRI 550/590: Rated COP at 7°C leaving / 12°C entering chilled water
    - ASHRAE 90.4-2019: Chiller setpoint rule (+1°C = -1.4% energy)
    - ASHRAE 90.1 EIR-PLR curve: EnergyPlus default quadratic
    - UCI CCPP: AT-PE correlation r=-0.948
    """
    # AHRI 550/590 rated COP for water-cooled centrifugal chiller
    rated_cop = 6.1

    # AHRI rated conditions
    rated_t_cold_k = 7 + 273.15
    rated_t_hot_k  = 35 + 273.15
    rated_carnot   = rated_t_cold_k / (rated_t_hot_k - rated_t_cold_k)

    # Actual Carnot at operating conditions
    T_cold_k  = chiller_setpoint_c + 273.15
    T_hot_k   = max(ambient_temp_c + 10, 25) + 273.15
    cop_carnot = T_cold_k / (T_hot_k - T_cold_k)

    # Normalized temperature lift factor
    temp_lift_factor = cop_carnot / rated_carnot
    temp_lift_factor = max(0.65, min(1.20, temp_lift_factor))

    # ASHRAE 90.4: setpoint +1°C -> -1.4% energy -> +1.4% COP
    setpoint_adjustment = 1 + (chiller_setpoint_c - 7) * 0.014

    # ASHRAE 90.1 EIR-PLR curve (Electric Input Ratio as function of PLR)
    # EIR_PLR is in denominator: lower PLR -> higher EIR -> lower COP
    eir_plr = (
        0.17149273
        + 0.58820208 * part_load_ratio
        + 0.23737257 * part_load_ratio ** 2
    )
    eir_plr = max(0.55, min(1.25, eir_plr))

    # UCI CCPP ambient correlation
    uci_factor = 1 - (ambient_temp_c - 19.65) * 0.00485

    # Final COP (EIR_PLR in denominator)
    cop_real = (
        rated_cop
        * temp_lift_factor
        * setpoint_adjustment
        * uci_factor
        / eir_plr
    )

    return max(1.5, min(cop_real, 7.0))


def calculate_free_cooling(ambient_temp_c: float) -> float:
    """Ankara kışı free cooling faktörü."""
    if ambient_temp_c < 8:
        return min(0.65, (8 - ambient_temp_c) / 15)
    return 0.0


def calculate_fan_power(it_power_kw: float, fan_speed_pct: float) -> float:
    """Fan affinity law - kübik yasa."""
    return it_power_kw * 0.05 * (fan_speed_pct / 100) ** 3


def calculate_inlet_temp(
    server_workload_pct: float,
    ambient_temp_c: float,
    free_cooling_factor: float = 0.0,
    chiller_setpoint_c: float = 7,
    fan_speed_pct: float = 65,
) -> float:
    """
    Sunucu giriş (inlet) sıcaklığı.
    Setpoint, fan hızı ve recirculation risk faktörü dahil.
    Referans: ASHRAE TC 9.9 thermal envelope.
    """
    base = (
        18
        + (server_workload_pct / 100) * 8
        + (ambient_temp_c - 20) * 0.1
        - free_cooling_factor * 2
    )
    # Soğuk su setpoint'i yükseldikçe supply air/inlet sıcaklığı artar.
    setpoint_effect = (chiller_setpoint_c - 7) * 0.28
    # Fan hızı arttıkça hot-aisle recirculation azalır.
    fan_effect = -(fan_speed_pct - 65) * 0.035
    # Yüksek yükte rack recirculation riski artar.
    recirculation_risk = max(0, server_workload_pct - 80) * 0.03

    return base + setpoint_effect + fan_effect + recirculation_risk


def check_ashrae(inlet_temp_c: float) -> str:
    """ASHRAE TC 9.9 önerilen/izin verilen sıcaklık bandı sınıflandırması."""
    if inlet_temp_c < 21:
        return "Optimal"
    elif inlet_temp_c < 24:
        return "ASHRAE-Recommended"
    elif inlet_temp_c < 27:
        return "ASHRAE-Allowable"
    return "VIOLATION"


def calculate_pue(
    server_workload_pct: float,
    ambient_temp_c: float,
    chiller_setpoint_c: float = 7,
    fan_speed_pct: float = 65,
    it_capacity_mw: float = 21,
) -> dict:
    """
    Ana fizik motoru. PUE ve tüm türev değerleri hesaplar.

    Bilimsel referanslar:
    - The Green Grid / ISO-IEC 30134-2: PUE metodolojisi
    - ASHRAE TC 9.9: Termal limit yaklaşımı
    - ASHRAE 90.4-2019: Veri merkezi enerji standardı
    - AHRI 550/590: Chiller rated conditions
    - UCI CCPP: AT-PE r=-0.948 korelasyonu
    - TS EN 50600 series: Veri merkezi belgelendirme uyumu
    """
    it_power     = server_workload_pct / 100 * it_capacity_mw * 1000
    cooling_load = it_power * 0.97

    # Chiller nominal kapasitesi IT max'ın %105'i
    nominal_cooling = it_capacity_mw * 1000 * 1.05
    part_load_ratio = max(0.15, min(1.0, cooling_load / nominal_cooling))

    free_factor   = calculate_free_cooling(ambient_temp_c)
    cop           = calculate_cop(ambient_temp_c, chiller_setpoint_c, part_load_ratio)
    # Tesis içi soğutma dağıtım kaybı (pompalar, CRAH/CRAC fanları, vana/dağıtım).
    cooling_distribution_factor = 1.35
    chiller_power = cooling_load * (1 - free_factor) / cop * cooling_distribution_factor
    fan_power     = calculate_fan_power(it_power, fan_speed_pct)
    aux_power     = it_power * 0.08

    total = it_power + chiller_power + fan_power + aux_power
    pue   = total / it_power

    inlet_temp        = calculate_inlet_temp(
        server_workload_pct,
        ambient_temp_c,
        free_factor,
        chiller_setpoint_c,
        fan_speed_pct,
    )
    electricity_price = 3.2

    bms_command = {
        "device": "CHILLER-01",
        "chilled_water_setpoint_c": chiller_setpoint_c,
        "fan_speed_pct": fan_speed_pct,
        "protocol": "BACnet/IP",
        "approval_required": True,
        "standards_profile": "TS EN 50600-aligned demo",
    }

    return {
        "pue":                  round(pue, 4),
        "it_power_kw":          round(it_power, 1),
        "chiller_power_kw":     round(chiller_power, 1),
        "fan_power_kw":         round(fan_power, 1),
        "aux_power_kw":         round(aux_power, 1),
        "total_power_kw":       round(total, 1),
        "cop_real":             round(cop, 4),
        "cooling_distribution_factor": cooling_distribution_factor,
        "part_load_ratio":      round(part_load_ratio, 3),
        "inlet_temp_c":         round(inlet_temp, 2),
        "free_cooling_active":  free_factor > 0,
        "free_cooling_factor":  round(free_factor, 3),
        "ashrae_status":        check_ashrae(inlet_temp),
        "safety_ok":            inlet_temp < 27.0,
        "hourly_cost_tl":       round(total * electricity_price, 2),
        "co2_kg_per_hour":      round(total * 0.45, 2),
        "bms_command":          json.dumps(bms_command, ensure_ascii=False),
        "standards_compliance": {
            "cop_basis":             "AHRI 550/590",
            "setpoint_rule":         "ASHRAE 90.4 (+1°C = -1.4%)",
            "part_load_curve":       "ASHRAE 90.1 EIR-PLR quadratic",
            "ambient_correlation":   "UCI CCPP r=-0.948",
            "ashrae_thermal":        "TC 9.9",
            "pue_methodology":       "ISO/IEC 30134-2",
            "turkish_compliance":    "TS EN 50600 data center certification alignment",
        },
    }


def validate_recommendation(current: dict, proposed: dict) -> dict:
    """
    Öneri güvenli mi? Fizik, PUE ve ASHRAE kontrolü.
    """
    issues = []

    if proposed["inlet_temp_c"] > 27:
        issues.append("ASHRAE ihlali: inlet temp > 27°C")
    if proposed["pue"] > current["pue"]:
        issues.append("PUE kötüleşiyor")
    if proposed["cop_real"] < 1.5:
        issues.append("COP minimum altında")

    monthly_savings_tl = (
        (current["pue"] - proposed["pue"])
        * proposed["it_power_kw"]
        * 720
        * 3.2
    )

    return {
        "approved":           len(issues) == 0,
        "issues":             issues,
        "pue_improvement":    round(current["pue"] - proposed["pue"], 4),
        "monthly_savings_tl": round(monthly_savings_tl, 0),
    }


if __name__ == "__main__":
    import json as _json

    print("=== YAZ OGLE (35°C, %85 yük, setpoint 7°C, fan %82) ===")
    r1 = calculate_pue(85, 35, chiller_setpoint_c=7, fan_speed_pct=82)
    print(f"PUE: {r1['pue']}, COP: {r1['cop_real']}, PLR: {r1['part_load_ratio']}")
    print(f"Inlet: {r1['inlet_temp_c']}°C, ASHRAE: {r1['ashrae_status']}")
    print(f"Maliyet: {r1['hourly_cost_tl']} TL/saat")

    print("\n=== KIS GECESI (-2°C, %45 yük, setpoint 12°C, fan %50) ===")
    r2 = calculate_pue(45, -2, chiller_setpoint_c=12, fan_speed_pct=50)
    print(f"PUE: {r2['pue']}, COP: {r2['cop_real']}, PLR: {r2['part_load_ratio']}")
    print(f"Free cooling: {r2['free_cooling_active']}")

    print("\n=== SETPOINT SENSITIVITY (yaz, %85 yük) ===")
    print(f"{'Setpoint':<10}{'PUE':<10}{'COP':<10}{'Inlet':<12}{'ASHRAE':<25}")
    for sp in [7, 9, 11, 13, 15]:
        r = calculate_pue(85, 35, chiller_setpoint_c=sp, fan_speed_pct=70)
        print(f"{sp}°C{'':<7}{r['pue']:<10}{r['cop_real']:<10}{r['inlet_temp_c']}°C{'':<6}{r['ashrae_status']}")

    print("\n=== FAN SPEED SENSITIVITY (yaz, setpoint 10°C, %85 yük) ===")
    for fs in [40, 55, 70, 85, 95]:
        r = calculate_pue(85, 35, chiller_setpoint_c=10, fan_speed_pct=fs)
        print(f"Fan %{fs:<5}-> PUE {r['pue']}, Inlet {r['inlet_temp_c']}°C, ASHRAE: {r['ashrae_status']}")

    print("\n=== PART-LOAD SENSITIVITY (yaz, setpoint 10°C) ===")
    for wl in [25, 50, 75, 100]:
        r = calculate_pue(wl, 35, chiller_setpoint_c=10, fan_speed_pct=70)
        print(f"Workload {wl:>3}% -> PLR {r['part_load_ratio']}, COP {r['cop_real']}, PUE {r['pue']}")

    print("\n=== STANDARDS COMPLIANCE ===")
    print(_json.dumps(r1["standards_compliance"], indent=2, ensure_ascii=False))
