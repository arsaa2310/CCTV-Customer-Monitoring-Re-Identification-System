# Rangkuman: Database Orang, Precision/Recall, dan Lokasi Model

## 1) Database personal / orang yang terdeteksi

Di project ini, data identitas orang disimpan di 2 tempat:

1. Qdrant (database vektor / embedding orang)
   - Koleksi default: `person_embeddings`
   - Didefinisikan di `app/core/config.py`
   - Service Qdrant ada di `docker-compose.yml`
   - Volume persistent: `visiontrack_qdrant_data`
   - Port: `6333`

2. Snapshot foto orang
   - Folder: `./storage/snapshots`
   - Struktur contoh:
     - `storage/snapshots/Person_000001/cam01_001.jpg`
   - Ini dibuat oleh `app/services/snapshot_service.py`

### A. Menghapus satu orang tertentu

Endpoint project sudah tersedia:

```bash
curl -X DELETE "http://localhost:8000/api/person/Person_000001"
```

Ini memanggil fungsi `delete_person()` di `app/qdrant_client/qdrant_service.py`.

### B. Menghapus semua database orang

Untuk bersihkan semua embedding orang di Qdrant:

```bash
curl -X DELETE "http://localhost:6333/collections/person_embeddings"
```

Setelah itu, restart app agar collection dibuat ulang:

```bash
docker restart visiontrack-app
```

Atau wipe volume Qdrant penuh (lebih brutal):

```bash
docker volume rm visiontrack_qdrant_data
```

Lalu start ulang:

```bash
docker compose up -d qdrant
```

### C. Menghapus semua snapshot foto

```bash
sudo rm -rf ./storage/snapshots/*
```

Catatan penting:

- `Qdrant` = data embedding + metadata identitas
- `storage/snapshots` = foto wajah/crop hasil deteksi
- Jika ingin reset total data orang, bersihkan keduanya

---

## 2) Cara meningkatkan akurasi deteksi / recognition

Project ini punya parameter utama di `app/core/config.py` dan `config/cameras.json` (jika ada `settings` di dalam file)

### Parameter penting

- `detection_confidence`
  - default: `0.5`
  - makin tinggi = deteksi lebih ketat, lebih sedikit false positive
  - makin rendah = lebih banyak orang terdeteksi, tapi bisa banyak salah detect

- `similarity_threshold`
  - default: `0.75`
  - ini threshold matching identitas orang di Qdrant
  - semakin tinggi = lebih ketat, lebih sedikit orang dianggap sama
  - semakin rendah = lebih sensitif, tapi lebih gampang salah match

- `frame_skip`
  - default: `10`
  - semakin kecil = proses lebih sering, lebih halus, tapi CPU lebih berat
  - semakin besar = lebih ringan, tapi kadang track jadi kurang stabil

- `max_track_age`
  - mengatur seberapa lama track dipertahankan jika orang ilang dari frame

### Rekomendasi tuning

Untuk akurasi deteksi / person recognition:

- Jika false positive terlalu tinggi:
  - naikkan `detection_confidence` dari `0.5` ke `0.6` atau `0.7`
- Jika miss detection terlalu sering:
  - turunkan `detection_confidence` ke `0.4`
- Jika identity orang sering salah dianggap sama:
  - naikkan `similarity_threshold` dari `0.75` ke `0.8` atau `0.85`
- Jika orang sering tidak terhubung / track putus:
  - turunkan `frame_skip` dan/atau naikkan `max_track_age`

Contoh konfigurasi yang lebih ketat:

```json
{
  "settings": {
    "similarity_threshold": 0.8,
    "detection_confidence": 0.6,
    "frame_skip": 3,
    "max_track_age": 40
  }
}
```

Catatan:

- Untuk precision tinggi: pilih threshold lebih tinggi
- Untuk recall tinggi: pilih threshold lebih rendah
- Biasanya trade-off: precision vs recall

---

## 3) Dimana model disimpan dan cara replace model baru

### A. YOLO model

Di `app/core/config.py`:

```python
# Model
    yolo_model: str = "yolov8n.pt"
    reid_model: str = "osnet_x1_0"
```

Dan `app/detector/yolo_detector.py`:

```python
self._model = YOLO(model_name)
```

Artinya model YOLO bisa dipanggil dengan:

- nama default: `yolov8n.pt`
- file lokal: misalnya `./models/yolov8s.pt`
- path dari cache Ultralytics

Di `docker-compose.yml`, project ini juga mempunyai volume:

```yaml
- yolo_cache:/root/.config/Ultralytics
```

Jadi model YOLO otomatis tersimpan di cache Docker/Ultralytics, bukan di folder repo utama.

### B. ReID model (OSNet)

Di `app/reid/osnet_reid.py` model dibuat dengan:

```python
model = torchreid.models.build_model(
    name=model_name,
    num_classes=1000,
    pretrained=True,
)
```

Artinya model `osnet_x1_0` diambil dari `torchreid` / pretrained weights biasanya tersimpan di cache environment Python, bukan di folder project. Untuk model baru yang lebih bagus, biasanya kita harus:

- menyiapkan model baru
- menaruh di folder khusus, misalnya `models/`
- lalu ubah config agar app memanggil file model yang baru

### C. Cara yang paling rapi untuk replace model baru

Disarankan buat folder seperti ini:

```bash
mkdir -p models
```

Lalu taruh model baru di sini:

- `models/yolov8s.pt`
- `models/yolov8m.pt`
- `models/custom_reid.pth` (jika custom model)

Setelah itu:

- update `APP_YOLO_MODEL` di environment, atau
- edit `app/core/config.py` / `AppSettings`

Contoh paling sederhana untuk YOLO:

```bash
export APP_YOLO_MODEL=/app/models/yolov8s.pt
```

Atau ubah langsung di file config:

```python
# app/core/config.py
    yolo_model: str = "/app/models/yolov8s.pt"
```

Setelah itu restart app:

```bash
docker compose restart fastapi
```

### D. Praktik yang bagus

- simpan semua model di satu folder `models/`
- jangan campur model dengan source code
- versi model bisa ditulis seperti:
  - `models/yolov8s_v1.pt`
  - `models/yolov8s_v2.pt`
  - `models/osnet_best.pth`
- untuk upgrade tinggal ganti nama file path di config

---

## 4) Rekomendasi paling aman untuk project ini

### Reset database orang total

```bash
curl -X DELETE "http://localhost:6333/collections/person_embeddings"
sudo rm -rf ./storage/snapshots/*
docker restart visiontrack-app
```

### Naikkan akurasi

```json
{
  "settings": {
    "similarity_threshold": 0.8,
    "detection_confidence": 0.6,
    "frame_skip": 3,
    "max_track_age": 40
  }
}
```

### Simpan model baru dengan struktur rapi

```bash
mkdir -p models
```

Lalu isi folder `models/` dan arahkan config ke sana.

---

## 5) Ringkasan singkat

- Data orang = Qdrant + snapshot folder
- Untuk reset semua orang: hapus collection Qdrant + snapshot folder
- Untuk akurasi lebih bagus: ubah `detection_confidence` dan `similarity_threshold`
- Model saat ini tersimpan di cache Ultralytics / torchreid, tapi untuk workflow yang rapi sebaiknya pindahkan ke `models/` lalu replace path-nya di config

Kalau mau, saya bisa lanjutkan dengan membuatkan:

1. file `models/README.md` untuk standarisasi penyimpanan model, atau
2. patch config supaya model bisa dipindah ke folder `models/` dengan cara yang lebih rapi.
