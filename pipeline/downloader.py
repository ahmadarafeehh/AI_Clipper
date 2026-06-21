"""
Step 1: Download the source video from YouTube.
"""
from pathlib import Path
import yt_dlp
import config


def download_video(url: str) -> Path:
    """Download best-quality mp4 (video+audio merged) and return its path."""
    outtmpl = str(config.DOWNLOADS_DIR / "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    # On cloud hosts (Render included), YouTube's bot-detection flags the
    # datacenter IP and demands authentication. Feeding it a cookies file
    # from a real logged-in session works around this. Locally this file
    # won't exist, so cookiefile is simply omitted - no behavior change.
    if Path(config.YOUTUBE_COOKIE_FILE).exists():
        ydl_opts["cookiefile"] = config.YOUTUBE_COOKIE_FILE
        print(f"[downloader] Using cookies from {config.YOUTUBE_COOKIE_FILE}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # extract_info with download=True returns the final, post-processed info dict
        path = Path(ydl.prepare_filename(info))
        # merge_output_format may change extension to .mp4 after postprocessing
        if not path.exists():
            path = path.with_suffix(".mp4")
    if not path.exists():
        raise FileNotFoundError(f"yt-dlp reported success but file not found: {path}")
    print(f"[downloader] Saved video -> {path}")
    return path


def extract_audio(video_path: Path, out_path: Path, start: float = None, end: float = None) -> Path:
    """
    Extract audio as mono 16kHz FLAC (small, lossless - ideal for Whisper).
    If start/end (seconds) are given, only that slice is extracted.
    """
    import subprocess
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video_path)]
    if end is not None:
        duration = end - (start or 0)
        cmd += ["-t", str(duration)]
    cmd += ["-ar", "16000", "-ac", "1", "-map", "0:a", "-c:a", "flac", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
