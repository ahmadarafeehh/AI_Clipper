"""
Step 4: Cut the selected time range out of the source video, optionally
reframing it to vertical 9:16 (blurred, zoomed background + centered
foreground - the standard Shorts/Reels look).
"""
import subprocess
from pathlib import Path
import config


def cut_clip(video_path: Path, start: float, end: float, output_path: Path,
             vertical: bool = None) -> Path:
    if vertical is None:
        vertical = config.VERTICAL_OUTPUT
    duration = end - start
    w, h = config.VERTICAL_SIZE

    # --- Step 1: precise trim, NO filters involved ---
    # Combining seeking with a filter_complex (blur/overlay for vertical
    # reframing) in a single ffmpeg call can let the filter graph see frames
    # the seek/trim hasn't dropped yet, causing a small but consistent leak
    # of extra footage before the real start (~1s in practice). Splitting
    # trim and filtering into two separate ffmpeg calls removes any chance
    # of that interaction: this step ONLY trims, with no filter_complex at
    # all, so the output starts and ends exactly where requested.
    seek_buffer = 5.0
    fast_seek = max(0.0, start - seek_buffer)
    precise_offset = start - fast_seek

    trimmed_path = output_path.with_name(output_path.stem + "_trimmed_tmp.mp4")
    trim_cmd = [
        "ffmpeg", "-y",
        "-ss", f"{fast_seek:.3f}",       # fast, approximate seek (before -i)
        "-i", str(video_path),
        "-ss", f"{precise_offset:.3f}",  # precise, frame-accurate seek (after -i)
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(trimmed_path),
    ]
    subprocess.run(trim_cmd, check=True, capture_output=True)

    # --- Step 2: apply vertical reframing (or just pass through) ---
    # This step never seeks - it processes the WHOLE trimmed file from its
    # own t=0, so there's no seeking/filter interaction left to go wrong.
    if vertical:
        filter_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=20[bg];"
            f"[0:v]scale={w}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
        )
        filter_cmd = [
            "ffmpeg", "-y",
            "-i", str(trimmed_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        subprocess.run(filter_cmd, check=True, capture_output=True)
        trimmed_path.unlink(missing_ok=True)
    else:
        trimmed_path.replace(output_path)

    print(f"[video_editor] Cut clip -> {output_path} "
          f"(requested {start:.2f}s-{end:.2f}s, fast-seek to {fast_seek:.2f}s "
          f"+ precise offset {precise_offset:.2f}s, trim and filter done in separate passes)")
    return output_path