# Audio Speed-Up

Web app untuk mempercepat audio (nada ikut naik), lalu menguji pemulihan kecepatan dengan nilai restore.

## Fitur

- Upload audio lokal atau direct link audio (butuh CORS dari server sumber).
- **YouTube → MP3** lewat RapidAPI [`youtube-mp310`](https://rapidapi.com/elisbushaj2/api/youtube-mp310).
- Restore speed preset `0.43`, `0.44`, atau custom.
- Ekspor **MP3 (320 kbps)** atau **OGG (Vorbis q10)** di browser lewat WebAssembly.
- Preview, tes restore, unduh hasil, dan unduh MP3 sumber dari YouTube.

## Alur YouTube

1. Browser mengirim URL ke `POST /api/youtube_audio`; backend memanggil RapidAPI memakai API key (disimpan di server).
2. Backend mengembalikan link MP3. Browser mengunduhnya langsung; jika diblokir CORS, lewat `GET /api/youtube_audio?file=...` (maks ~4.4 MB, URL ditandatangani sehingga proxy tidak bisa disalahgunakan).
3. MP3 dipercepat di browser dan di-encode ke MP3 atau OGG sesuai pilihan.

## Setup RapidAPI

1. Buka halaman API di RapidAPI, klik **Subscribe to Test** dan pilih paket (Basic/gratis jika ada).
2. Salin **X-RapidAPI-Key** dari panel contoh kode.
3. Di Vercel: **Settings → Environment Variables**, tambahkan `RAPIDAPI_KEY` = key tersebut. Opsional: `RAPIDAPI_HOST` (default `youtube-mp310.p.rapidapi.com`).
4. **Redeploy**.

Jangan menaruh key di `index.html` atau repository.

## Deploy

Upload seluruh isi folder ke root repository GitHub (termasuk file berawalan titik), import ke Vercel dengan Framework Preset **Other**, Build/Output kosong.

```text
.
├── api/
│   └── youtube_audio.py
├── public/
│   └── index.html
├── pyproject.toml
├── vercel.json
├── .python-version
├── .gitignore
└── README.md
```

Tes: buka `https://NAMA-PROJECT.vercel.app/api/youtube_audio` → harus menampilkan `{"ok": true, ...}`.

## Keamanan dan hak cipta

- Endpoint hanya menerima request dari origin yang sama, tetapi tetap bisa menghabiskan kuota API. Aktifkan Vercel Firewall/rate limiting jika dibuka publik.
- Gunakan hanya untuk konten yang kamu miliki atau boleh kamu unduh.
