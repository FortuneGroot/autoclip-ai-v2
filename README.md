# AUTOCLIP AI V2

Private V2 source snapshot, based on source-kit version 0.1.4. This contains the working Python application and Windows launchers. A standalone EXE and bundled Windows installer have not been built.

Automatic generation exports up to ten clips. Timestamp-guided generation supports one 10–40-second clip per supplied mark, including batches above ten clips. Automatic editorial quality still requires human review; this is not a claim of human-approved highlight selection.

Personal recordings, generated clips, access keys, model downloads, installed environments, and machine logs are excluded.

AUTOCLIP AI turns a video you are permitted to use into up to ten ranked, captioned vertical MP4 clips. It runs on your own Windows computer. The selection engine uses transcript boundaries and an explainable score; it returns fewer clips when the source lacks enough useful moments. Optional Ollama scoring can add a content review when a local Ollama model is installed.

## Requirements

- Windows 10 or 11, 64-bit; Python 3.11 or 3.12 from python.org with the `py` launcher; an internet connection to install free dependencies and download the first speech model.
- Space for your source video, output clips, and a local speech model. Long recordings can take substantial time on CPU. A compatible GPU may help but is optional.
- Permission under the video owner's rights and the platform's terms to download and edit the source video. Importing a video file you already have is the most reliable route. YouTube URL retrieval is best effort and can fail as sites change or restrict access.

## Install and open

1. Extract the ZIP to a folder you own. Keep the files together.
2. Double-click **Install AUTOCLIP AI.bat** and let it finish. Installation creates a private `.venv` in this folder and a desktop shortcut. No paid API account is required.
3. Double-click the **AUTOCLIP AI** desktop shortcut. It starts the local server and opens the editor in your default browser. Alternatively, double-click **Launch AUTOCLIP AI.bat** for the native Windows interface.
4. Paste an accessible YouTube URL or import a local video, then click **Generate Clips**. Review the ranked clips and suggested captions before posting.

Finished MP4 files, thumbnails, captions, and the scoring manifest are saved under `output`. They have no AUTOCLIP AI watermark. Automatic captions and editorial choices can contain mistakes, so review the exports before publication.

No timestamps are required for automatic generation. If you already have review notes, open a completed video's library card and choose **Optional: guide clips with my notes**. Paste up to 100 approximate marks (`12.45`, `15`, `mm:ss`, or `h:mm:ss`, one per line). The app chooses clip boundaries and exports one nearby 10–40-second spoken moment per mark when complete speech is available, using the saved transcript and source video without downloading or transcribing again. Guided batches may exceed the automatic ten-clip limit. The original exports stay intact.

## Optional phone access

Double-click **Launch AUTOCLIP AI for iPhone.bat** on Windows, then scan the QR code with an iPhone on the same trusted Wi-Fi. Processing still runs on Windows. Windows may request administrator approval once to allow only local-subnet traffic on TCP port 8765. The phone interface uses local HTTP; do not use it on public or untrusted Wi-Fi. It is not a cloud service or an App Store app.

## Source layout

- `core.py`: transcript scoring, candidate construction, and deduplication.
- `analysis/revise_job.py`: timestamp-guided refinement of a completed saved job.
- `pipeline.py`: retrieval, transcription, cropping, captions, and export.
- `app.py`: native Windows interface.
- `mobile_server.py` and `mobile/`: local browser interface.
- `tests/` and **Run Tests.bat**: unit and short local end-to-end checks.

## Limits

Results depend on speech quality, framing, video access, available memory, and processing time. The app does not bypass DRM, logins, or access controls. A 60–120-minute job can take a long time on a CPU. Optional Ollama runtime and model files are not included in this source ZIP; install a compatible free local model separately for AI content scoring. The first speech model download and package installation require internet access; video processing itself runs locally. `THIRD_PARTY_NOTICES.md` identifies the main external components and their licenses.

For an install failure, run **Install AUTOCLIP AI.bat** again and read the error in its window. If a YouTube URL fails, import a local video file you are authorized to edit.
