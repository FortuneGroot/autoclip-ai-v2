"""Local media pipeline. All subprocess arguments are passed as lists."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from core import Candidate, Word, generate_candidates, make_caption, make_title, select_clips

Progress = Callable[[str, float], None]
_windows_dll_directory = None
MODEL_DIR = Path(__file__).resolve().parent / "models"


class PipelineError(RuntimeError):
    pass


def validate_youtube_url(value: str) -> str:
    value = value.strip()
    if len(value) > 2048:
        raise ValueError("URL is too long")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in {
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be",
        "music.youtube.com", "www.youtube-nocookie.com", "youtube-nocookie.com"
    }:
        raise ValueError("Paste a valid YouTube video URL")
    if not parsed.path or parsed.path == "/":
        raise ValueError("The URL needs to identify a video")
    return value


def ffmpeg_path() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise PipelineError("FFmpeg is missing. Run Install AUTOCLIP AI.bat first.") from exc


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1500:]
        raise PipelineError(f"Media processing failed: {detail}")
    return result


def _video_dimensions(ffmpeg: str, source: Path) -> tuple[int, int]:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr)
    if not match:
        raise PipelineError("Could not read video dimensions. Try an MP4 or MOV file.")
    width, height = int(match.group(1)), int(match.group(2))
    if not (16 <= width <= 16384 and 16 <= height <= 16384):
        raise PipelineError("Video dimensions are invalid")
    return width, height


def _video_duration(ffmpeg: str, source: Path) -> float:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)", result.stderr)
    if not match:
        raise PipelineError("Could not verify exported clip duration")
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def _download(url: str, folder: Path, progress: Progress) -> tuple[Path, str]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise PipelineError("yt-dlp is missing. Run Install AUTOCLIP AI.bat first.") from exc

    def hook(data: dict) -> None:
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            done = data.get("downloaded_bytes") or 0
            if total:
                progress(f"Downloading video: {done * 100 / total:.0f}%", 0.03 + 0.12 * done / total)

    opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4", "outtmpl": str(folder / "source.%(ext)s"),
        "noplaylist": True, "restrictfilenames": True, "progress_hooks": [hook],
        "quiet": True, "no_warnings": True, "ffmpeg_location": ffmpeg_path(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        title = str(info.get("title") or "YouTube video") if isinstance(info, dict) else "YouTube video"
    except Exception as exc:
        raise PipelineError(f"Could not download this YouTube video: {exc}. You can import a local copy instead.") from exc
    matches = [p for p in folder.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not matches:
        raise PipelineError("Download completed but no video file was found. Import a local copy instead.")
    return max(matches, key=lambda p: p.stat().st_size), title


def _transcribe(ffmpeg: str, source: Path, folder: Path, progress: Progress) -> tuple[list[Word], str]:
    audio = folder / "speech.wav"
    progress("Extracting audio", 0.18)
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
          "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)])
    global _windows_dll_directory
    if os.name == "nt" and hasattr(os, "add_dll_directory") and _windows_dll_directory is None:
        local_runtime = Path(sys.prefix) / "Scripts"
        if (local_runtime / "msvcp140.dll").is_file():
            _windows_dll_directory = os.add_dll_directory(str(local_runtime))
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError("faster-whisper is missing. Run Install AUTOCLIP AI.bat first.") from exc
    progress("Loading speech model (first run may download it)", 0.22)
    total_duration = _video_duration(ffmpeg, source)
    model_name = os.environ.get("AUTOCLIP_WHISPER_MODEL", "small")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", model_name):
        raise PipelineError("Invalid AUTOCLIP_WHISPER_MODEL value")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    def decode(model: object) -> tuple[list[Word], list[str], str]:
        segments, info = model.transcribe(str(audio), beam_size=5, word_timestamps=True, vad_filter=True)
        decoded_words: list[Word] = []
        lines: list[str] = []
        last_reported = -1.0
        for segment in segments:
            lines.append(f"[{segment.start:.2f} - {segment.end:.2f}] {segment.text.strip()}")
            completed = min(1.0, max(0.0, segment.end / max(total_duration, 1.0)))
            if completed - last_reported >= 0.02:
                progress(f"Transcribing speech: {completed:.0%}", 0.27 + 0.30 * completed)
                last_reported = completed
            for item in segment.words or []:
                try:
                    decoded_words.append(Word(float(item.start), float(item.end), item.word.strip()))
                except (TypeError, ValueError):
                    continue
        return decoded_words, lines, str(getattr(info, "language", "unknown"))

    try:
        try:
            model = WhisperModel(model_name, device="auto", compute_type="int8",
                                 download_root=str(MODEL_DIR))
            progress("Transcribing the entire video", 0.27)
            words, transcript_lines, language = decode(model)
        except RuntimeError as exc:
            if not any(term in str(exc).lower() for term in ("cuda", "cublas", "cudnn")):
                raise
            progress("GPU runtime unavailable; switching to CPU", 0.27)
            model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                 download_root=str(MODEL_DIR))
            words, transcript_lines, language = decode(model)
        (folder / "transcript.txt").write_text("\n".join(transcript_lines), encoding="utf-8")
        (folder / "transcript_words.json").write_text(json.dumps([asdict(x) for x in words],
                                                         ensure_ascii=False, indent=2), encoding="utf-8")
        if not words:
            raise PipelineError("No speech was detected in this video")
        return words, language
    finally:
        audio.unlink(missing_ok=True)


def _ai_shortlist(candidates: list[Candidate], limit: int = 80) -> list[int]:
    """Sample strong, distinct moments throughout a long recording."""
    if type(limit) is not int or limit < 1:
        raise ValueError("Shortlist limit must be a positive integer")
    buckets: dict[int, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if candidate.score < 50:
            continue
        buckets.setdefault(int(candidate.start // 600), []).append(index)
    for indices in buckets.values():
        indices.sort(key=lambda i: candidates[i].score, reverse=True)
    ordered: list[int] = []
    # Give each ten-minute section a chance before filling from global rank.
    for rank in range(8):
        for bucket in sorted(buckets):
            indices = buckets[bucket]
            if rank < len(indices):
                ordered.append(indices[rank])
    ordered.extend(sorted(range(len(candidates)),
                          key=lambda i: candidates[i].score, reverse=True))
    selected: list[int] = []
    for index in ordered:
        candidate = candidates[index]
        if candidate.score < 50:
            continue
        if any(min(candidate.end, candidates[other].end) -
               max(candidate.start, candidates[other].start) > 1.0
               for other in selected):
            continue
        selected.append(index)
        if len(selected) == limit:
            break
    return selected


def _ollama_scores(candidates: list[Candidate], progress: Progress) -> tuple[dict[int, float], str]:
    """Score a bounded set of candidates; malformed/unavailable responses fall back cleanly."""
    endpoint = "http://127.0.0.1:11434"
    try:
        with urllib.request.urlopen(endpoint + "/api/tags", timeout=2) as response:
            models = json.load(response).get("models", [])
        names = [m.get("name") for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]
        if not names:
            return {}, "heuristic (Ollama has no installed model)"
        model = next((n for n in names if any(tag in n.lower() for tag in ("qwen", "llama", "mistral"))), names[0])
        scores: dict[int, float] = {}
        shortlist = _ai_shortlist(candidates)
        for offset in range(0, len(shortlist), 10):
            batch = shortlist[offset:offset + 10]
            progress(f"Reviewing content with Ollama ({offset + 1}/{len(shortlist)})", 0.62 + 0.06 * offset / max(1, len(shortlist)))
            examples = [{"id": i, "text": candidates[i].text[:700]} for i in batch]
            prompt = ("You are an editor selecting the strongest standalone spoken moments from an interview. "
                      "Rate each excerpt 0 to 20. Give 16-20 only to a memorable, specific insight or "
                      "opinion that hooks immediately, develops one complete idea, and ends naturally. "
                      "Give 10-15 to useful but ordinary content. Give 0-9 to vague chatter, "
                      "questions without answers, missing context, unfinished thoughts, or filler. "
                      "Judge the actual words, not topic popularity. Return ONLY a JSON object "
                      "with a scores array containing objects {id: integer, score: integer 0 to 20}. "
                      "Clips: " + json.dumps(examples, ensure_ascii=False))
            payload = json.dumps({"model": model, "prompt": prompt, "stream": False,
                                  "format": "json", "options": {"temperature": 0}}).encode("utf-8")
            request = urllib.request.Request(endpoint + "/api/generate", payload,
                                             {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=180) as response:
                outer = json.load(response)
            parsed = json.loads(outer.get("response", "{}"))
            for row in parsed.get("scores", []):
                if not isinstance(row, dict):
                    continue
                idx, value = row.get("id"), row.get("score")
                if type(idx) is int and idx in batch and type(value) in (int, float) and 0 <= value <= 20:
                    scores[idx] = (float(value) - 10.0) * 2.0
        return scores, f"Ollama ({model}) + heuristic" if scores else "heuristic (Ollama response unavailable)"
    except (OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {}, "heuristic (Ollama unavailable)"


def _ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    return f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _write_captions(path: Path, candidate: Candidate) -> None:
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
              "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
              "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
              "Style: Main,Arial,70,&H00FFFFFF,&H0000FFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,220,1\n\n"
              "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = [header]
    relative = [Word(max(0, w.start - candidate.start), min(candidate.end - candidate.start, w.end - candidate.start), w.text)
                for w in candidate.words if w.end > candidate.start and w.start < candidate.end]
    for i in range(0, len(relative), 4):
        chunk = relative[i:i + 4]
        if not chunk:
            continue
        start, end = chunk[0].start, chunk[-1].end
        if end <= start:
            continue
        content = _ass_escape(" ".join(w.text for w in chunk))
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{content}\n")
    path.write_text("".join(lines), encoding="utf-8-sig")


def _face_crop(source: Path, midpoint: float, width: int, height: int) -> float | None:
    """Return face x-center as a fraction; center crop remains the fallback."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(source))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, midpoint * 1000)
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4,
                                         minSize=(max(24, width // 30), max(24, height // 30)))
        if len(faces) == 0:
            return None
        x, _, w, _ = max(faces, key=lambda face: int(face[2]) * int(face[3]))
        return max(0.0, min(1.0, (int(x) + int(w) / 2) / frame.shape[1]))
    except Exception:
        return None


def _render(ffmpeg: str, source: Path, folder: Path, candidate: Candidate,
            index: int, dimensions: tuple[int, int]) -> dict:
    width, height = dimensions
    name = re.sub(r"[^A-Za-z0-9]+", "_", make_title(candidate.text)).strip("_")[:55] or "Highlight"
    stem = f"{index:02d}_{name}"
    video = folder / f"{stem}.mp4"
    caption_file = folder / f"{stem}.ass"
    thumbnail = folder / f"{stem}.png"
    _write_captions(caption_file, candidate)
    face_x = _face_crop(source, (candidate.start + candidate.end) / 2, width, height)
    center = face_x if face_x is not None else 0.5
    # Scale to 1080 high first. A broad source becomes a true crop; a narrow
    # source is padded rather than enlarged beyond its available width.
    scaled_width = width * 1920 / height
    if scaled_width >= 1080:
        crop_x = max(0, min(scaled_width - 1080, scaled_width * center - 540))
        geometry = f"scale=-2:1920,crop=1080:1920:{int(crop_x)}:0"
    else:
        geometry = "scale=1080:-2,crop=1080:1920:0:(ih-1920)/2" if height > width * 16 / 9 else "scale=1080:-2,pad=1080:1920:0:(1920-ih)/2:black"
    filters = f"{geometry},setsar=1,ass={caption_file.name}"
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{candidate.start:.3f}",
          "-i", str(source), "-t", f"{candidate.end - candidate.start:.3f}", "-vf", filters,
          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(video)], cwd=folder)
    if _video_dimensions(ffmpeg, video) != (1080, 1920):
        raise PipelineError(f"Exported clip has the wrong dimensions: {video.name}")
    exported_duration = _video_duration(ffmpeg, video)
    if not 10.0 <= exported_duration <= 40.0:
        raise PipelineError(f"Exported clip duration is outside 10–40 seconds: {video.name}")
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", str(video),
          "-frames:v", "1", str(thumbnail)])
    return {"rank": index, "title": make_title(candidate.text), "file": str(video),
            "thumbnail": str(thumbnail), "caption_file": str(caption_file),
            "social_caption": make_caption(candidate), "transcript_excerpt": candidate.text,
            "start": candidate.start,
            "end": candidate.end, "duration": round(exported_duration, 2),
            "score": candidate.score, "score_reasons": list(candidate.reasons),
            "framing": "face-aware" if face_x is not None else "center"}


def process(source_value: str | Path, output_root: Path, progress: Progress) -> Path:
    if not callable(progress):
        raise TypeError("progress must be callable")
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    job = output_root / time.strftime("%Y-%m-%d_%H-%M-%S")
    suffix = 1
    while job.exists():
        suffix += 1
        job = output_root / f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{suffix}"
    job.mkdir()
    ffmpeg = ffmpeg_path()
    source_text = str(source_value)
    if source_text.lower().startswith(("http://", "https://")):
        url = validate_youtube_url(source_text)
        progress("Retrieving video", 0.02)
        source, title = _download(url, job, progress)
    else:
        source = Path(source_value).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
            raise PipelineError("Choose a local MP4, MOV, MKV, WEBM, or M4V video")
        title = source.stem
        progress("Loading local video", 0.05)
    dimensions = _video_dimensions(ffmpeg, source)
    words, language = _transcribe(ffmpeg, source, job, progress)
    progress("Finding complete spoken moments", 0.60)
    candidates = generate_candidates(words)
    ollama_scores, selection_mode = _ollama_scores(candidates, progress)
    identity = {id(item): index for index, item in enumerate(candidates)}
    selected = select_clips(candidates, extra_score=lambda item: ollama_scores.get(identity[id(item)], 0.0))
    if not selected:
        raise PipelineError("No 10–40 second complete spoken moments met the quality threshold. Try a longer, speech-rich video.")
    results = []
    original_scores = {(item.start, item.end): item.score for item in candidates}
    for index, candidate in enumerate(selected, 1):
        progress(f"Rendering clip {index} of {len(selected)}", 0.70 + 0.29 * (index - 1) / len(selected))
        rendered = _render(ffmpeg, source, job, candidate, index, dimensions)
        rendered["heuristic_score"] = original_scores[(candidate.start, candidate.end)]
        rendered["ollama_bonus"] = round(candidate.score - rendered["heuristic_score"], 1)
        results.append(rendered)
    manifest = {"source": source_text, "source_title": title, "language": language,
                "selection_mode": selection_mode, "candidates_considered": len(candidates),
                "clips": results}
    (job / "clips.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (job / "social_captions.txt").write_text("\n\n".join(
        f"{item['rank']:02d}. {item['title']} (score {item['score']})\n{item['social_caption']}"
        for item in results), encoding="utf-8")
    progress(f"Finished {len(results)} clips", 1.0)
    return job
