# Third-party components

This source archive contains AUTOCLIP AI application source and interface assets. It does **not** contain a Python environment, speech model, FFmpeg executable, or downloaded video. The installer obtains dependencies from their package distributors on the buyer's computer. Review the licenses of the exact package versions installed before commercial redistribution of any combined binary build.

| Component | Use | Upstream license/source |
| --- | --- | --- |
| yt-dlp | Accessible video retrieval | [Project and licensing notes](https://github.com/yt-dlp/yt-dlp) |
| faster-whisper | Local transcription | [MIT license](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) |
| CTranslate2 | Inference engine used by faster-whisper | [Project license](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE) |
| PyAV | Media decoding used by faster-whisper | [Project license](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt) |
| OpenCV Python | Face detection for crop placement | [Project license](https://github.com/opencv/opencv/blob/4.x/LICENSE) |
| imageio-ffmpeg / FFmpeg | FFmpeg executable for MP4 rendering | [Wrapper](https://github.com/imageio/imageio-ffmpeg), [FFmpeg legal and license page](https://ffmpeg.org/legal.html) |
| qrcode / Pillow | Local setup QR image | [qrcode](https://github.com/lincolnloop/python-qrcode/blob/main/LICENSE), [Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| OpenAI Whisper model weights | Speech model downloaded on first run | [Whisper project license](https://github.com/openai/whisper/blob/main/LICENSE) |

FFmpeg licensing depends on how the executable was built. Some FFmpeg configurations use GPL components. This source archive avoids shipping an FFmpeg binary; building and distributing an all-in-one executable needs a separate license-compliance review. yt-dlp's own licensing notes also distinguish its Python package from its bundled executables. [YouTube's Terms](https://www.youtube.com/t/terms) and rights in source footage are separate from software licenses. Use only videos you may access, download, and edit under both.
