import json
import os
import re
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

MAX_AUDIO_BYTES = 4 * 1024 * 1024  # Keep below Vercel's 4.5 MB response limit.
MAX_DURATION_SECONDS = 5 * 60
ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]", "", value or "")
    value = value.strip(" .-_")[:80]
    return value or "youtube-audio"


class handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json(200, {
            "ok": True,
            "service": "youtube-audio",
            "limits": {
                "max_audio_mb": 4,
                "max_duration_seconds": MAX_DURATION_SECONDS
            }
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                return self._json(400, {"error": "Request tidak valid."})

            payload = json.loads(self.rfile.read(length))
            url = (payload.get("url") or "").strip()
            parsed = urlparse(url)

            if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HOSTS:
                return self._json(400, {"error": "Masukkan URL YouTube yang valid."})

            # No playlists, no external post-processing binaries.
            with tempfile.TemporaryDirectory(prefix="/tmp/youtube-audio-") as temp_dir:
                output_template = str(Path(temp_dir) / "source.%(ext)s")
                options = {
                    "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                    "outtmpl": output_template,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "restrictfilenames": True,
                    "socket_timeout": 20,
                    "retries": 1,
                    "fragment_retries": 1,
                    "max_filesize": MAX_AUDIO_BYTES,
                    "overwrites": True,
                }

                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=False)

                    duration = info.get("duration")
                    if duration and duration > MAX_DURATION_SECONDS:
                        return self._json(
                            413,
                            {"error": "Video terlalu panjang. Maksimal 5 menit."}
                        )

                    info = ydl.extract_info(url, download=True)
                    requested = info.get("requested_downloads") or []
                    downloaded_path = None
                    if requested:
                        downloaded_path = requested[0].get("filepath")

                    if not downloaded_path or not os.path.isfile(downloaded_path):
                        # Fallback for yt-dlp versions that do not populate filepath.
                        candidates = list(Path(temp_dir).glob("source.*"))
                        candidates = [p for p in candidates if p.is_file()]
                        if candidates:
                            downloaded_path = str(candidates[0])

                    if not downloaded_path or not os.path.isfile(downloaded_path):
                        return self._json(502, {"error": "Audio YouTube gagal diunduh."})

                    size = os.path.getsize(downloaded_path)
                    if size > MAX_AUDIO_BYTES:
                        return self._json(
                            413,
                            {"error": "Ukuran audio melebihi batas 4 MB. Coba video yang lebih pendek."}
                        )

                    extension = Path(downloaded_path).suffix.lower()
                    mime_types = {
                        ".m4a": "audio/mp4",
                        ".webm": "audio/webm",
                        ".opus": "audio/ogg",
                        ".ogg": "audio/ogg",
                        ".mp3": "audio/mpeg",
                    }
                    content_type = mime_types.get(extension, "application/octet-stream")
                    filename = safe_filename(info.get("title")) + (extension or ".m4a")

                    with open(downloaded_path, "rb") as audio_file:
                        audio_data = audio_file.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(audio_data)))
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("X-Audio-Filename", filename)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio_data)

        except Exception as exc:
            # Do not expose stack traces or server internals to visitors.
            message = str(exc)
            if "Private video" in message:
                message = "Video bersifat privat dan tidak dapat diakses."
            elif "Sign in" in message or "login" in message.lower():
                message = "Video membutuhkan login atau memiliki pembatasan akses."
            elif "Unsupported URL" in message:
                message = "URL YouTube tidak didukung."
            else:
                message = "Gagal mengambil audio. Video mungkin dibatasi, tidak tersedia, atau YouTube menolak permintaan dari server."
            self._json(422, {"error": message})

    def log_message(self, format, *args):
        # Avoid logging full YouTube URLs or request payloads.
        return
