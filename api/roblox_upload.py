"""
Proxy tipis (Vercel Python Function) ke Roblox Open Cloud Assets API.
Diperlukan karena apis.roblox.com tidak bisa dipanggil langsung dari browser (CORS).

API key Roblox dikirim dari browser lewat header `x-roblox-key` untuk SETIAP request
dan TIDAK disimpan / di-log di server.

  POST /api/roblox_upload?name=&creatorType=user|group&creatorId=&ext=mp3|ogg
       header: x-roblox-key
       body  : isi file audio mentah (maks ~4.4 MB karena batas body Vercel 4.5 MB)
       -> {"operationId": "...", "done": bool, "assetId": "..."?}

  GET  /api/roblox_upload?operation=<operationId>
       header: x-roblox-key
       -> {"done": false}  atau  {"done": true, "assetId": "..."}

  GET  /api/roblox_upload?asset=<assetId>
       header: x-roblox-key
       -> {"assetId": "...", "moderation": "approved|reviewing|rejected|unknown"}

  GET  /api/roblox_upload?validate=1&creatorType=user|group&creatorId=
       (tanpa key; pakai API publik Roblox)
       -> {"ok": true, "type": "group", "id": "...", "name": "Nama Group"}

  GET  /api/roblox_upload  -> cek status endpoint
"""
import json
import re
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROBLOX = "https://apis.roblox.com/assets/v1"
MAX_BODY_BYTES = 4_400_000  # batas body Vercel = 4.5 MB
CONTENT_TYPES = {"mp3": "audio/mpeg", "ogg": "audio/ogg"}
OP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,100}$")
ID_RE = re.compile(r"^\d{1,20}$")
KEY_RE = re.compile(r"^[A-Za-z0-9+/=_.~-]+$")  # base64 / base64url / JWT-like
MAX_KEY_LEN = 4096  # key Roblox bisa sangat panjang (ratusan karakter)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def clean_key(value: str) -> str:
    # Hapus semua whitespace (spasi/enter ikut ter-copy saat paste); key asli tidak mengandung whitespace.
    key = re.sub(r"\s+", "", value or "")
    if not key:
        raise ApiError("API key Roblox kosong. Tempel key di kolom API Key.", 400)
    if len(key) < 20:
        raise ApiError(f"API key Roblox terlalu pendek ({len(key)} karakter). Pastikan key tersalin utuh.", 400)
    if len(key) > MAX_KEY_LEN:
        raise ApiError(f"API key Roblox terlalu panjang ({len(key)} karakter).", 400)
    if not KEY_RE.match(key):
        raise ApiError("API key Roblox mengandung karakter yang tidak valid. Salin ulang key dari Creator Hub.", 400)
    return key


def roblox_call(req: Request, timeout: int):
    req.add_header("User-Agent", "audio-speedup/3.0 (+vercel)")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", errors="replace"))
            msg = str(body.get("message") or body.get("error") or "")
        except Exception:
            msg = ""
        msg = msg[:300]
        detail = f" [{e.code}] {msg}".rstrip()
        print("roblox http error:", e.code, msg[:200])
        if e.code == 401:
            raise ApiError("API key Roblox tidak valid." + detail, 502)
        if e.code == 403:
            raise ApiError(
                "Akses ditolak Roblox: key perlu izin Assets (asset:read + asset:write), "
                "pemilik key harus sama dengan Creator ID (untuk group: buat key dengan owner = Group, "
                "dan akun pembuat key harus punya izin upload/kelola asset di group), "
                "serta Accepted IP Addresses harus 0.0.0.0/0." + detail, 502)
        if e.code == 429:
            raise ApiError("Terkena rate limit / kuota upload Roblox. Coba lagi nanti." + detail, 429)
        raise ApiError("Roblox menolak permintaan." + detail, 502)
    except (URLError, TimeoutError):
        raise ApiError("Tidak bisa menghubungi Roblox atau responsnya terlalu lama.", 504)
    except ValueError:
        raise ApiError("Respons Roblox tidak valid.", 502)


def extract_result(data: dict) -> dict:
    """Ubah objek 'operation' Roblox menjadi {operationId, done, assetId?}."""
    op_id = str(data.get("path", "")).split("/")[-1]
    out = {"operationId": op_id, "done": bool(data.get("done"))}
    if out["done"]:
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ApiError("Upload ditolak Roblox: " + str(msg)[:300], 502)
        asset_id = str((data.get("response") or {}).get("assetId") or "")
        if not asset_id:
            raise ApiError("Operasi selesai tetapi Roblox tidak mengembalikan assetId.", 502)
        out["assetId"] = asset_id
        out["moderation"] = norm_moderation(data)
    return out


def norm_moderation(data: dict) -> str:
    """Ambil moderationState dari objek asset/operation -> approved | reviewing | rejected | unknown."""
    resp = data.get("response") if isinstance(data.get("response"), dict) else data
    mr = (resp or {}).get("moderationResult") or {}
    state = str(mr.get("moderationState") or "").upper().replace("MODERATION_STATE_", "")
    return {"APPROVED": "approved", "REVIEWING": "reviewing", "REJECTED": "rejected"}.get(state, "unknown")


def lookup_creator(creator_type: str, creator_id: str) -> dict:
    """Validasi ID & ambil nama lewat API publik Roblox (tanpa API key)."""
    if creator_type == "group":
        url = f"https://groups.roblox.com/v1/groups/{creator_id}"
    else:
        url = f"https://users.roblox.com/v1/users/{creator_id}"
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "audio-speedup/3.0 (+vercel)"})
    label = "Group" if creator_type == "group" else "User"
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except HTTPError as e:
        if e.code in (400, 404):
            raise ApiError(f"{label} ID {creator_id} tidak ditemukan di Roblox.", 404)
        if e.code == 429:
            raise ApiError("Roblox membatasi pengecekan sementara (rate limit). Coba lagi sebentar.", 429)
        raise ApiError(f"Tidak bisa memverifikasi {label} ID (HTTP {e.code}).", 502)
    except (URLError, TimeoutError, ValueError):
        raise ApiError(f"Tidak bisa memverifikasi {label} ID (Roblox tidak merespons).", 504)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ApiError(f"{label} ID {creator_id} tidak ditemukan di Roblox.", 404)
    out = {"ok": True, "type": creator_type, "id": creator_id, "name": name}
    if creator_type == "user" and data.get("displayName"):
        out["displayName"] = str(data["displayName"])
    return out


class handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        """Cegah situs lain memakai proxy ini."""
        site = self.headers.get("Sec-Fetch-Site")
        if site:
            return site == "same-origin"
        host = self.headers.get("Host", "")
        for name in ("Origin", "Referer"):
            value = self.headers.get(name)
            if value:
                return urlparse(value).netloc == host
        return False

    # ---------- GET: cek status operasi ----------
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            if not query:
                return self._json(200, {"ok": True, "service": "roblox_upload"})
            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})

            # --- validasi Creator ID (tanpa key): tampilkan nama group/user ---
            if query.get("validate"):
                ctype = query.get("creatorType", [""])[0].lower()
                cid = query.get("creatorId", [""])[0]
                if ctype not in ("user", "group") or not ID_RE.match(cid):
                    return self._json(400, {"error": "Creator ID harus angka dan tipe harus user/group."})
                return self._json(200, lookup_creator(ctype, cid))

            key = clean_key(self.headers.get("x-roblox-key", ""))

            # --- cek status moderasi asset ---
            asset = query.get("asset", [""])[0]
            if asset:
                if not ID_RE.match(asset):
                    return self._json(400, {"error": "Asset ID tidak valid."})
                try:
                    data = roblox_call(Request(f"{ROBLOX}/assets/{asset}?readMask=moderationResult",
                                               headers={"x-api-key": key}), 25)
                except ApiError as e:
                    if e.status in (401, 403, 429):
                        raise
                    data = roblox_call(Request(f"{ROBLOX}/assets/{asset}", headers={"x-api-key": key}), 25)
                return self._json(200, {"assetId": asset, "moderation": norm_moderation(data)})

            # --- status operasi upload ---
            op = query.get("operation", [""])[0]
            if not OP_ID_RE.match(op):
                return self._json(400, {"error": "Operation ID tidak valid."})

            data = roblox_call(Request(f"{ROBLOX}/operations/{op}", headers={"x-api-key": key}), 25)
            self._json(200, extract_result(data))
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    # ---------- POST: upload audio ----------
    def do_POST(self):
        try:
            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})

            query = parse_qs(urlparse(self.path).query)
            key = clean_key(self.headers.get("x-roblox-key", ""))
            ext = query.get("ext", [""])[0].lower()
            creator_type = query.get("creatorType", [""])[0].lower()
            creator_id = query.get("creatorId", [""])[0]
            name = re.sub(r"\s+", " ", query.get("name", [""])[0]).strip()[:50] or "audio"

            if ext not in CONTENT_TYPES:
                return self._json(400, {"error": "Format harus mp3 atau ogg."})
            if creator_type not in ("user", "group") or not ID_RE.match(creator_id):
                return self._json(400, {"error": "Creator ID harus angka dan tipe harus user/group."})

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return self._json(400, {"error": "File kosong."})
            if length > MAX_BODY_BYTES:
                return self._json(413, {"error": "File lebih dari 4.4 MB (batas body Vercel)."})
            audio = self.rfile.read(length)

            creator = {"userId": creator_id} if creator_type == "user" else {"groupId": creator_id}
            request_json = json.dumps({
                "assetType": "Audio",
                "displayName": name,
                "description": "Uploaded with Audio Speed-Up",
                "creationContext": {"creator": creator},
            })

            boundary = "----AudioSpeedUp" + uuid.uuid4().hex
            body = b"".join([
                f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n\r\n{request_json}\r\n'.encode(),
                (f'--{boundary}\r\nContent-Disposition: form-data; name="fileContent"; '
                 f'filename="audio.{ext}"\r\nContent-Type: {CONTENT_TYPES[ext]}\r\n\r\n').encode(),
                audio,
                f"\r\n--{boundary}--\r\n".encode(),
            ])
            req = Request(f"{ROBLOX}/assets", data=body, method="POST", headers={
                "x-api-key": key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            self._json(200, extract_result(roblox_call(req, 50)))
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except (ValueError, KeyError):
            self._json(400, {"error": "Request tidak valid."})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    def log_message(self, format, *args):
        return  # jangan log URL, nama file, atau key
