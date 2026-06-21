"""
Step 1: Download the source video from YouTube.
"""
import shutil
from pathlib import Path
import yt_dlp
import config


def _writable_cookiefile():
    """
    yt-dlp updates the cookie jar in place after requests (YouTube rotates
    some session cookies during use). config.YOUTUBE_COOKIE_FILE points at
    Render's Secret File mount (/etc/secrets/...), which is READ-ONLY -
    yt-dlp crashes trying to write back to it. Copy it once into WORK_DIR
    (which IS writable) and hand yt-dlp that copy instead. Locally, where
    the secret file doesn't exist, this returns None and cookies are
    skipped entirely, same as before.
    """
    source = Path(config.YOUTUBE_COOKIE_FILE)
    if not source.exists():
        return None
    writable = config.WORK_DIR / "youtube_cookies_writable.txt"
    shutil.copy(source, writable)
    return writable


def download_video(url: str) -> Path:
    """Download best-quality mp4 (video+audio merged) and return its path."""
    outtmpl = str(config.DOWNLOADS_DIR / "%(id)s.%(ext)s")
    ydl_opts = {
        # bestvideo*+bestaudio/best is yt-dlp's own internal default - it
        # doesn't hard-require an mp4/m4a container, since YouTube doesn't
        # always serve that combo for every video (webm/vp9 only, for some
        # videos/resolutions). merge_output_format below still forces the
        # FINAL output to .mp4 regardless of what source streams it picks -
        # ffmpeg remuxes/transcodes during the merge either way.
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    cookiefile = _writable_cookiefile()
    if cookiefile:
        ydl_opts["cookiefile"] = str(cookiefile)
        print(f"[downloader] Using cookies from {cookiefile} (writable copy of {config.YOUTUBE_COOKIE_FILE})")
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
