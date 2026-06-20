"""
Simple local web UI for the clipper pipeline.

Run with:
    python app.py
Then open http://127.0.0.1:5000 in your browser.
"""
import threading
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, render_template, send_from_directory

import config
import main as pipeline_main

app = Flask(__name__)

# In-memory job store. Fine for a single-user local tool.
JOBS = {}
JOBS_LOCK = threading.Lock()


def _make_progress_cb(job_id):
    def progress(stage, message):
        with JOBS_LOCK:
            job = JOBS[job_id]
            job["stage"] = stage
            job["log"].append(message)
            # keep the log from growing forever
            if len(job["log"]) > 200:
                job["log"] = job["log"][-200:]
    return progress


def _run_job(job_id, url, num_clips, vertical, clip_length, add_captions, add_hook):
    progress = _make_progress_cb(job_id)
    try:
        results = pipeline_main.run(
            url,
            num_clips=num_clips,
            vertical=vertical,
            clip_length=clip_length,
            add_captions=add_captions,
            add_hook=add_hook,
            progress=progress,
        )
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["results"] = [
                {**r, "filename": Path(r["file"]).name} for r in results
            ]
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)
            JOBS[job_id]["log"].append(f"ERROR: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "YouTube URL is required"}), 400

    num_clips = int(data.get("num_clips", config.NUM_CLIPS))
    vertical = bool(data.get("vertical", True))
    clip_length = int(data.get("clip_length", 30))
    add_captions = bool(data.get("add_captions", True))
    add_hook = bool(data.get("add_hook", True))

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "stage": "starting",
            "log": ["Job queued..."],
            "results": [],
            "error": None,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, url, num_clips, vertical, clip_length, add_captions, add_hook),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "unknown job_id"}), 404
        return jsonify(job)


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(config.OUTPUT_DIR, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
