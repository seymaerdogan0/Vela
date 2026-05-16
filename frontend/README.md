# ThermaIQ Frontend Altyapısı

Bu klasörün amacı model geliştirmek değil; backend/model ekibi hazır oldukça onların çıktısını kullanıcıya anlaşılır, güvenli ve demo yapılabilir bir arayüz olarak göstermektir.

## Sorumluluk Alanı

Frontend tarafı şu işleri sahiplenir:

- Dashboard metriklerini göstermek
- Takvimde önemli tarihleri gerçek günlerine yerleştirmek
- Sıcaklık ve trafik/yük verisini ayrı katmanlar olarak göstermek
- Backend rapor çıktısını Nemotron panelinde göstermek
- Backend hazır değilken demo akışını mock/fallback veriyle ayakta tutmak
- Dosya yükleme tipini kullanıcıya seçtirmek

Frontend tarafı şu işleri sahiplenmez:

- XGBoost model eğitimi
- Optuna trial yönetimi
- Fizik hesaplarının nihai doğruluğu
- NVIDIA API key yönetimi
- Üretim verisini kalıcı saklama

## Çalıştırma

Frontend statik HTML olarak çalışır.

```powershell
cd "C:\Users\Emirhan\OneDrive - Yildiz Technical University\Masaüstü\POE\thermaiq\frontend"
C:\Users\Emirhan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m http.server 3000
```

Tarayıcı:

```text
http://127.0.0.1:3000
```

Backend şu anda frontend tarafından `8001` portunda beklenir:

```text
http://127.0.0.1:8001
```

## Veri Katmanları

Takvim ekranında üç ayrı dosya tipi seçilir:

- `Önemli tarihler`: Resmi tatil, sınav, maç, kampanya, kamu yoğunluğu gibi olaylar.
- `Sıcaklık verisi`: Tarih bazlı geçmiş veya tahmini dış sıcaklık.
- `Trafik/yük verisi`: Tarih bazlı beklenen veya geçmiş sunucu yükü.
- `Operasyon/sensör verisi`: Saatlik veri merkezi ölçümleri. Frontend bu dosyadan günlük ortalama sıcaklık ve yük katmanı üretir.

Bu ayrım önemli: sıcaklık bir olay değildir, takvim gününün üstüne binen bir veri katmanıdır.

## Demo Stratejisi

Backend veya model hazır değilse frontend yine çalışır:

- Varsayılan dashboard değerleri gösterilir.
- Takvim dosyaları yüklenebilir.
- `use_mock: true` ile backend rapor endpoint'i yerel rapor döndürür.

Backend/model ekibi hazır oldukça bu mock noktaları gerçek endpointlere bağlanır.
