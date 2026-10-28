"""Small local speech-to-clips test using Windows SAPI; run after installation."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import _run, ffmpeg_path, process  # noqa: E402


def ass_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", value)
    assert match, value
    return int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3]) + int(match[4]) / 100


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "output" / "sample_test"
    root.mkdir(parents=True, exist_ok=True)
    try:
        speech = root / "speech.wav"
        sample = root / "speech_sample.mp4"
        script = ("The biggest mistake people make is trying to solve a problem before they understand it. "
                  "Here is the key lesson. Ask what happened, listen carefully to the answer, and test one small change. "
                  "Because that gives you real evidence, your next decision becomes easier. "
                  "You can repeat this process until the result improves. ") * 3
        result = subprocess.run(["powershell.exe", "-NoProfile", "-File",
                                 str(Path(__file__).with_name("synthesize.ps1")),
                                 str(speech), script], capture_output=True, text=True, check=False)
        if result.returncode or not speech.is_file():
            raise RuntimeError("Windows SAPI sample speech generation failed: " + result.stderr[-500:])
        _run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "color=c=0x243447:s=1280x720:r=30",
              "-i", str(speech), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
              "-c:a", "aac", str(sample)])
        folder = process(sample, root / "results", lambda label, fraction: print(f"{fraction:.0%} {label}"))
        manifest = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
        clips = manifest["clips"]
        assert clips, "No clips selected"
        assert all(10 <= row["duration"] <= 40 for row in clips)
        assert all(Path(row["file"]).is_file() and Path(row["thumbnail"]).is_file() for row in clips)
        transcript = (folder / "transcript.txt").read_text(encoding="utf-8").lower()
        assert "problem" in transcript and "decision" in transcript, transcript[:200]
        assert all(row["heuristic_score"] >= 62 and row["transcript_excerpt"] for row in clips)
        transcript_words = json.loads((folder / "transcript_words.json").read_text(encoding="utf-8"))
        for row in clips:
            events = [line.split(",", 9) for line in Path(row["caption_file"]).read_text(encoding="utf-8-sig").splitlines()
                      if line.startswith("Dialogue:")]
            selected_words = [w for w in transcript_words if w["end"] > row["start"] and w["start"] < row["end"]]
            assert len(events) == (len(selected_words) + 3) // 4
            for event, offset in zip(events, range(0, len(selected_words), 4)):
                group = selected_words[offset:offset + 4]
                assert abs(ass_seconds(event[1]) - max(0, group[0]["start"] - row["start"])) <= 0.02
                assert abs(ass_seconds(event[2]) - min(row["duration"], group[-1]["end"] - row["start"])) <= 0.05
                assert ass_seconds(event[2]) <= row["duration"]
        print(f"PASS: {len(clips)} speech-selected captioned MP4 clip(s); mode={manifest['selection_mode']}")
        print(f"Results: {folder}")
    finally:
        speech.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
