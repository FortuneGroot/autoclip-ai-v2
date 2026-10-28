"""Local-network iPhone interface for AUTOCLIP AI.

Only the Windows process runs the media pipeline. The HTTP surface accepts
YouTube URLs and serves files named in completed manifests, never paths from
the client.
"""
from __future__ import annotations

import json
import hashlib
import math
import shutil
import secrets
import socket
import threading
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from analysis.revise_job import parse_markers, revise
from pipeline import process, validate_youtube_url

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "mobile"
OUTPUT = ROOT / "output" / "iphone"
UPLOADS = OUTPUT / "uploads"
SECRET_FILE = ROOT / ".mobile_secret"
PORT = 8765
MAX_BODY = 8192
MAX_UPLOAD = 10 * 1024 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
ARCHIVE_LOCK = threading.Lock()


def access_key() -> str:
    if SECRET_FILE.is_file():
        key = SECRET_FILE.read_text(encoding="ascii").strip()
        if len(key) >= 24 and all(c.isalnum() or c in "_-" for c in key):
            return key
        raise RuntimeError("The mobile access key file is invalid")
    key = secrets.token_urlsafe(24)
    SECRET_FILE.write_text(key, encoding="ascii")
    return key


def local_ipv4() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
    for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = entry[4][0]
        if not ip.startswith(("127.", "169.254.")):
            return ip
    raise RuntimeError("No Wi-Fi or Ethernet IPv4 address was found")


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, object] = {"status": "idle", "message": "Ready", "progress": 0.0}

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return dict(self.state)

    def start(self, source: str) -> bool:
        if not self.reserve("Starting"):
            return False
        self.launch_reserved(source)
        return True

    def start_refine(self, folder: Path, markers: str) -> bool:
        if not self.reserve("Refining saved video from your timestamps"):
            return False
        threading.Thread(target=self._run_refine, args=(folder, markers), daemon=True).start()
        return True

    def reserve(self, message: str) -> bool:
        with self.lock:
            if self.state.get("status") == "running":
                return False
            self.state = {"status": "running", "message": str(message)[:300], "progress": 0.0}
            return True

    def launch_reserved(self, source: str, temporary: bool = False) -> None:
        threading.Thread(target=self._run, args=(source, temporary), daemon=True).start()

    def fail_reserved(self, message: str) -> None:
        with self.lock:
            self.state = {"status": "error", "message": str(message)[:1000], "progress": 0.0}

    def _run(self, source: str, temporary: bool = False) -> None:
        def report(message: str, progress_value: float) -> None:
            with self.lock:
                self.state.update(message=str(message)[:300],
                                  progress=max(0.0, min(1.0, float(progress_value))))
        try:
            folder = process(source, OUTPUT, report)
            with self.lock:
                self.state = {"status": "done", "message": "Clips ready", "progress": 1.0,
                              "job": folder.name}
        except Exception as exc:
            with self.lock:
                self.state = {"status": "error", "message": str(exc)[:1000], "progress": 0.0}
        finally:
            if temporary:
                path = Path(source).resolve()
                if path.parent == UPLOADS.resolve():
                    path.unlink(missing_ok=True)

    def _run_refine(self, folder: Path, markers: str) -> None:
        def report(message: str, progress_value: float) -> None:
            with self.lock:
                self.state.update(message=str(message)[:300],
                                  progress=max(0.0, min(1.0, float(progress_value))))
        try:
            result = revise(folder, markers, report)
            with self.lock:
                self.state = {"status": "done", "message": "Refined clips ready", "progress": 1.0,
                              "job": result.name}
        except Exception as exc:
            with self.lock:
                self.state = {"status": "error", "message": str(exc)[:1000], "progress": 0.0}


def safe_job(name: str) -> Path | None:
    if not name or len(name) > 80 or not all(c.isalnum() or c in "_-" for c in name):
        return None
    folder = OUTPUT / name
    try:
        if (folder.resolve().parent != OUTPUT.resolve() or folder.is_symlink() or
                getattr(folder, "is_junction", lambda: False)()):
            return None
    except OSError:
        return None
    if folder.is_dir() and (folder / "clips.json").is_file():
        return folder
    return None


def source_key(value: object) -> str:
    """Opaque library grouping key; never send local source paths to browsers."""
    raw = value if isinstance(value, str) else ""
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        identity = "youtube:" + parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                  "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        identity = "youtube:" + video_id if video_id else raw
    else:
        identity = raw
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def existing_job_for_url(url: str) -> str | None:
    if not OUTPUT.is_dir():
        return None
    wanted = source_key(url)
    for folder in sorted(OUTPUT.iterdir(), key=lambda item: item.name, reverse=True):
        if safe_job(folder.name) is None or (folder / ".test_job").exists():
            continue
        try:
            data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
            if (isinstance(data, dict) and not data.get("parent_job") and
                    source_key(data.get("source")) == wanted):
                return folder.name
        except (OSError, ValueError, TypeError):
            continue
    return None


def job_manifest(name: str) -> dict[str, object] | None:
    folder = safe_job(name)
    if folder is None:
        return None
    try:
        data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
            return None
        clips: list[dict[str, object]] = []
        max_rank = 100 if isinstance(data.get("requested_markers"), list) and data["requested_markers"] else 10
        for entry in data["clips"]:
            if not isinstance(entry, dict):
                continue
            rank = entry.get("rank")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1 or rank > max_rank:
                continue
            duration = entry.get("duration")
            score = entry.get("score")
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or not 10 <= duration <= 40:
                continue
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
                continue
            reasons = entry.get("score_reasons", [])
            if not isinstance(reasons, list):
                reasons = []
            clips.append({
                "rank": rank, "title": str(entry.get("title", "Clip"))[:180],
                "social_caption": str(entry.get("social_caption", ""))[:2000],
                "duration": duration, "score": score,
                "score_reasons": [str(reason)[:120] for reason in reasons[:20]],
                "video_url": f"/api/jobs/{quote(name)}/clips/{rank}.mp4",
                "poster_url": f"/api/jobs/{quote(name)}/clips/{rank}.png",
            })
        source_value = data.get("source_media_path", str(folder / "source.mp4"))
        source_path = Path(source_value).resolve() if isinstance(source_value, str) else None
        can_refine = bool(source_path and source_path.name == "source.mp4" and
                          source_path.parent.parent == OUTPUT.resolve() and source_path.is_file() and
                          (folder / "transcript_words.json").is_file())
        return {"job": name, "source_title": str(data.get("source_title", "Video"))[:300],
                "selection_mode": str(data.get("selection_mode", ""))[:100], "clips": clips,
                "source_key": source_key(data.get("source")),
                "can_refine": can_refine,
                "download_all_url": f"/api/jobs/{quote(name)}/all.zip"}
    except (OSError, ValueError, TypeError):
        return None


def media_path(name: str, rank: int, suffix: str) -> Path | None:
    folder = safe_job(name)
    if folder is None or rank < 1 or rank > 100 or suffix not in {"mp4", "png"}:
        return None
    try:
        data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
        entry = next((x for x in data["clips"] if isinstance(x, dict) and x.get("rank") == rank), None)
        if entry is None:
            return None
        field = "file" if suffix == "mp4" else "thumbnail"
        path = Path(entry[field]).resolve(strict=True)
        if path.parent != folder.resolve() or path.suffix.lower() != f".{suffix}":
            return None
        return path
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None


def archive_path(name: str) -> Path | None:
    folder = safe_job(name)
    if folder is None:
        return None
    manifest = job_manifest(name)
    if manifest is None:
        return None
    archive = folder / "AUTOCLIP_AI_clips.zip"
    with ARCHIVE_LOCK:
        if archive.is_file():
            return archive
        temporary = folder / "AUTOCLIP_AI_clips.partial"
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as out:
                for clip in manifest["clips"]:
                    path = media_path(name, int(clip["rank"]), "mp4")
                    if path is None:
                        raise OSError("Clip missing")
                    out.write(path, path.name)
                caption_file = folder / "social_captions.txt"
                if caption_file.is_file():
                    out.write(caption_file, caption_file.name)
            temporary.replace(archive)
            return archive
        except (OSError, ValueError, zipfile.BadZipFile):
            temporary.unlink(missing_ok=True)
            return None


class Handler(BaseHTTPRequestHandler):
    server_version = "AUTOCLIP-AI/1"
    key: str = ""
    jobs: JobState

    def log_message(self, format: str, *args: object) -> None:
        # Request paths carry the access key; do not write them to a console or log.
        pass

    def _authorized(self) -> bool:
        values = parse_qs(urlsplit(self.path).query).get("key", [])
        return len(values) == 1 and secrets.compare_digest(values[0], self.key)

    def _headers(self, status: int, content_type: str, length: int,
                 extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if extra:
            for name, value in extra.items():
                self.send_header(name, value)
        self.end_headers()

    def _json(self, status: int, data: dict[str, object]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _file(self, path: Path, mime: str, download: str | None = None) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range", "")
        if requested:
            import re
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            if not match:
                self._headers(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, mime, 0,
                              {"Content-Range": f"bytes */{size}"})
                return
            start = int(match.group(1))
            end = min(size - 1, int(match.group(2))) if match.group(2) else size - 1
            if start >= size or end < start:
                self._headers(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, mime, 0,
                              {"Content-Range": f"bytes */{size}"})
                return
        headers = {"Accept-Ranges": "bytes"}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{download}"'
        if requested:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._headers(HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK,
                      mime, end - start + 1, headers)
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route == "/setup" and self.client_address[0] in {"127.0.0.1", "::1"}:
            self._setup()
            return
        public_static = {"/app.js": ("app.js", "text/javascript; charset=utf-8"),
                         "/style.css": ("style.css", "text/css; charset=utf-8"),
                         "/icon.svg": ("icon.svg", "image/svg+xml"),
                         "/icon.png": ("icon.png", "image/png")}
        if route in public_static:
            filename, mime = public_static[route]
            self._file(WEB / filename, mime)
            return
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Access key required. Scan the QR code on the Windows setup page."})
            return
        if route == "/api/status":
            self._json(HTTPStatus.OK, self.jobs.snapshot())
            return
        if route == "/manifest.webmanifest":
            manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
            manifest["start_url"] = f"/?key={quote(self.key)}"
            payload = json.dumps(manifest).encode("utf-8")
            self._headers(HTTPStatus.OK, "application/manifest+json", len(payload))
            self.wfile.write(payload)
            return
        if route == "/api/jobs":
            names = [p.name for p in OUTPUT.iterdir() if p.is_dir() and safe_job(p.name) and
                     not (p / ".test_job").exists()] if OUTPUT.is_dir() else []
            self._json(HTTPStatus.OK, {"jobs": [item for name in sorted(names, reverse=True)[:20]
                                                if (item := job_manifest(name)) is not None]})
            return
        parts = route.strip("/").split("/")
        if len(parts) == 5 and parts[:2] == ["api", "jobs"] and parts[3] == "clips":
            name, filename = parts[2], parts[4]
            import re
            match = re.fullmatch(r"([1-9][0-9]{0,2})\.(mp4|png)", filename)
            if match:
                suffix = match.group(2)
                path = media_path(name, int(match.group(1)), suffix)
                if path is not None:
                    self._file(path, "video/mp4" if suffix == "mp4" else "image/png",
                               path.name if suffix == "mp4" and parse_qs(urlsplit(self.path).query).get("download") == ["1"] else None)
                    return
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "all.zip":
            path = archive_path(parts[2])
            if path is not None:
                self._file(path, "application/zip", path.name)
                return
        if route == "/":
            payload = (WEB / "index.html").read_text(encoding="utf-8").replace("__KEY__", quote(self.key)).encode("utf-8")
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(payload))
            self.wfile.write(payload)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route == "/api/upload":
            self._upload()
            return
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Access key required"})
            return
        parts = route.strip("/").split("/")
        refine_name = parts[2] if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "refine" else None
        if route != "/api/jobs" and refine_name is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        raw_size = self.headers.get("Content-Length", "")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send JSON with a YouTube URL"})
            return
        if not raw_size.isdigit() or not 0 < int(raw_size) <= MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size"})
            return
        try:
            data = json.loads(self.rfile.read(int(raw_size)))
            if not isinstance(data, dict):
                raise ValueError("Send a JSON object")
            if refine_name is None:
                if not isinstance(data.get("url"), str):
                    raise ValueError("Enter a YouTube URL")
                url = validate_youtube_url(data["url"])
                if not isinstance(data.get("force", False), bool):
                    raise ValueError("Invalid reprocess option")
            else:
                folder = safe_job(refine_name)
                if folder is None or not isinstance(data.get("timestamps"), str):
                    raise ValueError("Choose a saved video and enter timestamps")
                manifest = job_manifest(refine_name)
                if manifest is None or not manifest["can_refine"]:
                    raise ValueError("The source video for this job is no longer available")
                transcript = json.loads((folder / "transcript_words.json").read_text(encoding="utf-8"))
                if (not isinstance(transcript, list) or not transcript or
                        not isinstance(transcript[-1], dict) or
                        isinstance(transcript[-1].get("end"), bool) or
                        not isinstance(transcript[-1].get("end"), (int, float))):
                    raise ValueError("Timed transcript is unavailable")
                parse_markers(data["timestamps"], float(transcript[-1]["end"]))
        except (ValueError, UnicodeDecodeError, OSError, TypeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if refine_name is None and not data.get("force", False):
            existing = existing_job_for_url(url)
            if existing is not None:
                self._json(HTTPStatus.OK, {"status": "existing", "job": existing})
                return
        started = self.jobs.start(url) if refine_name is None else self.jobs.start_refine(folder, data["timestamps"])
        if not started:
            self._json(HTTPStatus.CONFLICT, {"error": "A video is already processing"})
            return
        self._json(HTTPStatus.ACCEPTED, {"status": "running"})

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Access key required"})
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "jobs"]:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        folder = safe_job(parts[2])
        if folder is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Saved run not found"})
            return
        source = (folder / "source.mp4").resolve()
        dependencies = []
        if OUTPUT.is_dir():
            for other in OUTPUT.iterdir():
                if other == folder or not other.is_dir() or safe_job(other.name) is None:
                    continue
                try:
                    data = json.loads((other / "clips.json").read_text(encoding="utf-8"))
                    path = data.get("source_media_path") if isinstance(data, dict) else None
                    if isinstance(path, str) and Path(path).resolve() == source:
                        dependencies.append(other.name)
                except (OSError, ValueError, TypeError):
                    continue
        if dependencies:
            self._json(HTTPStatus.CONFLICT, {"error": "This source is used by refined runs. Delete those runs first."})
            return
        with self.jobs.lock:
            if self.jobs.state.get("status") == "running":
                self._json(HTTPStatus.CONFLICT, {"error": "Wait for the current video to finish before deleting."})
                return
            try:
                shutil.rmtree(folder)
            except OSError as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Could not delete this run: {exc}"})
                return
        self._json(HTTPStatus.OK, {"deleted": parts[2]})

    def _upload(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Access key required"})
            return
        raw_size = self.headers.get("Content-Length", "")
        if not raw_size.isdigit() or not 0 < int(raw_size) <= MAX_UPLOAD:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Select a video under 10 GB"})
            return
        size = int(raw_size)
        suffix = self.headers.get("X-Video-Extension", "").lower()
        if suffix not in VIDEO_SUFFIXES:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Choose an MP4, MOV, MKV, WEBM, or M4V video"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Upload a video file"})
            return
        UPLOADS.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(UPLOADS).free < size + 512 * 1024 * 1024:
            self._json(HTTPStatus.INSUFFICIENT_STORAGE, {"error": "Not enough disk space on Windows for this video"})
            return
        if not self.jobs.reserve("Uploading video from iPhone"):
            self._json(HTTPStatus.CONFLICT, {"error": "A video is already processing"})
            return
        target = UPLOADS / f"{secrets.token_urlsafe(18)}{suffix}"
        try:
            remaining = size
            with target.open("xb") as output:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("Upload connection ended before the video finished")
                    output.write(chunk)
                    remaining -= len(chunk)
                    with self.jobs.lock:
                        self.jobs.state["progress"] = 0.04 * (size - remaining) / size
            self.jobs.launch_reserved(str(target), temporary=True)
            self._json(HTTPStatus.ACCEPTED, {"status": "running"})
        except OSError as exc:
            target.unlink(missing_ok=True)
            self.jobs.fail_reserved(f"Upload failed: {exc}")
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Upload interrupted. Try again on the same Wi-Fi."})

    def _setup(self) -> None:
        import io
        import qrcode
        ip = local_ipv4()
        url = f"http://{ip}:{PORT}/?key={quote(self.key)}"
        qr = qrcode.make(url)
        svg = io.BytesIO()
        # Pillow QR is embedded as PNG data so setup has no external assets.
        qr.save(svg, format="PNG")
        import base64
        encoded = base64.b64encode(svg.getvalue()).decode("ascii")
        from html import escape
        body = f"""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>
        <title>AUTOCLIP AI iPhone setup</title><style>body{{font:18px system-ui;background:#101827;color:white;max-width:640px;margin:6vh auto;padding:24px}}img{{width:280px;max-width:80%;background:white;padding:15px;border-radius:18px}}a{{color:#6ee7d2;overflow-wrap:anywhere}}p{{line-height:1.5}}</style>
        <h1>AUTOCLIP AI for iPhone</h1><p>Connect your iPhone to the same Wi-Fi, then scan this code with the Camera app. You may close this setup page; the server keeps running until Windows signs out or restarts.</p>
        <img alt='iPhone access QR code' src='data:image/png;base64,{encoded}'><p><a href='{escape(url)}'>{escape(url)}</a></p>
        <p>In Safari, tap Share → Add to Home Screen → Open as Web App.</p><p>If the phone cannot connect, allow Python on your local network in Windows Firewall.</p>""".encode("utf-8")
        self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
        self.wfile.write(body)


def create_server(host: str = "0.0.0.0", port: int = PORT,
                  key: str | None = None, jobs: JobState | None = None) -> ThreadingHTTPServer:
    if not isinstance(host, str) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Invalid server address")
    class BoundHandler(Handler):
        pass
    BoundHandler.key = key if key is not None else access_key()
    BoundHandler.jobs = jobs if jobs is not None else JobState()
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    return server


def main() -> None:
    server = create_server()
    ip = local_ipv4()
    print(f"AUTOCLIP AI for iPhone is running at http://{ip}:{PORT}/", flush=True)
    print("Open http://127.0.0.1:8765/setup on this Windows computer for the QR code.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
