# Audio Speed-Up

Web app untuk mempercepat audio dengan perubahan pitch (nada ikut naik), lalu menguji pemulihan kecepatan menggunakan nilai restore.

## Fitur

- Upload audio lokal.
- Memuat direct link audio (bergantung pada CORS server sumber).
- Memuat audio dari URL YouTube melalui Vercel Python Function + `yt-dlp`.
- Restore speed preset `0.43`, `0.44`, atau custom.
- Ekspor MP3 atau OGG melalui WebAssembly di browser.
- Preview, tes restore, dan unduh hasil.

## Batasan endpoint YouTube di Vercel

Endpoint ini sengaja membatasi:
- Maksimal 5 menit per video.
- Maksimal 4 MB untuk file audio yang diunduh.
- Satu video saja (playlist tidak diproses).

Vercel Functions membatasi response body hingga 4.5 MB. Batas 4 MB di aplikasi menjaga response berada di bawah batas platform. Video yang lebih panjang/berukuran lebih besar akan ditolak. Untuk audio panjang, gunakan worker/backend terpisah dan object storage.

`yt-dlp` tidak menjamin semua video dapat diambil. YouTube dapat mengubah mekanisme akses atau menolak IP server cloud. Video privat, video yang membutuhkan login, dan konten yang dibatasi tidak didukung.

## Deploy ke GitHub dan Vercel

### 1. Upload ke GitHub

1. Buat repository baru di GitHub.
2. Upload seluruh isi folder ini ke root repository (bukan folder ZIP di dalam repository).
3. Pastikan `public/index.html`, `vercel.json`, `pyproject.toml`, `requirements.txt`, `.python-version`, dan folder `api/` berada di root.

Atau melalui Git:

```bash
git init
git add .
git commit -m "Prepare Audio Speed-Up for Vercel"
git branch -M main
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

### 2. Deploy di Vercel

1. Login ke https://vercel.com
2. Pilih **Add New → Project**.
3. Import repository GitHub.
4. Framework Preset: **Other**.
5. Root Directory: `./`.
6. Build Command: kosongkan / override off.
7. Output Directory: kosongkan.
8. Klik **Deploy**.

Vercel akan menyajikan `public/index.html` sebagai static page dan mendeteksi `api/youtube_audio.py` sebagai Python Function.

### 3. Tes endpoint

Setelah deploy, buka:

```text
https://NAMA-PROJECT.vercel.app/api/youtube_audio
```

Endpoint GET harus menampilkan JSON status dan batas penggunaan. Kembali ke halaman utama untuk menguji URL YouTube.

## Pengembangan lokal

Python 3.12+:

```bash
python -m venv .venv
```

Aktifkan virtual environment, lalu:

```bash
pip install -r requirements.txt
```

Untuk menjalankan frontend dan API secara lokal dengan routing Vercel, gunakan Vercel CLI:

```bash
npm install -g vercel
vercel dev
```

Buka URL lokal yang ditampilkan Vercel CLI.

## Privasi dan hak cipta

- Jangan gunakan untuk mengunduh konten yang tidak kamu miliki atau tidak memiliki izin untuk mengunduhnya.
- Jangan mengunggah cookie, token, atau kredensial YouTube ke repository.
- Endpoint publik dapat disalahgunakan dan konsumsi Function dapat menimbulkan biaya. Tambahkan autentikasi, rate limiting, dan pembatasan penggunaan sebelum penggunaan publik berskala besar.
- Jangan mencoba melewati login, paywall, DRM, atau pembatasan akses.

## Struktur

```text
.
├── api/
│   └── youtube_audio.py
├── public/
│   └── index.html
├── requirements.txt
├── vercel.json
├── .python-version
├── .gitignore
└── README.md
```
