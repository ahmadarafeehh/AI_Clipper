"""
Step 3: Feed the timestamped transcript to an LLM and ask it to pick the
best short-form clips, each with a scroll-stopping "hook" line.

Uses Google's Gemini 2.5 Flash (free tier, ai.google.dev) instead of Groq
for this step. Gemini's free tier has a 1M token context window, so the
*entire* transcript can be analyzed even for long videos - no truncation
needed, unlike Groq's 8000 TPM cap which only let the LLM see the first
few minutes of long videos.

Transcription (Whisper) still runs on Groq separately - this file only
changes which LLM picks the clips.
"""
import json
import re
from google import genai
from google.genai import types
import config

client = genai.Client(api_key=config.GOOGLE_API_KEY)

SYSTEM_PROMPT = """You are an expert short-form video editor who has produced viral \
TikTok/Reels/Shorts clips from long-form podcasts and talks. You are given a \
timestamped transcript of a video. Your job is to select the strongest, most \
self-contained moments to cut into standalone short clips.
Pick moments that work WITHOUT the rest of the video for context: a complete \
thought, a strong opinion, a surprising fact, a story with a punchline, useful \
advice, or an emotional beat. Avoid clips that depend on something said much \
earlier in the video.
CRITICAL - sentence boundaries: your start and end timestamps must align with \
the start and end of a complete sentence. NEVER choose a start time that lands \
in the middle of, or on the tail end of, a sentence that began earlier - the \
viewer should never hear a fragment like "...always been. [then the real \
clip begins]". Likewise the end time must land on the end of a complete \
sentence, not cut off mid-thought. If the strongest moment begins partway \
through a sentence, move the start timestamp BACKWARD to the beginning of \
that sentence (or forward to the start of the NEXT full sentence if the \
partial sentence adds nothing). It is fine for the resulting clip to be a \
few seconds shorter or longer than the target length in order to respect \
this rule - clean sentence boundaries matter more than hitting the exact \
target duration.
Since you can see the FULL transcript, spread your picks across the whole \
video rather than clustering them all near the beginning - look for strong \
moments in the middle and end too.
For each clip also write a "hook": a short (under 8 words), punchy line of \
on-screen text designed to stop someone from scrolling in the first second. \
The hook should tease the payoff without fully giving it away.
Respond with ONLY valid JSON, no commentary, in exactly this shape:
{
  "clips": [
    {
      "start": "MM:SS",
      "end": "MM:SS",
      "hook": "short punchy on-screen text",
      "reason": "one sentence on why this clip works"
    }
  ]
}
"""


def _parse_timestamp(ts: str) -> float:
    parts = [float(p) for p in ts.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# Matches lines like "[12:47 - 12:51] some text" or "[0:12:47 - 0:12:51] text"
_SEGMENT_RE = re.compile(
    r"\[\s*(\d{1,2}(?::\d{2}){1,2})\s*-\s*(\d{1,2}(?::\d{2}){1,2})\s*\]\s*(.*?)(?=\[\d|\Z)",
    re.DOTALL,
)


def _extract_clip_text(transcript: str, clip_start: float, clip_end: float) -> str:
    """
    Pulls the actual transcript text covering [clip_start, clip_end] out of the
    full timestamped transcript, so you can read what the LLM actually picked
    instead of just trusting its timestamps + hook.
    """
    pieces = []
    for m in _SEGMENT_RE.finditer(transcript):
        try:
            seg_start = _parse_timestamp(m.group(1))
            seg_end = _parse_timestamp(m.group(2))
        except ValueError:
            continue
        # include any transcript segment that overlaps the clip's time range at all
        if seg_end > clip_start and seg_start < clip_end:
            text = " ".join(m.group(3).split())
            if text:
                pieces.append(text)
    return " ".join(pieces).strip() or "(could not match transcript text to this time range)"


def select_clips(transcript: str) -> list[dict]:
    print("\n" + "=" * 70)
    print("[clip_selector] STARTING CLIP SELECTION (Gemini)")
    print("=" * 70)
    print(f"[clip_selector] Model: {config.GEMINI_MODEL}")
    print(f"[clip_selector] Requested num_clips: {config.NUM_CLIPS}")
    print(f"[clip_selector] Allowed clip length range: "
          f"{config.MIN_CLIP_SECONDS}s - {config.MAX_CLIP_SECONDS}s")
    print(f"[clip_selector] Full transcript length: {len(transcript)} chars "
          f"(~{len(transcript)//4} tokens estimated) - sent in full, no truncation")

    user_prompt = f"""Transcript (format is [start - end] text):
{transcript}

Select exactly {config.NUM_CLIPS} clips. Each clip must be between \
{config.MIN_CLIP_SECONDS} and {config.MAX_CLIP_SECONDS} seconds long, and \
clips must not overlap."""

    print("[clip_selector] Calling Gemini API...")

    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.6,
        ),
    )

    raw = response.text
    print("[clip_selector] --- RAW LLM RESPONSE (verbatim JSON) ---")
    print(raw)
    print("[clip_selector] --- END RAW LLM RESPONSE ---")

    usage = getattr(response, "usage_metadata", None)
    if usage:
        print(f"[clip_selector] Token usage - prompt: {usage.prompt_token_count}, "
              f"response: {usage.candidates_token_count}, total: {usage.total_token_count}")

    data = json.loads(raw)
    clips = data["clips"]
    print(f"[clip_selector] LLM returned {len(clips)} raw clip entries (before validation)")

    parsed = []
    for idx, c in enumerate(clips, start=1):
        print(f"\n[clip_selector] --- Raw clip #{idx} from LLM ---")
        print(f"    start (raw):  {c.get('start')}")
        print(f"    end (raw):    {c.get('end')}")
        print(f"    hook:         \"{c.get('hook')}\"")
        print(f"    reason:       {c.get('reason')}")

        start = _parse_timestamp(c["start"])
        end = _parse_timestamp(c["end"])
        duration = end - start

        if end <= start:
            print(f"    [clip_selector] REJECTED - end ({end}) <= start ({start}), malformed entry")
            continue

        in_range = config.MIN_CLIP_SECONDS <= duration <= config.MAX_CLIP_SECONDS
        print(f"    parsed start: {start:.1f}s ({_fmt(start)})")
        print(f"    parsed end:   {end:.1f}s ({_fmt(end)})")
        print(f"    duration:     {duration:.1f}s  "
              f"[{'OK - within' if in_range else 'WARNING - outside'} requested "
              f"{config.MIN_CLIP_SECONDS}-{config.MAX_CLIP_SECONDS}s range]")

        clip_text = _extract_clip_text(transcript, start, end)
        print(f"    --- Actual transcript text for this time range ---")
        print(f"    \"{clip_text}\"")
        print(f"    --- end transcript text ---")

        parsed.append({
            "start": start,
            "end": end,
            "hook": re.sub(r"\s+", " ", c["hook"]).strip(),
            "reason": c.get("reason", "").strip(),
            "transcript_text": clip_text,
        })

    if not parsed:
        raise ValueError("LLM did not return any usable clips - try again or check the transcript.")

    sorted_clips = sorted(parsed, key=lambda c: c["start"])
    for a, b in zip(sorted_clips, sorted_clips[1:]):
        if b["start"] < a["end"]:
            print(f"[clip_selector] WARNING - overlap detected: clip ending at "
                  f"{_fmt(a['end'])} overlaps clip starting at {_fmt(b['start'])}")

    print("\n" + "=" * 70)
    print(f"[clip_selector] FINAL SUMMARY - {len(parsed)} clip(s) accepted:")
    print("=" * 70)
    for i, c in enumerate(parsed, start=1):
        duration = c["end"] - c["start"]
        print(f"  Clip {i}:")
        print(f"    Time range : {_fmt(c['start'])} -> {_fmt(c['end'])}  ({duration:.1f}s)")
        print(f"    Hook       : \"{c['hook']}\"")
        print(f"    Reason     : {c['reason']}")
        print(f"    Transcript : \"{c['transcript_text']}\"")
    print("=" * 70 + "\n")

    return parsed