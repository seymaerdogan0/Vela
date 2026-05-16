# Frontend API Kontratları

Bu dosya frontend ile backend/model ekipleri arasındaki pratik sözleşmedir.

## Backend Base URL

Frontend şu an backend'i burada bekler:

```text
http://127.0.0.1:8001
```

`frontend/index.html` içinde:

```js
const API_BASE = "http://127.0.0.1:8001";
```

## Rapor Endpoint'i

```http
POST /api/report
```

Frontend bu endpoint'e dashboard/simülatör metriklerini gönderir.

Minimum payload:

```json
{
  "current_pue": 1.55,
  "optimum_pue": 1.24,
  "use_mock": true
}
```

Tercih edilen payload:

```json
{
  "scenario_name": "Simülatör senaryosu",
  "current_pue": 1.74,
  "optimum_pue": 1.31,
  "ambient_temp_c": 35,
  "server_workload_pct": 85,
  "monthly_savings_tl": 412000,
  "current_chiller_pct": 78,
  "optimized_chiller_pct": 62,
  "current_fan_pct": 85,
  "optimized_fan_pct": 58,
  "physics_status": "ok",
  "use_mock": true
}
```

Response:

```json
{
  "provider": "local-template",
  "model": "thermaiq-local-template",
  "report": "Türkçe operasyon raporu...",
  "validated": true,
  "validation_warnings": [],
  "api_warning": null,
  "source_metrics": {}
}
```

Frontend şu alanları kullanır:

- `provider`
- `report`
- `validated`
- `validation_warnings`

## Takvim Önemli Tarih Upload

```http
POST /api/calendar/parse
```

Frontend sadece `Önemli tarihler` seçiliyken bu endpoint'i çağırır.

Kabul edilen formatlar:

- `.csv`
- `.json`
- `.txt`
- `.tsv`
- `.md`

Örnek CSV:

```csv
date,event_name,category,expected_load_impact,is_holiday
2026-06-15,KPSS Sonuçlarının Açıklanması,e-Devlet Trafik,Critical,0
```

Örnek TXT:

```txt
KPSS Sonuçlarının Açıklanması | 2026-06-15 | Critical | 26 | e-Devlet trafik piki | +15C Kritik Ek Soğutma Modu
```

Response:

```json
{
  "events": [
    {
      "id": 1,
      "day": 15,
      "month": "June",
      "name": "KPSS Sonuçlarının Açıklanması",
      "load": 98,
      "level": "high",
      "date": "2026-06-15",
      "temp": 23,
      "desc": "e-Devlet Trafik kategorisinde Critical etki bekleniyor.",
      "cooling": "+15C Kritik Ek Sogutma Modu"
    }
  ],
  "accepted_count": 1,
  "rejected_count": 0,
  "errors": []
}
```

Frontend `events` listesini gerçek aylık takvime yerleştirir.

## Sıcaklık ve Trafik Dosyaları

Şimdilik frontend içinde parse edilir. Backend'e gitmez.

Sıcaklık:

```csv
date,temp
2026-10-25,18
```

Trafik/yük:

```csv
date,load
2026-10-25,92
```

Bu veriler olay olarak görünmez; gün hücresinde küçük veri etiketi olarak görünür.

## Operasyon/Sensör Verisi

Bu dosya modeli eğitmek için değil, frontend'de veri katmanını göstermek için okunur.

Desteklenen Kaggle benzeri başlık:

```csv
Timestamp,Server_Workload(%),Inlet_Temperature(Â°C),Outlet_Temperature(Â°C),Ambient_Temperature(Â°C),Cooling_Unit_Power_Consumption(kW),Chiller_Usage(%),AHU_Usage(%),Total_Energy_Cost($),Temperature_Deviation(Â°C),Cooling_Strategy_Action,Output
```

Frontend şu alanları kullanır:

- `Timestamp` → takvim günü
- `Server_Workload(%)` → günlük ortalama trafik/yük katmanı
- `Ambient_Temperature(Â°C)` → günlük ortalama sıcaklık katmanı

Diğer kolonlar şimdilik frontend tarafından gösterilmez; model/backend ekibi için ham veri olarak değerlidir.
