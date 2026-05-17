# ThermaIQ

ThermaIQ, veri merkezi sogutma operasyonlarini PUE, termal guvenlik ve enerji maliyeti acisindan optimize eden bir dijital ikiz demosudur. Backend tarafinda fizik tabanli PUE hesaplama, Optuna ile kisitli optimizasyon ve Nemotron/OpenRouter destekli operasyon raporu uretilir. Frontend tarafinda ise dashboard, takvim veri katmanlari, dosya yukleme akislari ve demo raporlari gosterilir.

## Neler Var?

- FastAPI tabanli backend
- Fizik tabanli PUE ve ASHRAE benzeri guvenlik kontrolleri
- Optuna ile chiller setpoint ve fan hizi optimizasyonu
- NVIDIA Nemotron veya OpenRouter ile LLM destekli politika/rapor uretimi
- API anahtari yoksa local fallback/mock rapor modu
- Statik HTML frontend
- Takvim olaylari, sicaklik, trafik/yuk ve operasyon/sensor ornek verileri
- Tek komutla demo baslatmak icin `run_demo.bat`

## Proje Yapisi

```text
thermaiq/
|-- backend/
|   |-- main.py                    # FastAPI uygulamasi ve endpointler
|   |-- physics.py                 # PUE, termal durum ve dogrulama hesaplari
|   |-- optimizer.py               # Optuna tabanli dijital ikiz optimizasyonu
|   |-- nemotron.py                # Nemotron/OpenRouter entegrasyonu ve fallback raporlar
|   |-- calendar_parser.py         # Takvim olay dosyasi parser'i
|   |-- adaptation.py              # Musteri verisi adaptasyon yardimcilari
|   |-- generate_data.py           # Veri uretim yardimcilari
|   |-- evaluate_optimization.py   # Optimizasyon degerlendirme betigi
|   `-- requirements.txt           # Python bagimliliklari
|-- frontend/
|   |-- index.html                 # Statik demo iskeleti
|   |-- assets/
|   |   |-- app.js                 # Frontend davranislari
|   |   |-- styles.css             # Arayuz stilleri
|   |   `-- favicon.svg            # Tarayici sekme logosu
|   |-- panels/                    # Dashboard, simulator, takvim vb. panel parcalari
|   |-- API_CONTRACTS.md           # Frontend-backend endpoint sozlesmeleri
|   |-- README.md                  # Frontend sorumluluk notlari
|   |-- calendar-events-sample.csv
|   |-- calendar-events-sample.txt
|   `-- sample-data/
|       |-- important-dates.csv
|       |-- operations-sensor-sample.csv
|       |-- traffic-forecast.csv
|       `-- weather-forecast.csv
|-- data/                          # Ham/islenmis veri klasoru
|-- models/                        # Egitilmis model dosyalari icin alan
|-- demo_scenarios.json            # Demo senaryo verileri
|-- thermaiqlast.html              # Alternatif/onceki HTML demo ciktisi
|-- run_demo.bat                   # Backend + frontend demo baslatici
|-- .env.example                   # Ortam degiskeni sablonu
`-- README.md
```

## Gereksinimler

- Python 3.10+ onerilir
- Windows icin `run_demo.bat` kullanilabilir
- LLM raporlari icin opsiyonel olarak `NVIDIA_API_KEY` veya `OPENROUTER_API_KEY`

API anahtari olmadan da demo calisir. Bu durumda backend deterministic local fallback raporlar uretir.

## Kurulum

```powershell
cd C:\Users\ASUS\Desktop\thermaiq
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

`.env` dosyasina sadece kullanacaginiz saglayicinin anahtarini girmeniz yeterlidir:

```env
NVIDIA_API_KEY=nvapi-xxx
OPENROUTER_API_KEY=sk-or-v1-xxx
```

## Calistirma

### Hizli demo

Windows'ta proje kokunden:

```powershell
.\run_demo.bat
```

Not: `run_demo.bat` proje kokundeki `.venv` Python'unu, bu makinedeki Codex Python runtime'ini, `python` komutunu veya Windows `py -3` komutunu otomatik bulmaya calisir.

Bu betik:

- Backend'i `http://127.0.0.1:8001` adresinde baslatir
- Frontend'i `http://127.0.0.1:3000` adresinde baslatir
- Tarayicida frontend'i acar

Frontend panelleri parcalara ayrildigi icin arayuzu dogrudan `index.html` dosyasina cift tiklayarak degil, `run_demo.bat` veya local HTTP server ile acin.

### Manuel calistirma

Backend:

```powershell
cd C:\Users\ASUS\Desktop\thermaiq\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Frontend:

```powershell
cd C:\Users\ASUS\Desktop\thermaiq
python -m http.server 3000 -d frontend
```

Tarayici:

```text
http://127.0.0.1:3000
```

API dokumani:

```text
http://127.0.0.1:8001/docs
```

## Temel Endpointler

| Method | Endpoint | Aciklama |
| --- | --- | --- |
| `GET` | `/health` | Servis ve bilesen saglik durumu |
| `POST` | `/api/predict` | Tek senaryo icin PUE hesaplama |
| `POST` | `/api/twin-optimize` | Fizik motoru + LLM politika + Optuna optimizasyonu |
| `POST` | `/api/report` | Operasyon raporu uretimi |
| `GET` | `/api/report/sample` | Mock rapor ornegi |
| `GET` | `/api/demo-scenarios` | Offline demo senaryolari |
| `POST` | `/api/bms/apply` | Mock BACnet/IP komut uygulama |
| `POST` | `/api/calendar/parse` | Takvim olay dosyasi parse etme |
| `GET` | `/api/calendar/sample` | Ornek takvim olaylari |
| `POST` | `/api/adaptation/upload` | Musteri CSV on kontrolu |
| `POST` | `/api/adaptation/run` | Musteri CSV adaptasyon demo akisi |

## Ornek API Kullanimi

PUE tahmini:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8001/api/predict `
  -ContentType "application/json" `
  -Body '{"server_workload_pct":85,"ambient_temp_c":35,"chiller_setpoint_c":7,"fan_speed_pct":65,"it_capacity_mw":21}'
```

Optimizasyon:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8001/api/twin-optimize `
  -ContentType "application/json" `
  -Body '{"server_workload_pct":85,"ambient_temp_c":35,"hour":14,"month":7,"it_capacity_mw":21,"n_trials":60}'
```

Local/mock rapor:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8001/api/report `
  -ContentType "application/json" `
  -Body '{"scenario_name":"Yaz ogle demo","current_pue":1.74,"optimum_pue":1.31,"ambient_temp_c":35,"server_workload_pct":85,"monthly_savings_tl":412000,"use_mock":true}'
```

## Veri Dosyalari

Frontend takvim ekraninda dort farkli veri tipi kullanilir:

- Onemli tarihler: resmi tatil, sinav, mac, kampanya veya kamu yogunlugu gibi olaylar
- Sicaklik verisi: tarih bazli dis sicaklik tahmini veya gecmis verisi
- Trafik/yuk verisi: tarih bazli sunucu yuku veya trafik tahmini
- Operasyon/sensor verisi: saatlik veri merkezi olcumleri

Ornek dosyalar `frontend/sample-data/` altindadir. API tarafindaki takvim parser'i `.csv`, `.json`, `.txt`, `.tsv` ve `.md` formatlarini destekler.

## Notlar

- Frontend su anda backend'i `http://127.0.0.1:8001` adresinde bekler.
- `POST /api/report` icin `use_mock: true` gonderilirse LLM API cagrisi yapilmaz.
- API anahtari eksik veya servis hatasi olursa backend otomatik local fallback uretir.
- `models/` klasoru egitilmis model dosyalari icin ayrilmistir; mevcut demo agirlikli olarak fizik motoru ve optimizasyon akisini kullanir.
