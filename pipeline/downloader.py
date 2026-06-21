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


def _base_ydl_opts(use_pot: bool = True, use_cookies: bool = False) -> dict:
    """
    Shared yt-dlp options.

    Bot-check strategy, in order of what's actually doing the work:

    1. PO Token provider (bgutil-ytdlp-pot-provider) - a small sidecar
       service that mints YouTube's required "proof of origin" token per
       request. This is what satisfies "Sign in to confirm you're not a
       bot" on datacenter IPs like Render's. It needs no human-exported
       credential and doesn't expire the way a cookie jar does. Enabled by
       setting the BGUTIL_POT_BASE_URL env var to the sidecar's URL.

    2. Cookies - OFF by default now. A stale/expired cookie file doesn't
       just "do nothing" - yt-dlp treats its mere presence as "this is a
       logged-in session", validates it, finds it's rotated/expired, and
       YouTube returns LOGIN_REQUIRED instead of the normal anonymous
       response. That's worse than having no cookies at all. Cookies are
       only attached when use_cookies=True, which download_video() only
       does as an explicit second attempt if the clean PO-token-only
       attempt fails - covering genuinely private/age-restricted videos
       without poisoning the common case.
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
        "noplaylist": True,
    }

    # DEBUG SWITCH: set YTDLP_DEBUG=1 as an env var on the main service to
    # turn this on. It makes yt-dlp print everything it's doing, including
    # a line like "[debug] [youtube] [pot] PO Token Providers: bgutil:http-
    # ..." which confirms whether the plugin is even loaded and whether it
    # reached the sidecar. Turn it back off once things work - it's noisy.
    debug = os.getenv("YTDLP_DEBUG", "").lower() in ("1", "true", "yes")
    if debug:
        opts["verbose"] = True
    else:
        opts["quiet"] = True
        opts["no_warnings"] = True

    pot_base_url = os.getenv("BGUTIL_POT_BASE_URL")
    if use_pot and pot_base_url:
        # yt-dlp's own docs: pair a PO Token provider with the "mweb"
        # client specifically. The auto-picked defaults (android_vr,
        # web_safari) have been getting flagged outright by YouTube
        # regardless of PO token - forcing mweb is the documented fix.
        opts["extractor_args"] = {
            "youtube": {"player_client": ["mweb"]},
            "youtubepot-bgutilhttp": {"base_url": [pot_base_url]},
        }
        print(f"[downloader] Using PO Token provider at {pot_base_url} (mweb client)", flush=True)
    elif use_pot:
        print(
            "[downloader] No BGUTIL_POT_BASE_URL set - downloads may hit "
            "YouTube's bot check on datacenter IPs. Deploy the "
            "bgutil-ytdlp-pot-provider sidecar and set that env var.",
            flush=True,
        )

    if use_cookies:
        cookiefile = _writable_cookiefile()
        if cookiefile:
            opts["cookiefile"] = str(cookiefile)
            print(
                f"[downloader] Retrying with cookies from {cookiefile} (writable copy of {config.YOUTUBE_COOKIE_FILE})",
                flush=True,
            )

    return opts


def download_video(url: str) -> Path:
    """
    Download best-quality mp4 (video+audio merged) and return its path.

    Two attempts:
      1. PO Token only, no cookies - the clean path, works for the vast
         majority of public videos (podcasts, interviews, talks, etc.).
      2. Only if (1) fails: PO Token + cookies, in case the video genuinely
         needs a logged-in session (private/members-only/age-restricted).
         This attempt is skipped automatically if no cookie file exists.
    Cookies are never sent on the first attempt - see _base_ydl_opts for why.
    """
    outtmpl = str(config.DOWNLOADS_DIR / "%(id)s.%(ext)s")

    def _attempt(use_pot: bool, use_cookies: bool):
        ydl_opts = _base_ydl_opts(use_pot=use_pot, use_cookies=use_cookies)
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
        path = _attempt(use_pot=True, use_cookies=False)
    except yt_dlp.utils.DownloadError as e:
        if not Path(config.YOUTUBE_COOKIE_FILE).exists():
            raise  # no cookies to fall back to, no point retrying
        print(f"[downloader] First attempt failed ({e}); retrying with cookies...", flush=True)
        path = _attempt(use_pot=True, use_cookies=True)

    if not path.exists():
        raise FileNotFoundError(f"yt-dlp reported success but file not found: {path}")
    print(f"[downloader] Saved video -> {path}", flush=True)
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
