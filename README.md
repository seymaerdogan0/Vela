# ThermaIQ — AI-Powered Data Center PUE Optimization Platform

ThermaIQ, veri merkezi enerji verimliliğini (PUE) yapay zeka ile optimize eden bir platformdur.

## Genel Bakış

Bu platform; XGBoost tabanlı tahmin modelleri, Optuna ile hiper-parametre optimizasyonu, fizik tabanlı kısıtlar ve NVIDIA Nemotron LLM entegrasyonu kullanarak veri merkezi soğutma sistemlerini gerçek zamanlı olarak optimize eder.

## Proje Yapısı

- `backend/` — FastAPI uygulaması, ML modelleri ve optimizasyon mantığı
- `frontend/` — Kullanıcı arayüzü (geliştirme aşamasında)
- `data/raw/` — Ham sensör verileri
- `data/processed/` — İşlenmiş ve özellik mühendisliği uygulanmış veriler
- `models/` — Eğitilmiş model dosyaları

## Kurulum

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
# .env dosyasına API anahtarlarını ekleyin
uvicorn main:app --reload
```

## Gereksinimler

- Python 3.10+
- NVIDIA API Key (Nemotron entegrasyonu için)
