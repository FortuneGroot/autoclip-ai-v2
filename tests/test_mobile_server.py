"""Local mobile HTTP contract: auth, validation, preview, and downloads."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import mobile_server


class MobileServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.patch = patch.object(mobile_server, "OUTPUT", self.output)
        self.patch.start()
        self.upload_patch = patch.object(mobile_server, "UPLOADS", self.output / "uploads")
        self.upload_patch.start()
        self.server = mobile_server.create_server("127.0.0.1", 0, key="test-key-12345678901234567890")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.key = "key=test-key-12345678901234567890"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.patch.stop()
        self.upload_patch.stop()
        self.temp.cleanup()

    def request(self, path: str, body: dict | None = None, headers: dict | None = None,
                method: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json"} if body is not None else {}
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_auth_validation_and_home_screen(self) -> None:
        self.assertEqual(self.request("/api/status")[0], 403)
        self.assertEqual(self.request(f"/?{self.key}")[0], 200)
        status, _, manifest = self.request(f"/manifest.webmanifest?{self.key}")
        self.assertEqual(status, 200)
        self.assertIn(self.key, json.loads(manifest)["start_url"])
        self.assertEqual(self.request(f"/api/jobs?{self.key}", {"url": "https://example.com/a"})[0], 400)
        self.assertEqual(self.request(f"/api/jobs?{self.key}", {"url": "file:///C:/secret.mp4"})[0], 400)

    def test_manifest_media_range_and_zip(self) -> None:
        folder = self.output / "2026-10-14_12-00-00"
        folder.mkdir()
        video = folder / "01_Good_Clip.mp4"
        poster = folder / "01_Good_Clip.png"
        video.write_bytes(b"0123456789")
        poster.write_bytes(b"pngbytes")
        (folder / "social_captions.txt").write_text("Caption", encoding="utf-8")
        (folder / "clips.json").write_text(json.dumps({"source_title": "A sample",
            "selection_mode": "heuristic", "clips": [{"rank": 1, "title": "Good clip", "file": str(video),
            "thumbnail": str(poster), "duration": 20.0, "score": 10, "social_caption": "Caption"}]}), encoding="utf-8")
        status, _, data = self.request(f"/api/jobs?{self.key}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["jobs"][0]["clips"][0]["title"], "Good clip")
        path = f"/api/jobs/{folder.name}/clips/1.mp4?{self.key}"
        status, headers, data = self.request(path, headers={"Range": "bytes=2-5"})
        self.assertEqual((status, data), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(self.request(f"/api/jobs/{folder.name}/all.zip?{self.key}")[0], 200)
        self.assertEqual(self.request(f"/api/jobs/..%2F..%2Fsecret/clips/1.mp4?{self.key}")[0], 404)

    def test_local_video_upload_boundary(self) -> None:
        body = b"sample video bytes"
        headers = {"Content-Type": "application/octet-stream", "X-Video-Extension": ".mp4"}
        request = urllib.request.Request(self.base + "/api/upload", data=body, headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(denied.exception.code, 403)
        bad = urllib.request.Request(self.base + f"/api/upload?{self.key}", data=body,
                                     headers={**headers, "X-Video-Extension": ".exe"})
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(bad, timeout=5)
        self.assertEqual(rejected.exception.code, 400)
        with patch.object(mobile_server.JobState, "launch_reserved") as launch:
            valid = urllib.request.Request(self.base + f"/api/upload?{self.key}", data=body, headers=headers)
            with urllib.request.urlopen(valid, timeout=5) as response:
                self.assertEqual(response.status, 202)
            self.assertEqual(launch.call_count, 1)
            path = Path(launch.call_args.args[0])
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(path.parent, mobile_server.UPLOADS)

    def test_guided_clip_seventeen_is_visible_and_downloadable(self) -> None:
        folder = self.output / "2026-10-17_12-59-30_guided"
        folder.mkdir()
        clips = []
        for rank in range(1, 18):
            video = folder / f"{rank:02d}_Clip.mp4"
            poster = folder / f"{rank:02d}_Clip.png"
            video.write_bytes(f"video{rank}".encode())
            poster.write_bytes(b"poster")
            clips.append({"rank": rank, "title": f"Clip {rank}", "file": str(video),
                          "thumbnail": str(poster), "duration": 30, "score": 75})
        (folder / "clips.json").write_text(json.dumps({"requested_markers": list(range(17)),
            "clips": clips}), encoding="utf-8")
        status, _, payload = self.request(f"/api/jobs?{self.key}")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(payload)["jobs"][0]["clips"]), 17)
        self.assertEqual(self.request(f"/api/jobs/{folder.name}/clips/17.mp4?{self.key}")[0], 200)
        self.assertEqual(self.request(f"/api/jobs/{folder.name}/all.zip?{self.key}")[0], 200)

    def test_refine_saved_job_validates_markers_and_source(self) -> None:
        folder = self.output / "2026-10-17_10-00-00"
        folder.mkdir()
        (folder / "source.mp4").write_bytes(b"source")
        (folder / "clips.json").write_text(json.dumps({"clips": []}), encoding="utf-8")
        (folder / "transcript_words.json").write_text(json.dumps([
            {"start": 0.0, "end": 100.0, "text": "A complete idea"}]), encoding="utf-8")
        path = f"/api/jobs/{folder.name}/refine?{self.key}"
        self.assertEqual(self.request(path, {"timestamps": "bad"})[0], 400)
        self.assertEqual(self.request(path, {"timestamps": "2:00"})[0], 400)
        with patch.object(mobile_server.JobState, "start_refine", return_value=True) as start:
            self.assertEqual(self.request(path, {"timestamps": "1:00"})[0], 202)
            self.assertEqual(start.call_args.args, (folder, "1:00"))
        (folder / "source.mp4").unlink()
        self.assertEqual(self.request(path, {"timestamps": "1:00"})[0], 400)

    def test_hidden_test_jobs_and_safe_deletion(self) -> None:
        parent = self.output / "2026-10-17_10-00-00"
        child = self.output / "2026-10-17_10-01-00_refined"
        test_job = self.output / "2026-10-14_10-00-00"
        for folder in (parent, child, test_job):
            folder.mkdir()
        (parent / "source.mp4").write_bytes(b"source")
        (parent / "clips.json").write_text(json.dumps({"source": "https://youtu.be/example", "clips": []}), encoding="utf-8")
        (child / "clips.json").write_text(json.dumps({"source_media_path": str(parent / "source.mp4"), "clips": []}), encoding="utf-8")
        (test_job / "clips.json").write_text(json.dumps({"clips": []}), encoding="utf-8")
        (test_job / ".test_job").write_text("test", encoding="utf-8")
        status, _, payload = self.request(f"/api/jobs?{self.key}")
        self.assertEqual(status, 200)
        names = [job["job"] for job in json.loads(payload)["jobs"]]
        self.assertEqual(set(names), {parent.name, child.name})
        self.assertEqual(self.request(f"/api/jobs/{parent.name}?{self.key}", method="DELETE")[0], 409)
        self.server.RequestHandlerClass.jobs.state["status"] = "running"
        self.assertEqual(self.request(f"/api/jobs/{child.name}?{self.key}", method="DELETE")[0], 409)
        self.server.RequestHandlerClass.jobs.state["status"] = "idle"
        self.assertEqual(self.request(f"/api/jobs/{child.name}?{self.key}", method="DELETE")[0], 200)
        self.assertEqual(self.request(f"/api/jobs/{parent.name}?{self.key}", method="DELETE")[0], 200)
        self.assertFalse(parent.exists())
        self.assertTrue(test_job.exists())
        self.assertEqual(self.request(f"/api/jobs/..%2Fother?{self.key}", method="DELETE")[0], 404)

    def test_source_key_groups_youtube_timestamp_variants(self) -> None:
        self.assertEqual(mobile_server.source_key("https://www.youtube.com/watch?v=abc&t=12s"),
                         mobile_server.source_key("https://youtu.be/abc?t=20"))
        self.assertNotEqual(mobile_server.source_key("https://youtu.be/abc"),
                            mobile_server.source_key("https://youtu.be/other"))

    def test_repeat_url_reuses_existing_job_until_explicit_rerun(self) -> None:
        folder = self.output / "2026-10-17_11-36-43"
        folder.mkdir()
        (folder / "clips.json").write_text(json.dumps({
            "source": "https://www.youtube.com/watch?v=abc&t=12s", "clips": []
        }), encoding="utf-8")
        path = f"/api/jobs?{self.key}"
        with patch.object(mobile_server.JobState, "start", return_value=True) as start:
            status, _, payload = self.request(path, {"url": "https://youtu.be/abc?t=20"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(payload), {"status": "existing", "job": folder.name})
            start.assert_not_called()
            self.assertEqual(self.request(path, {"url": "https://youtu.be/abc", "force": True})[0], 202)
            start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
