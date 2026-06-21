"""
Central configuration for the clipper pipeline.
Edit values here instead of hunting through every file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "Add your key "
        "from https://console.groq.com/keys"
    )

# Path to a YouTube cookies file (Netscape format), used to make yt-dlp
# look like an authenticated browser session. YouTube increasingly demands
# this for traffic from cloud/datacenter IPs (Render included) - without
# it, downloads fail with "Sign in to confirm you're not a bot". On Render
# this is mounted automatically by their "Secret Files" feature at
# /etc/secrets/<filename>; locally that path just won't exist, so this
# has no effect on local runs.
YOUTUBE_COOKIE_FILE = os.getenv("YOUTUBE_COOKIE_FILE", "/etc/secrets/youtube_cookies.txt")

# --- Groq models ---
# LLM used to read the transcript and choose clips + write hooks.
# Good general picks on Groq right now: "openai/gpt-oss-120b" (best reasoning,
# 131k context) or "llama-3.3-70b-versatile" (fast, very reliable JSON output).
LLM_MODEL = "openai/gpt-oss-120b"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# Whisper model used for transcription (both the full-video pass and the
# per-clip word-timestamp pass). "whisper-large-v3-turbo" is fast and cheap;
# use "whisper-large-v3" if you want max accuracy and don't mind it being slower.
WHISPER_MODEL = "whisper-large-v3-turbo"

# Groq's free tier caps audio uploads at 25MB (100MB on paid "dev" tier).
# We extract audio as mono 16kHz FLAC (small + lossless) and split into
# chunks under this size if needed.
MAX_AUDIO_CHUNK_MB = 24

# --- Clip selection ---
NUM_CLIPS = 3          # how many clips to extract per video
MIN_CLIP_SECONDS = 20
MAX_CLIP_SECONDS = 90

# --- Output video ---
VERTICAL_OUTPUT = True   # True = 1080x1920 (Shorts/Reels/TikTok), False = keep source aspect ratio
VERTICAL_SIZE = (1080, 1920)

# --- Captions (burned-in subtitles) ---
# NOTE: captions are rendered via ffmpeg's "ass" filter, which uses libass.
# CAPTION_FONT_FILE is set further down, after FONTS_DIR is defined in the
# Paths section - it needs that variable to exist first.
CAPTION_WORDS_PER_CARD = 4       # how many words shown on screen at once
CAPTION_FONT = "Arial Black"     # fallback name if CAPTION_FONT_FILE is None
CAPTION_FONT_SIZE = 78
CAPTION_COLOR = "&H00FFFFFF"        # ASS BGR hex, AABBGGRR-ish: this is opaque white
CAPTION_HIGHLIGHT_COLOR = "&H0000D7FF"  # opaque gold/yellow (highlighted word)
CAPTION_OUTLINE_COLOR = "&H00000000"    # black outline
CAPTION_MARGIN_V = 260           # distance from bottom, in px (PlayRes space)
MAX_TRANSCRIPT_CHARS = 20000

# --- Hook text overlay ---
# NOTE: HOOK_FONT_FILE is set further down, after FONTS_DIR is defined in
# the Paths section - same reason as CAPTION_FONT_FILE above. It bypasses
# fontconfig entirely (font lookup by name is unreliable across platforms)
# and is also used by hook.py + Pillow to measure exact text width for
# wrapping, instead of guessing.
HOOK_FONT = "Arial Black"        # fallback name if HOOK_FONT_FILE is None
HOOK_FONT_SIZE = 64              # starting size; auto-shrinks down to HOOK_MIN_FONT_SIZE if a hook needs more than HOOK_MAX_LINES to fit
HOOK_MIN_FONT_SIZE = 40          # floor for the auto-shrink - won't go smaller than this even if a hook is very long
HOOK_MAX_LINES = 3               # wrap past this many lines and the font starts shrinking instead
HOOK_SIDE_MARGIN_PCT = 0.08      # horizontal safe-zone margin on EACH side, as a fraction of frame width (0.08 = 8% left + 8% right)
HOOK_BOX_BORDER = 18             # px of padding ffmpeg's "box" draws around each line - must match the boxborderw value used in hook.py's drawtext string
HOOK_Y_POSITION_PCT = 0.14       # how far down from the top the hook sits, as a fraction of frame height. ~0.12-0.18 matches where top-performing Shorts/Reels hooks sit - flush against the very top edge (<0.08) tends to get visually crowded or covered by the platform's own UI (username, sound bar) once posted
HOOK_DURATION_SECONDS = None     # None = show for whole clip; or e.g. 4 = only first 4s

# --- Paths ---
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
WORK_DIR = BASE_DIR / "work"
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"

for d in (DOWNLOADS_DIR, WORK_DIR, OUTPUT_DIR, FONTS_DIR):
    d.mkdir(exist_ok=True)

# These two depend on FONTS_DIR above, which is why they live down here
# instead of next to the other CAPTION_*/HOOK_* settings further up.
HOOK_FONT_FILE = str(FONTS_DIR / "ArchivoBlack-Regular.ttf")
CAPTION_FONT_FILE = str(FONTS_DIR / "ArchivoBlack-Regular.ttf")
