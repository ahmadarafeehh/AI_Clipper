"""
Usage (CLI, unchanged):
    python main.py "https://www.youtube.com/watch?v=XXXXXXXX"
    python main.py "<url>" --clips 5 --no-vertical --length 30 --no-hook --no-captions
"""
import argparse
import json
import shutil
import config
from pipeline import downloader, transcriber, clip_selector, video_editor, captions, hook


def run(url: str, num_clips: int, vertical: bool, clip_length: int = 30,
        add_captions: bool = True, add_hook: bool = True, progress=None):
    """
    progress: optional callable(stage: str, message: str) used by the web UI
    to report status. Safe to leave as None for CLI use (falls back to print).
    """
    def report(stage, message):
        print(message)
        if progress:
            progress(stage, message)

    config.NUM_CLIPS = num_clips
    config.VERTICAL_OUTPUT = vertical
    # Translate the requested target clip length into a min/max range the
    # LLM clip selector can work with, instead of the old fixed 20-90s range.
    config.MIN_CLIP_SECONDS = max(5, clip_length - 5)
    config.MAX_CLIP_SECONDS = clip_length + 5

    report("download", "=== 1/4: Downloading video ===")
    video_path = downloader.download_video(url)

    report("transcribe", "=== 2/4: Transcribing full video (Groq Whisper) ===")
    transcript = transcriber.transcribe_full_video(video_path)
    (config.WORK_DIR / "transcript.txt").write_text(transcript, encoding="utf-8")
    report("transcribe", f"[main] Transcript saved to {config.WORK_DIR / 'transcript.txt'}")

    report("select", "=== 3/4: Selecting clips + writing hooks (Groq LLM) ===")
    clips = clip_selector.select_clips(transcript)
    (config.WORK_DIR / "clips_manifest.json").write_text(
        json.dumps(clips, indent=2), encoding="utf-8"
    )

    report("render", "=== 4/4: Cutting clips, captioning, adding hooks ===")
    results = []
    for i, clip in enumerate(clips, start=1):
        report("render", f"--- Clip {i}/{len(clips)} ({clip['start']:.0f}s-{clip['end']:.0f}s) ---")

        cut_path = config.WORK_DIR / f"clip_{i}_cut.mp4"
        video_editor.cut_clip(video_path, clip["start"], clip["end"], cut_path)
        current_path = cut_path

        if add_captions:
            # Use the ALREADY-CUT clip (starts at t=0) to generate word
            # timestamps for captions, instead of seeking into the original
            # full video again with clip["start"]/clip["end"]. Seeking twice
            # into the source video independently (once to cut the clip,
            # once to grab caption audio) can land on slightly different
            # actual start points due to keyframe rounding, which causes a
            # caption from just-before-the-clip to flash briefly at the
            # start. Transcribing the cut clip itself removes that second
            # seek entirely - there's nothing for it to disagree with.
            words = transcriber.transcribe_clip_words(cut_path, 0.0, clip["end"] - clip["start"])
            captioned_path = config.WORK_DIR / f"clip_{i}_captioned.mp4"
            captions.burn_captions(current_path, words, captioned_path)
            current_path = captioned_path

        final_path = config.OUTPUT_DIR / f"clip_{i}.mp4"
        if add_hook:
            hook.add_hook(current_path, clip["hook"], final_path)
        else:
            shutil.copy(current_path, final_path)

        results.append({**clip, "file": str(final_path)})
        report("render", f"  -> {final_path}")

    manifest_path = config.OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    report("done", "=== Done ===")
    for r in results:
        report("done", f"  {r['file']}   hook: \"{r['hook']}\"")
    report("done", f"Full manifest: {manifest_path}")

    # work/ holds intermediate files (raw cuts, captions, transcript) - safe to delete
    # shutil.rmtree(config.WORK_DIR)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Turn a YouTube video into short-form clips with AI-selected "
                     "highlights, burned-in captions, and hook text - powered by Groq."
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--clips", type=int, default=config.NUM_CLIPS, help="Number of clips to generate")
    parser.add_argument("--length", type=int, default=30, help="Target length per clip in seconds (15-60)")
    parser.add_argument("--no-vertical", action="store_true", help="Keep original aspect ratio instead of reframing to 9:16")
    parser.add_argument("--no-captions", action="store_true", help="Skip burning in captions")
    parser.add_argument("--no-hook", action="store_true", help="Skip the hook text overlay")
    args = parser.parse_args()
    run(
        args.url,
        num_clips=args.clips,
        vertical=not args.no_vertical,
        clip_length=args.length,
        add_captions=not args.no_captions,
        add_hook=not args.no_hook,
    )


if __name__ == "__main__":
    main()