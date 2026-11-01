# Audio Speed-Up

Web app untuk mempercepat banyak audio sekaligus (nada ikut naik), meng-upload hasilnya ke Roblox, dan menghasilkan blok Lua siap salin.

## Fitur

- Pilih/seret **banyak file audio lokal** sekaligus (bulk). Judul lagu bisa diedit per file.
- Restore speed preset `0.43`, `0.44`, atau custom.
- Ekspor **OGG (Vorbis q10, default)** atau **MP3 (320 kbps)** di browser (WebAssembly).
- **Upload ke Roblox** lewat Open Cloud Assets API dan tampilkan Asset ID. Nama asset di Roblox dibuat `no copyright song <angka acak>`; `SongName` di hasil Lua memakai nama file asli (bisa diedit).
- **Validasi Creator ID**: menampilkan nama Group/User sebelum upload.
- **Cek moderasi**: status Approved/Reviewing/Rejected ditampilkan per file. Audio yang belum Approved tidak bisa diputar di Studio ("Asset is not approved for the requester"); audio milik Group hanya bisa dipakai di game milik Group yang sama.
- Hasil siap salin:

```lua
			{
				SongName = "judul lagu",
				SoundId = "rbxassetid://123456789",
				ImageId = "rbxassetid://93672832601289",
				PlaybackSpeed = 0.43,
			},
```

## Cara kerja upload

Browser tidak bisa memanggil `apis.roblox.com` langsung (CORS), jadi file dikirim ke `POST /api/roblox_upload` (Vercel Python Function) yang meneruskannya ke Roblox, lalu browser memantau status operasi sampai Asset ID keluar.

- API key diisi di halaman, dikirim per request lewat header, **tidak disimpan di server**. Opsi "Ingat" menyimpannya di `localStorage` browser kamu (jangan dipakai di komputer bersama).
- **Batas Vercel: body request 4.5 MB.** File upload otomatis dibuat ulang dengan kualitas lebih rendah (MP3 320→96 kbps / OGG q10→q0) jika lebih dari 4.3 MB. File yang kamu unduh tetap kualitas terbaik.
- Batas Roblox: audio maks 7 menit; 10 upload/bulan (belum ID-verified) atau 100 upload/bulan (ID-verified).

## Membuat API key Roblox

1. Buka https://create.roblox.com/dashboard/credentials → **Create API Key**.
2. Tambahkan API **Assets** dengan izin **Read** dan **Write**.
3. Pada **Accepted IP Addresses**, isi `0.0.0.0/0` (IP Vercel tidak tetap).
4. Salin key (hanya muncul sekali; key Roblox bisa sangat panjang, itu normal). Pemilik key harus sama dengan Creator ID. Untuk grup: pilih **Group** sebagai pemilik key, pilih "Upload sebagai: Group" di halaman, isi **Group ID**, dan pastikan akun kamu punya izin upload/kelola asset di grup tersebut.

## Deploy

Upload seluruh isi folder ini ke root repository GitHub (termasuk file berawalan titik), lalu import ke Vercel dengan Framework Preset **Other**, Build/Output kosong. Tidak perlu environment variable.

```text
.
├── api/
│   └── roblox_upload.py
├── public/
│   └── index.html
├── pyproject.toml
├── vercel.json
├── .python-version
├── .gitignore
└── README.md
```

Tes: buka `https://NAMA-PROJECT.vercel.app/api/roblox_upload` → harus menampilkan `{"ok": true, ...}`.

## Catatan

- Endpoint hanya menerima request dari origin yang sama.
- Upload hanya konten yang kamu miliki atau punya izin untuk digunakan; audio bisa ditolak moderasi Roblox.
