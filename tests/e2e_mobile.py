"""Exercise the mobile job runner and HTTP delivery with real media processing."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mobile_server
from mobile_server import JobState, create_server
from pipeline import _video_dimensions, _video_duration, ffmpeg_path

sample = Path(__file__).resolve().parents[1] / "output" / "sample_test" / "speech_sample.mp4"
if not sample.is_file():
    raise SystemExit(f"Missing sample video: {sample}")
mobile_server.OUTPUT = Path(__file__).resolve().parents[1] / "output" / "test_runs" / "mobile"
mobile_server.UPLOADS = mobile_server.OUTPUT / "uploads"
jobs = JobState()
server = create_server("127.0.0.1", 0, key="mobile-e2e-test-key", jobs=jobs)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"

def fetch(path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(base + path + "?key=mobile-e2e-test-key", headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.read()

try:
    assert jobs.start(str(sample))
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = jobs.snapshot()
        print(f"{state['status']}: {state['message']}", flush=True)
        if state["status"] == "done":
            break
        if state["status"] == "error":
            raise RuntimeError(state["message"])
        time.sleep(5)
    else:
        raise TimeoutError("Mobile pipeline did not finish within 10 minutes")
    status, data = fetch("/api/jobs")
    assert status == 200
    listing = json.loads(data)["jobs"]
    job = next(item for item in listing if item["job"] == state["job"])
    assert job["clips"], "No clips returned"
    folder = mobile_server.OUTPUT / state["job"]
    for clip in job["clips"]:
        rank = clip["rank"]
        status, prefix = fetch(f"/api/jobs/{state['job']}/clips/{rank}.mp4", {"Range": "bytes=0-31"})
        assert status == 206 and len(prefix) == 32 and b"ftyp" in prefix
        path = next(folder.glob(f"{rank:02d}_*.mp4"))
        assert _video_dimensions(ffmpeg_path(), path) == (1080, 1920)
        assert 10 <= _video_duration(ffmpeg_path(), path) <= 40
        assert clip["social_caption"]
    status, archive = fetch(f"/api/jobs/{state['job']}/all.zip")
    assert status == 200 and archive[:2] == b"PK"
    print(f"PASS: {len(job['clips'])} real captioned vertical MP4(s), HTTP preview, ZIP export")
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
