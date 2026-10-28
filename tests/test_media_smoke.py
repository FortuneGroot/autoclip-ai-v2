"""Runs media export on a generated 12-second sample. No download/model required."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import Candidate, Word
from pipeline import _render, _run, _video_dimensions, ffmpeg_path


class MediaSmokeTest(unittest.TestCase):
    def test_vertical_mp4_and_caption_export(self) -> None:
        ffmpeg = ffmpeg_path()
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "sample.mp4"
            _run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                  "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "12",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
            script = "Here is the key to testing your idea because the customer response tells you what matters most."
            parts = script.split()
            words = tuple(Word(i * 0.6, i * 0.6 + 0.45, token) for i, token in enumerate(parts))
            candidate = Candidate(0, 11.25, script, 80, ("complete ending",), words)
            result = _render(ffmpeg, source, folder, candidate, 1, _video_dimensions(ffmpeg, source))
            self.assertTrue(Path(result["file"]).is_file())
            self.assertGreater(Path(result["file"]).stat().st_size, 1000)
            self.assertTrue(Path(result["caption_file"]).is_file())
            self.assertTrue(Path(result["thumbnail"]).is_file())
            self.assertEqual(_video_dimensions(ffmpeg, Path(result["file"])), (1080, 1920))


if __name__ == "__main__":
    unittest.main()
