# Audio Speed-Up

Web app untuk mempercepat audio (nada ikut naik), lalu menguji pemulihan kecepatan dengan nilai restore.

## Fitur

- Upload audio lokal atau direct link audio (butuh CORS dari server sumber).
- **YouTube → MP3** lewat Apify actor [`web.harvester/youtube-downloader`](https://apify.com/web.harvester/youtube-downloader).
- Restore speed preset `0.43`, `0.44`, atau custom.
- Ekspor **MP3 (320 kbps)** atau **OGG (Vorbis q10)** lewat WebAssembly di browser.
- Preview, tes restore, unduh hasil, dan unduh MP3 sumber dari YouTube.

## Alur YouTube

1. Browser mengirim URL ke `POST /api/youtube_audio`; backend memulai run Apify.
2. Browser memantau `GET /api/youtube_audio?run=ID` sampai selesai (tidak kena timeout function).
3. File MP3 diunduh langsung dari Apify (jika diblokir CORS, lewat `GET /api/youtube_audio?file=...`, maks ~4.4 MB).
4. MP3 diperlambat/dipercepat di browser dan di-encode ke MP3 atau OGG sesuai pilihan.

## Setup Apify

1. Buat akun di https://apify.com, lalu ambil API token di **Settings → API & Integrations**.
2. Di Vercel: **Project → Settings → Environment Variables**, tambahkan:
   - `APIFY_TOKEN` = token Apify kamu (wajib).
   - `APIFY_PROXY_GROUPS` = `RESIDENTIAL` (opsional, hanya jika run biasa sering gagal; proxy residensial lebih mahal).
3. **Redeploy** setelah menambah environment variable.

Biaya actor sekitar **$28 per 1.000 file MP3** (cek halaman pricing Apify untuk angka terbaru), belum termasuk biaya proxy.
**Jangan** menaruh token di `index.html` atau repository.

## Deploy ke GitHub dan Vercel

Upload seluruh isi folder ini ke root repository (termasuk file berawalan titik: `.python-version`, `.gitignore`), lalu import ke Vercel dengan Framework Preset **Other**, Build Command kosong, Output Directory kosong.

Struktur:

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

Tidak ada `requirements.txt` karena backend hanya memakai library standar Python.

Tes endpoint setelah deploy: buka `https://NAMA-PROJECT.vercel.app/api/youtube_audio` → harus menampilkan `{"ok": true, ...}`.

## Pengembangan lokal

```bash
npm install -g vercel
vercel dev
```

Atur `APIFY_TOKEN` lewat `vercel env pull` atau file `.env.local` (jangan di-commit).

## Keamanan dan hak cipta

- Endpoint hanya menerima request dari origin yang sama, tetapi tetap bisa menghabiskan kuota Apify. Aktifkan Vercel Firewall/rate limiting jika situs dibuka publik.
- Gunakan hanya untuk konten yang kamu miliki atau boleh kamu unduh.
