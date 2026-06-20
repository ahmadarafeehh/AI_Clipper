"""
Step 6: Overlay the LLM-written "hook" line near the top of the clip, the
way a human editor adds the big bold scroll-stopping text on Shorts/Reels.
"""
import os
import subprocess
from pathlib import Path

from PIL import ImageFont

import config
from pipeline.utils import get_resolution


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if not config.HOOK_FONT_FILE:
        raise RuntimeError(
            "config.HOOK_FONT_FILE must point to a real .ttf so we can measure "
            "exact glyph widths for wrapping. (It's the same reason drawtext "
            "needs it to dodge the broken fontconfig name lookup on Windows.)"
        )
    return ImageFont.truetype(config.HOOK_FONT_FILE, size)


def _line_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    # getbbox returns (left, top, right, bottom). For some fonts/glyphs
    # "left" isn't 0, so subtract it out to get the true advance width -
    # this is the number that actually matters for "will it fit".
    left, _, right, _ = font.getbbox(text)
    return right - left


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _line_width(font, candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_hook_text(hook_text: str, video_width: int) -> tuple[str, int]:
    """Wrap the hook to fit the frame using *real* measured glyph widths
    (the old heuristic - width / (fontsize * 0.58) - was an approximation
    that ran wide on bold caps text, which is what caused lines to overflow
    the frame and get clipped on both edges by the x=(w-text_w)/2 centering).

    If a hook is long enough that it still wraps to more lines than
    config.HOOK_MAX_LINES even at max width, the font is shrunk a couple
    px at a time (down to config.HOOK_MIN_FONT_SIZE) and re-wrapped, same
    as how caption apps auto-fit a card of text.

    Returns (text_with_real_newlines, font_size_used).
    """
    # Account for: side safe-zone margins (so text doesn't kiss the frame
    # edges) AND the "box" padding ffmpeg adds around each line (boxborderw
    # extends past text_w on both sides, so it needs to be subtracted too
    # or the *box* clips even when the text itself would have fit).
    safe_width = (
        int(video_width * (1 - 2 * config.HOOK_SIDE_MARGIN_PCT))
        - 2 * config.HOOK_BOX_BORDER
    )
    upper = hook_text.upper()
    font_size = config.HOOK_FONT_SIZE

    while True:
        font = _load_font(font_size)
        lines = _wrap_to_width(upper, font, safe_width)
        longest_line = max(_line_width(font, line) for line in lines)
        fits = longest_line <= safe_width and len(lines) <= config.HOOK_MAX_LINES
        if fits or font_size <= config.HOOK_MIN_FONT_SIZE:
            return "\n".join(lines), font_size
        font_size -= 2


def add_hook(video_path: Path, hook_text: str, output_path: Path) -> Path:
    video_path = Path(video_path)
    output_path = Path(output_path)
    width, height = get_resolution(video_path)

    wrapped, font_size = _fit_hook_text(hook_text, width)
    textfile = config.WORK_DIR / "hook_text.txt"
    # IMPORTANT: don't use textfile.write_text() here. On Windows, text-mode
    # writes silently translate every "\n" into "\r\n" (os.linesep). FFmpeg's
    # drawtext reads the textfile byte-for-byte and treats that stray "\r"
    # as its own line break, so a 2-line hook becomes 3 visual lines (line,
    # blank, line) - the big gap between lines. newline="\n" forces the
    # literal bytes we built, no OS translation.
    with open(textfile, "w", encoding="utf-8", newline="\n") as f:
        f.write(wrapped)

    # --- Run ffmpeg with cwd set to WORK_DIR so every path is relative.
    # Same reasoning as captions.py: absolute Windows paths (with a drive
    # letter colon) fed into ffmpeg's filtergraph parser break things even
    # when escaped, since drawtext's textfile/fontfile args also use ":" as
    # an internal separator. Relative paths sidestep this entirely.
    work_dir = config.WORK_DIR.resolve()

    def _rel(p: Path) -> str:
        p = Path(p).resolve()
        try:
            rel = p.relative_to(work_dir)
        except ValueError:
            rel = Path(os.path.relpath(p, work_dir))
        return rel.as_posix()

    def _path_arg(p: Path) -> str:
        """Relative path if possible (same drive as work_dir), else fall
        back to an absolute path with the drive-letter colon escaped -
        ffmpeg filter args use ":" as a separator, so any literal colon
        in the path (e.g. "C:") must be escaped as "\\:". This only
        triggers for paths outside the project drive, e.g. system fonts."""
        p = Path(p).resolve()
        try:
            return p.relative_to(work_dir).as_posix()
        except ValueError:
            try:
                return Path(os.path.relpath(p, work_dir)).as_posix()
            except ValueError:
                # different drive on Windows - relpath is impossible
                return str(p).replace("\\", "/").replace(":", "\\:")

    video_rel = _rel(video_path)
    output_rel = _rel(output_path)
    textfile_rel = _rel(textfile)

    if config.HOOK_FONT_FILE:
        fontfile_arg = _path_arg(Path(config.HOOK_FONT_FILE))
        font_arg = f"fontfile='{fontfile_arg}'"
    else:
        font_arg = f"font='{config.HOOK_FONT}'"

    # Sits ~12-18% down from the top by default (config.HOOK_Y_POSITION_PCT)
    # instead of hugging the very top edge. Top-performing Shorts/Reels
    # hooks almost never sit flush against the top: that zone is where the
    # platform's own UI (username, sound title, follow button) gets drawn
    # once the clip is posted, so text glued to the edge reads as cramped
    # or gets covered. ~12-18% reads as "first thing you see" while still
    # leaving breathing room above it.
    y_pos = int(height * config.HOOK_Y_POSITION_PCT)

    drawtext = (
        f"drawtext=textfile='{textfile_rel}':{font_arg}:"
        f"fontsize={font_size}:fontcolor=white:"
        f"borderw=4:bordercolor=black:"
        f"box=1:boxcolor=black@0.45:boxborderw={config.HOOK_BOX_BORDER}:"
        f"line_spacing=10:text_align=center:"
        f"x=(w-text_w)/2:y={y_pos}"
    )
    # text_align=center makes wrapped lines center as a block instead of
    # left-justifying against the longest line (FFmpeg's drawtext default
    # for multi-line text). Needs FFmpeg >= 6.1 (Nov 2023) - if you hit
    # "Unable to parse option value 'center'" on an older build, update
    # ffmpeg, or drop ":text_align=center" (hooks that fit on one line will
    # still look right; hooks that wrap to 2-3 lines will left-justify).

    if config.HOOK_DURATION_SECONDS:
        drawtext += f":enable='lt(t,{config.HOOK_DURATION_SECONDS})'"

    cmd = [
        "ffmpeg", "-y", "-i", video_rel,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        output_rel,
    ]

    result = subprocess.run(cmd, cwd=str(work_dir), capture_output=True)
    if result.returncode != 0:
        print("[hook] ffmpeg FAILED. Command:")
        print("  " + " ".join(cmd))
        print("[hook] ---- ffmpeg stderr ----")
        print(result.stderr.decode(errors="replace"))
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

    print(f"[hook] Added hook text -> {output_path} (font {font_size}px, {wrapped.count(chr(10)) + 1} line(s))")
    return output_path