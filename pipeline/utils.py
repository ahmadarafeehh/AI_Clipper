"""Small shared helpers used across pipeline modules."""
import json
import subprocess
from pathlib import Path


def get_resolution(video_path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    s = json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"]


def wrap_text(text: str, max_chars_per_line: int) -> str:
    """Greedy word-wrap. Returns text with '\\n' inserted between lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars_per_line and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)
