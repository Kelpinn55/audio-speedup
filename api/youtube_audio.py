"""
Backend tipis (Vercel Python Function) untuk RapidAPI "youtube-mp310"
(YouTube -> MP3). API key disimpan di server, tidak pernah dikirim ke browser.

  POST /api/youtube_audio  {"url": "<link YouTube>"}
       -> {"status":"SUCCEEDED","fileUrl","sig","title"}
  GET  /api/youtube_audio?file=<fileUrl>&sig=<sig>
       -> proxy file MP3 (cadangan jika browser diblokir CORS; maks ~4.4 MB)
  GET  /api/youtube_audio  -> cek status endpoint

Environment variable di Vercel:
  RAPIDAPI_KEY   (wajib)    API key RapidAPI
  RAPIDAPI_HOST  (opsional) default: youtube-mp310.p.rapidapi.com
"""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
MAX_PROXY_BYTES = 4_400_000  # batas aman respons Vercel (4.5 MB)
UA = "Mozilla/5.0 (compatible; AudioSpeedUp/2.0)"

URL_KEYS = ("link", "url", "download_url", "downloadurl", "download", "mp3", "mp3_link",
            "mp3url", "file", "audio", "audio_url", "audiourl", "result", "data")
SKIP_KEYS = ("thumb", "image", "cover", "poster", "avatar", "icon", "progress")
TITLE_KEYS = ("title", "name", "filename", "videotitle")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def api_key() -> str:
    k = os.environ.get("RAPIDAPI_KEY", "").strip()
    if not k:
        raise ApiError("RAPIDAPI_KEY belum diatur di Environment Variables Vercel.", 500)
    return k


def api_host() -> str:
    return os.environ.get("RAPIDAPI_HOST", "youtube-mp310.p.rapidapi.com").strip()


def sign(file_url: str) -> str:
    """Tanda tangan agar proxy hanya mau mengambil URL yang diterbitkan backend ini."""
    return hmac.new(api_key().encode(), file_url.encode(), hashlib.sha256).hexdigest()[:32]


def find_url(obj):
    """Cari link file di JSON dengan struktur apa pun (kunci umum dulu, lalu cari rekursif)."""
    if isinstance(obj, str):
        return obj if obj.startswith(("http://", "https://")) else None
    if isinstance(obj, dict):
        lower = {str(k).lower(): v for k, v in obj.items()}
        for k in URL_KEYS:
            if k in lower:
                found = find_url(lower[k])
                if found:
                    return found
        for k, v in lower.items():
            if any(s in k for s in SKIP_KEYS):
                continue
            found = find_url(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = find_url(v)
            if found:
                return found
    return None


def find_title(obj):
    if isinstance(obj, dict):
        lower = {str(k).lower(): v for k, v in obj.items()}
        for k in TITLE_KEYS:
            if isinstance(lower.get(k), str) and lower[k].strip():
                return lower[k].strip()
        for v in lower.values():
            t = find_title(v)
            if t:
                return t
    if isinstance(obj, list):
        for v in obj:
            t = find_title(v)
            if t:
                return t
    return None


def call_rapidapi(video_url: str):
    endpoint = f"https://{api_host()}/download/mp3?url={quote(video_url, safe='')}"
    req = Request(endpoint, headers={
        "x-rapidapi-key": api_key(),
        "x-rapidapi-host": api_host(),
        "User-Agent": UA,
    })
    try:
        with urlopen(req, timeout=50) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", errors="replace")).get("message", "")
        except Exception:
            detail = ""
        detail = f" [{e.code}] {detail}".rstrip()
        print("rapidapi http error:", e.code, detail[:300])
        if e.code in (401, 403):
            raise ApiError("API key RapidAPI ditolak atau belum subscribe ke API ini." + detail, 502)
        if e.code == 429:
            raise ApiError("Kuota/limit RapidAPI habis. Coba lagi nanti." + detail, 429)
        raise ApiError("RapidAPI menolak permintaan." + detail, 502)
    except (URLError, TimeoutError):
        raise ApiError("Tidak bisa menghubungi RapidAPI atau responsnya terlalu lama.", 504)

    try:
        data = json.loads(body)
    except ValueError:
        raise ApiError("Respons RapidAPI bukan JSON: " + body[:200], 502)
    return data


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _same_origin(self) -> bool:
        """Cegah situs lain memakai endpoint (dan kuota API) kamu."""
        site = self.headers.get("Sec-Fetch-Site")
        if site:
            return site == "same-origin"
        host = self.headers.get("Host", "")
        for name in ("Origin", "Referer"):
            value = self.headers.get(name)
            if value:
                return urlparse(value).netloc == host
        return False

    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            if not query:
                return self._json(200, {"ok": True, "service": "youtube_audio", "provider": "rapidapi"})
            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})
            if "file" in query:
                return self._proxy_file(query["file"][0], query.get("sig", [""])[0])
            return self._json(400, {"error": "Request tidak valid."})
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    def _proxy_file(self, file_url: str, sig: str):
        if not hmac.compare_digest(sign(file_url), sig):
            return self._json(403, {"error": "Tanda tangan URL tidak valid."})
        if urlparse(file_url).scheme not in ("http", "https"):
            return self._json(400, {"error": "URL file tidak valid."})
        try:
            with urlopen(Request(file_url, headers={"User-Agent": UA}), timeout=40) as resp:
                content_type = resp.headers.get("Content-Type", "audio/mpeg")
                data = resp.read(MAX_PROXY_BYTES + 1)
        except (HTTPError, URLError, TimeoutError):
            return self._json(502, {"error": "Gagal mengunduh file MP3 dari penyedia API."})
        if len(data) > MAX_PROXY_BYTES:
            return self._json(413, {
                "error": "File MP3 lebih dari 4.4 MB sehingga tidak bisa lewat Vercel, "
                         "dan browser tidak bisa mengunduh langsung (diblokir CORS)."
            })
        if not content_type.startswith("audio/"):
            content_type = "audio/mpeg"
        self._send(200, data, content_type)

    def do_POST(self):
        try:
            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                return self._json(400, {"error": "Request tidak valid."})

            url = (json.loads(self.rfile.read(length)).get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HOSTS:
                return self._json(400, {"error": "Masukkan URL YouTube yang valid."})

            data = call_rapidapi(url)
            file_url = find_url(data)
            if not file_url:
                snippet = json.dumps(data, ensure_ascii=False)[:300]
                print("no link in response:", snippet)
                return self._json(502, {
                    "error": "RapidAPI tidak mengembalikan link MP3. Respons: " + snippet
                })
            self._json(200, {
                "status": "SUCCEEDED",
                "fileUrl": file_url,
                "sig": sign(file_url),
                "title": find_title(data) or "youtube-audio",
            })
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except (ValueError, KeyError):
            self._json(400, {"error": "Request tidak valid."})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    def log_message(self, format, *args):
        return  # jangan log URL YouTube atau key
