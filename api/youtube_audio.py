"""
Backend tipis (Vercel Python Function) untuk Apify actor
web.harvester/youtube-downloader (YouTube -> MP3).

Alur (supaya tidak kena timeout function Vercel):
  POST /api/youtube_audio            {"url": "..."}  -> mulai run, balas {"runId": "..."}
  GET  /api/youtube_audio?run=<id>                   -> status run; jika selesai balas
                                                        {"status":"SUCCEEDED","fileUrl","title","duration"}
  GET  /api/youtube_audio?file=<fileUrl>             -> proxy file MP3 (cadangan, maks ~4.4 MB)
  GET  /api/youtube_audio                            -> cek status endpoint

Environment variable di Vercel:
  APIFY_TOKEN          (wajib)  token API Apify
  APIFY_PROXY_GROUPS   (opsional) mis. "RESIDENTIAL" jika run biasa sering gagal
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ACTOR = "web.harvester~youtube-downloader"
APIFY = "https://api.apify.com/v2"
ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
RUN_ID_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")
MAX_PROXY_BYTES = 4_400_000  # batas aman respons Vercel (4.5 MB)
FAILED_STATES = {"FAILED", "ABORTING", "ABORTED", "TIMING-OUT", "TIMED-OUT"}


class ApifyError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def token() -> str:
    t = os.environ.get("APIFY_TOKEN", "").strip()
    if not t:
        raise ApifyError("APIFY_TOKEN belum diatur di Environment Variables Vercel.", 500)
    return t


def apify_json(method: str, path: str, body: dict | None = None, timeout: int = 25):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        APIFY + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        # Ambil tipe & pesan error asli dari Apify supaya penyebabnya jelas.
        err_type, err_msg = "", ""
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {})
            err_type, err_msg = str(err.get("type", "")), str(err.get("message", ""))
        except Exception:
            pass
        detail = f" [{e.code} {err_type}] {err_msg}".rstrip()
        print("apify http error:", e.code, err_type, err_msg[:300])
        if e.code == 401:
            raise ApifyError("Token Apify tidak valid." + detail, 502)
        if e.code == 404:
            raise ApifyError("Data Apify tidak ditemukan (run kedaluwarsa atau ID salah)." + detail, 404)
        if e.code == 429:
            raise ApifyError("Terlalu banyak permintaan ke Apify. Coba lagi sebentar." + detail, 429)
        raise ApifyError("Apify menolak permintaan." + detail, 502)
    except (URLError, TimeoutError):
        raise ApifyError("Tidak bisa menghubungi Apify. Coba lagi.", 504)


class handler(BaseHTTPRequestHandler):
    # ---------- helpers ----------
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _same_origin(self) -> bool:
        """Cegah situs lain memakai endpoint (dan kuota Apify) kamu."""
        site = self.headers.get("Sec-Fetch-Site")
        if site:
            return site == "same-origin"
        host = self.headers.get("Host", "")
        for name in ("Origin", "Referer"):
            value = self.headers.get(name)
            if value:
                return urlparse(value).netloc == host
        return False

    # ---------- GET ----------
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)

            if not query:
                return self._json(200, {"ok": True, "service": "youtube_audio", "provider": "apify"})

            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})

            if "run" in query:
                return self._run_status(query["run"][0])
            if "file" in query:
                return self._proxy_file(query["file"][0])
            return self._json(400, {"error": "Request tidak valid."})
        except ApifyError as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    def _run_status(self, run_id: str):
        if not RUN_ID_RE.match(run_id):
            return self._json(400, {"error": "Run ID tidak valid."})

        run = apify_json("GET", f"/actor-runs/{run_id}")["data"]
        status = run.get("status", "UNKNOWN")

        if status in FAILED_STATES:
            return self._json(502, {
                "status": status,
                "error": "Apify gagal memproses video (mungkin dibatasi, privat, atau tidak tersedia).",
            })
        if status != "SUCCEEDED":
            return self._json(200, {"status": status})

        dataset_id = run.get("defaultDatasetId")
        items = apify_json("GET", f"/datasets/{dataset_id}/items?clean=true&limit=1") if dataset_id else []
        item = items[0] if isinstance(items, list) and items else {}
        file_url = item.get("fileUrl")
        if not file_url:
            return self._json(502, {
                "status": status,
                "error": "Apify selesai tetapi tidak mengembalikan file MP3 untuk video ini.",
            })

        info = item.get("information") or {}
        try:
            duration = int(info.get("lengthSeconds") or 0)
        except (TypeError, ValueError):
            duration = 0
        self._json(200, {
            "status": "SUCCEEDED",
            "fileUrl": file_url,
            "title": info.get("title") or "youtube-audio",
            "duration": duration,
        })

    def _proxy_file(self, file_url: str):
        parsed = urlparse(file_url)
        if (parsed.scheme != "https" or parsed.hostname != "api.apify.com"
                or not parsed.path.startswith("/v2/key-value-stores/")):
            return self._json(400, {"error": "URL file tidak valid."})

        req = Request(file_url, headers={"Authorization": f"Bearer {token()}"})
        try:
            with urlopen(req, timeout=40) as resp:
                content_type = resp.headers.get("Content-Type", "audio/mpeg")
                data = resp.read(MAX_PROXY_BYTES + 1)
        except (HTTPError, URLError, TimeoutError):
            return self._json(502, {"error": "Gagal mengunduh file MP3 dari Apify."})

        if len(data) > MAX_PROXY_BYTES:
            return self._json(413, {
                "error": "File MP3 lebih dari 4.4 MB sehingga tidak bisa lewat Vercel. "
                         "Buka link langsung dari Apify atau gunakan video yang lebih pendek."
            })
        if not content_type.startswith("audio/"):
            content_type = "audio/mpeg"
        self._send(200, data, content_type)

    # ---------- POST ----------
    def do_POST(self):
        try:
            if not self._same_origin():
                return self._json(403, {"error": "Akses ditolak."})

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                return self._json(400, {"error": "Request tidak valid."})

            payload = json.loads(self.rfile.read(length))
            url = (payload.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HOSTS:
                return self._json(400, {"error": "Masukkan URL YouTube yang valid."})

            proxy = {"useApifyProxy": True}
            groups = [g.strip() for g in os.environ.get("APIFY_PROXY_GROUPS", "").split(",") if g.strip()]
            if groups:
                proxy["apifyProxyGroups"] = groups

            run = apify_json("POST", f"/actors/{ACTOR}/runs", {
                "youtubeUrls": [{"url": url}],
                "includeInfo": True,
                "maxRequestRetries": 25,
                "proxyConfiguration": proxy,
            })["data"]
            self._json(200, {"runId": run["id"], "status": run.get("status", "READY")})
        except ApifyError as e:
            self._json(e.status, {"error": str(e)})
        except (ValueError, KeyError):
            self._json(400, {"error": "Request tidak valid."})
        except Exception as e:
            print("unexpected error:", repr(e))
            self._json(500, {"error": "Terjadi kesalahan di server."})

    def log_message(self, format, *args):
        # Jangan log URL YouTube atau token.
        return
