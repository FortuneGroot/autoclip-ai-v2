"""Render improved clip drafts from an existing AUTOCLIP AI transcription.

This leaves the original job untouched and avoids downloading or transcribing
the long video again. The new folder appears in the mobile app's library.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Candidate, Word, MAX_SECONDS, WEAK_END, generate_candidates, normalize, select_clips  # noqa: E402
from pipeline import _ollama_scores, _render, _video_dimensions, ffmpeg_path  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
JOBS = (ROOT / "output" / "iphone").resolve()
Progress = Callable[[str, float], None]


def parse_markers(raw: str, duration: float) -> list[float]:
    if (not isinstance(raw, str) or isinstance(duration, bool) or
            not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
        raise ValueError("Invalid timestamps or video duration")
    if not raw.strip() or len(raw) > 4000:
        raise ValueError("Enter up to 100 timestamps, such as 12.45, 15, or 1:02:15")
    parts = [part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip()]
    if not 1 <= len(parts) <= 100:
        raise ValueError("Enter one to 100 timestamps")
    result: list[float] = []
    for part in parts:
        if not re.fullmatch(r"\d{1,3}(?:[.:]\d{1,2}){0,2}", part):
            raise ValueError(f"Invalid timestamp: {part[:30]}. Use 12.45, 15, or 1:02:15")
        numbers = [int(value) for value in re.split(r"[.:]", part)]
        if any(value >= 60 for value in numbers[1:]):
            raise ValueError(f"Invalid minutes or seconds: {part[:30]}")
        seconds = (numbers[0] * 60 if len(numbers) == 1 else
                   numbers[0] * 60 + numbers[1] if len(numbers) == 2 else
                   numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
        if not 0 <= seconds <= duration:
            end_time = f"{int(duration // 3600)}:{int(duration // 60) % 60:02d}:{int(duration) % 60:02d}"
            raise ValueError(f"{part[:30]} is outside this video. The recording ends at {end_time}.")
        if any(abs(seconds - previous) < 10 for previous in result):
            raise ValueError("Timestamps must be at least ten seconds apart")
        result.append(float(seconds))
    return result


def _continue_thought(candidate: Candidate, words: list[Word]) -> Candidate:
    """Favor a complete later pause for a guided moment that ended early."""
    if candidate.end - candidate.start >= 32:
        return candidate
    subsequent = [index for index, word in enumerate(words)
                  if candidate.end < word.end <= candidate.start + MAX_SECONDS + 1.5]
    boundaries: list[int] = []
    for index in subsequent:
        next_gap = words[index + 1].start - words[index].end if index + 1 < len(words) else 9.0
        if next_gap >= 0.45 or re.search(r"[.!?][\"']?$", words[index].text.strip()):
            boundaries.append(index)
    if not boundaries:
        return candidate
    for end_index in reversed(boundaries):
        end = words[end_index].end
        if end - candidate.end < 7:
            continue
        start_indices = [index for index, word in enumerate(words)
                         if candidate.start <= word.start <= candidate.start + 2
                         and 10.2 <= end - word.start <= MAX_SECONDS]
        if not start_indices:
            continue
        def start_quality(index: int) -> tuple[int, float]:
            token = words[index].text.strip(" .,?!\"'").lower()
            return (0 if token in WEAK_END or token in {"think", "mean"} else 1,
                    -abs(words[index].start - candidate.start))
        start_index = max(start_indices, key=start_quality)
        selected = tuple(words[start_index:end_index + 1])
        text = normalize(" ".join(word.text.strip() for word in selected))
        return Candidate(selected[0].start, selected[-1].end, text, candidate.score,
                         candidate.reasons + ("extended to finish thought",), selected)
    return candidate


def near_markers(candidates: list[Candidate], markers: list[float], limit: int = 10,
                 transcript_words: list[Word] | None = None) -> list[Candidate]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Clip limit must be from one to 100")
    if not isinstance(markers, list) or any(isinstance(mark, bool) or not isinstance(mark, (int, float))
                                            or not math.isfinite(mark) or mark < 0 for mark in markers):
        raise ValueError("Invalid guided timestamp")
    chosen: list[Candidate] = []
    for marker in markers:
        nearby = [candidate for candidate in candidates
                  if abs(candidate.start - marker) <= 15 and candidate.end >= marker]
        if not nearby:
            nearby = [candidate for candidate in candidates
                      if abs(candidate.start - marker) <= 30 and candidate.end >= marker]
        if not nearby:
            continue
        candidate = max(nearby, key=lambda item: (item.score - 1.2 * abs(item.start - marker),
                                                  -abs(item.start - marker), item.end - item.start))
        chosen.append(_continue_thought(candidate, transcript_words) if transcript_words is not None else candidate)
        if len(chosen) == limit:
            break
    if not chosen:
        raise ValueError("No complete 10–40 second spoken moments were found near these marks")
    return chosen


def revise(folder: Path, markers_text: str | None = None, progress: Progress | None = None) -> Path:
    report = progress if progress is not None else lambda message, fraction: print(message, flush=True)
    original = folder.resolve(strict=True)
    if not original.is_dir() or original.parent != JOBS:
        raise ValueError("Choose a completed AUTOCLIP AI mobile job folder")
    original_manifest = json.loads((original / "clips.json").read_text(encoding="utf-8"))
    if not isinstance(original_manifest, dict) or not isinstance(original_manifest.get("clips"), list):
        raise ValueError("Original job manifest is invalid")
    source_value = original_manifest.get("source_media_path", str(original / "source.mp4"))
    if not isinstance(source_value, str):
        raise ValueError("Original video path is invalid")
    source = Path(source_value).resolve(strict=True)
    if source.parent.parent != JOBS or source.name != "source.mp4" or not source.is_file():
        raise ValueError("Original downloaded video is missing")
    raw = json.loads((original / "transcript_words.json").read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Original timed transcript is missing")
    if any(not isinstance(row, dict) or isinstance(row.get("start"), bool) or
           isinstance(row.get("end"), bool) or not isinstance(row.get("start"), (int, float)) or
           not isinstance(row.get("end"), (int, float)) or not isinstance(row.get("text"), str)
           for row in raw):
        raise ValueError("Original timed transcript is invalid")
    words = [Word(row["start"], row["end"], row["text"]) for row in raw]
    candidates = generate_candidates(words)
    if markers_text is None:
        bonus, mode = _ollama_scores(candidates, report)
        identity = {id(item): index for index, item in enumerate(candidates)}
        selected = select_clips(candidates, extra_score=lambda item: bonus.get(identity[id(item)], 0.0))
    else:
        markers = parse_markers(markers_text, words[-1].end)
        selected = near_markers(candidates, markers, limit=len(markers), transcript_words=words)
        mode = "user-marked moments"
    if not selected:
        raise ValueError("No candidates met the revised quality floor")
    name = time.strftime("%Y-%m-%d_%H-%M-%S") + ("_guided" if markers_text is not None else "_refined")
    destination = JOBS / name
    suffix = 2
    while destination.exists():
        destination = JOBS / f"{name}_{suffix}"
        suffix += 1
    destination.mkdir(parents=True)
    for filename in ("transcript.txt", "transcript_words.json"):
        shutil.copy2(original / filename, destination / filename)
    dimensions = _video_dimensions(ffmpeg_path(), source)
    results: list[dict[str, object]] = []
    for index, candidate in enumerate(selected, 1):
        report(f"Rendering refined clip {index}/{len(selected)}", 0.1 + 0.85 * (index - 1) / len(selected))
        row = _render(ffmpeg_path(), source, destination, candidate, index, dimensions)
        original_score = next((c.score for c in candidates
                               if c.start == candidate.start and c.end == candidate.end), candidate.score)
        row["heuristic_score"] = original_score
        row["ollama_bonus"] = round(candidate.score - float(row["heuristic_score"]), 1)
        if markers_text is not None:
            nearest = min(markers, key=lambda mark: abs(candidate.start - mark))
            row["score_reasons"] = list(row["score_reasons"]) + [
                f"near your note at {int(nearest // 60)}:{int(nearest % 60):02d}"]
        results.append(row)
    manifest = {
        "source": original_manifest.get("source", str(source)),
        "source_title": original_manifest.get("source_title", source.stem),
        "source_media_path": str(source),
        "language": original_manifest.get("language", "unknown"),
        "selection_mode": f"revised {mode} (saved transcript)",
        "candidates_considered": len(candidates),
        "parent_job": original.name,
        "requested_markers": markers if markers_text is not None else [],
        "clips": results,
    }
    (destination / "clips.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (destination / "social_captions.txt").write_text("\n\n".join(
        f"{row['rank']:02d}. {row['title']} (score {row['score']})\n{row['social_caption']}" for row in results
    ), encoding="utf-8")
    report(f"Finished {len(results)} refined clips", 1.0)
    return destination


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: revise_job.py <completed-mobile-job-folder>")
    output = revise(Path(sys.argv[1]))
    print(f"PASS: revised clips in {output}")
