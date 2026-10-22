# Dashboard Areal Kebakaran Hutan dan Lahan Provinsi Riau 2023–2025

Dashboard web interaktif yang menampilkan peta, luas, dan estimasi emisi CO₂ areal kebakaran hutan dan lahan di Provinsi Riau tahun 2023–2025 per kabupaten/kota. Areal terbakar merupakan hasil identifikasi model deep learning U-Net++ dari citra Sentinel-1.

Bagian dari skripsi *Identifikasi Areal Kebakaran Hutan dan Lahan Menggunakan Deep Learning dan Data Penginderaan Jauh (Studi Kasus: Provinsi Riau)* — Gilbert Rubenson, Politeknik Statistika STIS.

## Menjalankan di laptop

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Isi repositori

| File/folder | Keterangan |
|---|---|
| `app.py` | aplikasi dashboard (file utama untuk Streamlit Community Cloud) |
| `requirements.txt` | pustaka Python yang dibutuhkan |
| `.streamlit/config.toml` | pengaturan tema Streamlit |
| `dashboard_data/` | data siap pakai: areal terbakar per tahun, batas wilayah, ringkasan luas dan emisi |
