"""
Step 2: Transcribe audio using Groq's hosted Whisper endpoint.

Two use cases:
  - transcribe_full_video(): coarse, segment-level transcript with timestamps,
    used as input to the LLM clip-selector (cheap, one pass over the whole video).
  - transcribe_clip(): word-level timestamps for a single short clip, used to
    build the animated burned-in captions.
"""
import math
import subprocess
import json
from pathlib import Path

from groq import Groq

import config
from pipeline.downloader import extract_audio

client = Groq(api_key=config.GROQ_API_KEY)


def get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _call_whisper(audio_path: Path, granularities):
    with open(audio_path, "rb") as f:
        return client.audio.transcriptions.create(
            file=f,
            model=config.WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=granularities,
        )


def transcribe_full_video(video_path: Path) -> str:
    """
    Returns a single string transcript formatted like:
        [00:00 - 00:04] Hey what's up everyone...
        [00:04 - 00:09] Today we're talking about...
    chunked automatically if the audio is too large for one API call.
    """
    duration = get_duration(video_path)
    full_audio = config.WORK_DIR / "probe_audio.flac"
    extract_audio(video_path, full_audio)
    size_mb = full_audio.stat().st_size / (1024 * 1024)

    if size_mb <= config.MAX_AUDIO_CHUNK_MB:
        chunks = [(0.0, duration)]
    else:
        n_chunks = math.ceil(size_mb / config.MAX_AUDIO_CHUNK_MB)
        chunk_len = duration / n_chunks
        chunks = [
            (i * chunk_len, min((i + 1) * chunk_len, duration))
            for i in range(n_chunks)
        ]
    full_audio.unlink(missing_ok=True)

    lines = []
    for idx, (start, end) in enumerate(chunks):
        chunk_path = config.WORK_DIR / f"chunk_{idx}.flac"
        extract_audio(video_path, chunk_path, start=start, end=end)
        print(f"[transcriber] Transcribing chunk {idx + 1}/{len(chunks)} "
              f"({start:.0f}s - {end:.0f}s)...")
        result = _call_whisper(chunk_path, granularities=["segment"])
        chunk_path.unlink(missing_ok=True)

        segments = getattr(result, "segments", None) or result.get("segments", [])
        for seg in segments:
            seg_start = seg["start"] if isinstance(seg, dict) else seg.start
            seg_end = seg["end"] if isinstance(seg, dict) else seg.end
            seg_text = seg["text"] if isinstance(seg, dict) else seg.text
            abs_start = start + seg_start
            abs_end = start + seg_end
            lines.append(f"[{_fmt(abs_start)} - {_fmt(abs_end)}] {seg_text.strip()}")

    return "\n".join(lines)


def transcribe_clip_words(video_path: Path, clip_start: float, clip_end: float) -> list[dict]:
    """
    Returns word-level timestamps *relative to the clip start* (i.e. first
    word starts near t=0), ready to feed into the caption builder.
    [{"word": "Hey", "start": 0.12, "end": 0.34}, ...]
    """
    audio_path = config.WORK_DIR / "clip_audio.flac"
    extract_audio(video_path, audio_path, start=clip_start, end=clip_end)
    result = _call_whisper(audio_path, granularities=["word"])
    audio_path.unlink(missing_ok=True)

    words = getattr(result, "words", None) or result.get("words", [])
    out = []
    for w in words:
        word = w["word"] if isinstance(w, dict) else w.word
        ws = w["start"] if isinstance(w, dict) else w.start
        we = w["end"] if isinstance(w, dict) else w.end
        out.append({"word": word.strip(), "start": ws, "end": we})
    return out


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
