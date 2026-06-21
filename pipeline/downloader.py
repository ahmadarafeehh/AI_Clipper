"""
Step 1: Download the source video from YouTube.
"""
import os
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
    (which IS writable) and hand yt-dlp that copy instead. If the secret
    file doesn't exist (locally, or if you've dropped cookies entirely),
    this returns None and cookies are simply skipped.
    """
    source = Path(config.YOUTUBE_COOKIE_FILE)
    if not source.exists():
        return None
    writable = config.WORK_DIR / "youtube_cookies_writable.txt"
    shutil.copy(source, writable)
    return writable


def _base_ydl_opts(use_pot: bool = True) -> dict:
    """
    Shared yt-dlp options.

    Bot-check strategy, in order of what's actually doing the work:

    1. PO Token provider (bgutil-ytdlp-pot-provider) - a small sidecar
       service that mints YouTube's required "proof of origin" token per
       request. This is what satisfies "Sign in to confirm you're not a
       bot" on datacenter IPs like Render's. It needs no human-exported
       credential and doesn't expire the way a cookie jar does. Enabled by
       setting the BGUTIL_POT_BASE_URL env var to the sidecar's URL.

    2. Cookies (optional, additive) - only needed for content that
       genuinely requires a logged-in session: age-restricted, private, or
       members-only videos. Most clip-source content (podcasts, interviews,
       talks) doesn't need this. Kept purely as a fallback for those edge
       cases - it's no longer required for the common case.
    """
    opts = {
        # Capped at 720p - the free Render instance only has 512MB RAM, and
        # pulling in a full 1080p source (400-800MB) on top of ffmpeg's
        # memory use during cutting/reframing/captioning was crashing the
        # container mid-job. 720p is plenty of source quality for short
        # vertical social clips and uses a fraction of the memory/disk.
        "format": "bestvideo*[height<=720]+bestaudio/best[height<=720]",
        "merge_output_format": "mp4",
        # remote_components lets yt-dlp fetch its EJS challenge-solver
        # script at runtime - required to decrypt YouTube's "n challenge"
        # signatures and actually resolve real format URLs. Confirmed
        # working - keep this.
        "remote_components": {"ejs:github"},
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    pot_base_url = os.getenv("BGUTIL_POT_BASE_URL")
    if use_pot and pot_base_url:
        opts["extractor_args"] = {
            "youtubepot-bgutilhttp": {"base_url": [pot_base_url]},
        }
        print(f"[downloader] Using PO Token provider at {pot_base_url}")
    elif use_pot:
        print(
            "[downloader] No BGUTIL_POT_BASE_URL set - downloads may hit "
            "YouTube's bot check on datacenter IPs. Deploy the "
            "bgutil-ytdlp-pot-provider sidecar and set that env var."
        )

    cookiefile = _writable_cookiefile()
    if cookiefile:
        opts["cookiefile"] = str(cookiefile)
        print(f"[downloader] Also using cookies from {cookiefile} (writable copy of {config.YOUTUBE_COOKIE_FILE})")

    return opts


def download_video(url: str) -> Path:
    """
    Download best-quality mp4 (video+audio merged) and return its path.

    Tries the PO Token provider first. If that request fails for any
    reason (sidecar briefly down, network hiccup, etc.), retries once
    without it rather than failing the whole job outright - cookies alone,
    or a clean unauthenticated request, still succeed for plenty of videos.
    """
    outtmpl = str(config.DOWNLOADS_DIR / "%(id)s.%(ext)s")

    def _attempt(use_pot: bool):
        ydl_opts = _base_ydl_opts(use_pot=use_pot)
        ydl_opts["outtmpl"] = outtmpl
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # extract_info with download=True returns the final, post-processed info dict
            path = Path(ydl.prepare_filename(info))
            # merge_output_format may change extension to .mp4 after postprocessing
            if not path.exists():
                path = path.with_suffix(".mp4")
            return path

    try:
        path = _attempt(use_pot=True)
    except yt_dlp.utils.DownloadError as e:
        if not os.getenv("BGUTIL_POT_BASE_URL"):
            raise  # PO token wasn't even configured, no point retrying
        print(f"[downloader] First attempt failed ({e}); retrying without PO Token provider...")
        path = _attempt(use_pot=False)

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
