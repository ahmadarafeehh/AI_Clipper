# Groq Shorts Clipper

Turn a long YouTube video into short, captioned, hook-driven clips — fully automated, running on your own machine.

**Pipeline:**
1. Downloads the video (`yt-dlp`)
2. Transcribes it with timestamps using **Groq's Whisper API**
3. Sends the transcript to a **Groq LLM**, which picks the best clips and writes a scroll-stopping "hook" line for each
4. Cuts each clip with `ffmpeg` and reframes it to vertical 9:16 (blurred, zoomed background — the standard Shorts/Reels look)
5. Re-transcribes each clip for word-level timing and burns in animated, word-by-word highlighted captions
6. Overlays the hook text near the top of the clip

Everything — transcription AND clip selection — runs through your one `GROQ_API_KEY`, so there's nothing else to sign up for.

## 1. Install prerequisites

- **Python 3.10+**
- **ffmpeg** must be installed and on your PATH
  - Windows: `winget install ffmpeg` (or download from ffmpeg.org and add to PATH)
  - Mac: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
- A free **Groq API key**: https://console.groq.com/keys

## 2. Set up the project

```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and paste in your key:

```
GROQ_API_KEY=gsk_your_real_key_here
```

## 3. Run it

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Optional flags:

```bash
python main.py "<url>" --clips 5          # generate 5 clips instead of the default 3
python main.py "<url>" --no-vertical      # keep the original aspect ratio instead of 9:16
```

Finished clips land in `output/clip_1.mp4`, `output/clip_2.mp4`, etc., alongside an `output/manifest.json` listing each clip's timestamps, hook text, and the LLM's reasoning for picking it.

Intermediate files (full transcript, raw cuts, the generated `.ass` caption files) are kept in `work/` so you can inspect or re-use them — safe to delete between runs.

## Tuning it to your taste

Almost everything is a constant at the top of **`config.py`** — no need to dig through the pipeline code:

| What | Where |
|---|---|
| How many clips, min/max clip length | `NUM_CLIPS`, `MIN_CLIP_SECONDS`, `MAX_CLIP_SECONDS` |
| Which Groq LLM picks the clips | `LLM_MODEL` |
| Which Whisper model transcribes | `WHISPER_MODEL` |
| Vertical vs. original aspect ratio | `VERTICAL_OUTPUT` |
| Caption font, size, colors, words-per-line | `CAPTION_*` |
| Hook font, size, how long it stays on screen | `HOOK_*` |

### Using your own font
By default, captions/hooks try to use "Arial Black" via your system's font lookup, which may silently fall back to a default font (especially on Windows, where ffmpeg often lacks the fontconfig support needed for `font=` by-name lookup). For guaranteed results, drop a `.ttf` file into `fonts/` and point to it directly:

```python
CAPTION_FONT_FILE = "fonts/Montserrat-ExtraBold.ttf"
HOOK_FONT_FILE = "fonts/Montserrat-ExtraBold.ttf"
```

## How clip selection actually works

The full transcript (with timestamps) is sent to the LLM in one prompt with instructions to pick self-contained, complete-thought moments and avoid clips that depend on context from elsewhere in the video. It returns strict JSON with `start`, `end`, `hook`, and `reason` for each clip — see `pipeline/clip_selector.py` to tweak the prompt (e.g. bias it toward funny moments, controversial takes, educational tips, etc. — just edit `SYSTEM_PROMPT`).

## Notes & limits

- **Long videos / Groq's audio size limit**: Groq's free tier caps audio uploads at 25MB. The full-video transcription step automatically splits long audio into chunks to stay under this, so very long videos (multi-hour) just take a bit longer and use a few more API calls.
- **Videos without speech, or in languages Whisper handles poorly**, will produce a thin transcript and likely worse clip choices — this works best on talking-head content (podcasts, interviews, tutorials, vlogs).
- **Copyright**: this tool can technically clip any video you give it a URL for. Only use it on content you own, have rights to repurpose, or that's appropriately licensed (e.g. your own podcast/stream VOD) — and check YouTube's Terms of Service regarding downloading video content.
- This is unaffiliated with Google/YouTube; `yt-dlp` is a third-party tool and YouTube can change things in ways that break it from time to time — if downloads start failing, `pip install -U yt-dlp` is usually the fix.
