"""
Step 5: Build TikTok/CapCut-style burned-in captions: a few words on screen
at a time, with the current word highlighted as it's spoken (karaoke fill),
generated from Groq Whisper's word-level timestamps.
"""
import subprocess
import shutil
from pathlib import Path

import config
from pipeline.utils import get_resolution


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words: list[dict], video_path: Path, ass_path: Path) -> Path:
    width, height = get_resolution(video_path)
    font = config.CAPTION_FONT_FILE and Path(config.CAPTION_FONT_FILE).stem or config.CAPTION_FONT

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{config.CAPTION_FONT_SIZE},{config.CAPTION_HIGHLIGHT_COLOR},{config.CAPTION_COLOR},{config.CAPTION_OUTLINE_COLOR},&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,60,60,{config.CAPTION_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    n = config.CAPTION_WORDS_PER_CARD
    for i in range(0, len(words), n):
        card = words[i:i + n]
        if not card:
            continue
        card_start = card[0]["start"]
        card_end = card[-1]["end"]
        text_parts = []
        for w in card:
            dur_cs = max(1, round((w["end"] - w["start"]) * 100))
            text_parts.append(f"{{\\kf{dur_cs}}}{_escape(w['word'])} ")
        text = "".join(text_parts).strip()
        lines.append(
            f"Dialogue: 0,{_ass_time(card_start)},{_ass_time(card_end)},Default,,0,0,0,,{text}\n"
        )
    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


def burn_captions(video_path: Path, words: list[dict], output_path: Path) -> Path:
    video_path = Path(video_path)
    output_path = Path(output_path)

    if not words:
        # no words detected (e.g. silent clip) - just pass the video through
        shutil.copy(video_path, output_path)
        print(f"[captions] No words detected, copied video as-is -> {output_path}")
        return output_path

    ass_path = config.WORK_DIR / "captions.ass"
    build_ass(words, video_path, ass_path)

    # --- Run ffmpeg with cwd set to WORK_DIR so every path we pass it is
    # relative. This avoids the classic Windows problem where an absolute
    # path like "F:/.../captions.ass" gets fed into ffmpeg's filtergraph
    # parser, which treats ":" as an option separator. Escaping the colon
    # (F\:/...) is fragile and was causing silent/garbled failures.
    # Relative paths have no drive letter, so there's nothing to escape.
    work_dir = config.WORK_DIR.resolve()

    def _rel(p: Path) -> str:
        p = Path(p).resolve()
        try:
            rel = p.relative_to(work_dir)
        except ValueError:
            # Fallback for paths outside WORK_DIR (e.g. fonts dir as a sibling)
            import os
            rel = Path(os.path.relpath(p, work_dir))
        return rel.as_posix()

    video_rel = _rel(video_path)
    ass_rel = _rel(ass_path)
    fonts_rel = _rel(config.FONTS_DIR)
    output_rel = _rel(output_path)

    cmd = [
        "ffmpeg", "-y", "-i", video_rel,
        "-vf", f"ass={ass_rel}:fontsdir={fonts_rel}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        output_rel,
    ]

    result = subprocess.run(cmd, cwd=str(work_dir), capture_output=True)
    if result.returncode != 0:
        print("[captions] ffmpeg FAILED. Command:")
        print("  " + " ".join(cmd))
        print("[captions] ---- ffmpeg stderr ----")
        print(result.stderr.decode(errors="replace"))
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

    print(f"[captions] Burned in captions -> {output_path}")
    return output_path