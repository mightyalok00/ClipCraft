"""FastAPI Web Server with Real-Time SSE Job Streaming for ClipCraft."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

from config import SHORTS_DIR, load_config, save_config
from core.pipeline import process_video
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="ClipCraft — Next-Gen AI Video Clipper")

# Serve frontend static assets
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory job state and SSE event queues
JOBS: dict[str, dict[str, Any]] = {}
EVENT_QUEUES: dict[str, queue.Queue] = {}


class JobCreateRequest(BaseModel):
    source: str
    num_clips: int = 3
    content_type: str = "general"
    layout: str = "facetrack"
    captions: str = "bold_yellow"
    prompt: str = ""


class ConfigUpdateRequest(BaseModel):
    llm_provider: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str | None = None
    whisper_model: str | None = None
    whisper_device: str | None = None


def _background_worker(job_id: str, req: JobCreateRequest):
    q = EVENT_QUEUES.setdefault(job_id, queue.Queue())

    def on_progress(stage: str, frac: float, msg: str):
        payload = {"job_id": job_id, "stage": stage, "fraction": frac, "message": msg}
        q.put(payload)
        if job_id in JOBS:
            JOBS[job_id]["stage"] = stage
            JOBS[job_id]["fraction"] = frac
            JOBS[job_id]["message"] = msg

    try:
        manifest = process_video(
            source_url_or_path=req.source,
            num_clips=req.num_clips,
            content_type=req.content_type,
            layout=req.layout,
            captions=req.captions,
            prompt=req.prompt,
            progress_callback=on_progress,
        )
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["result"] = manifest
        q.put({"job_id": job_id, "stage": "completed", "fraction": 1.0, "message": "Done", "manifest": manifest})
    except Exception as e:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)
        q.put({"job_id": job_id, "stage": "error", "fraction": 0.0, "message": f"Failed: {e}"})


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>ClipCraft Dashboard Loading...</h1>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, bg: BackgroundTasks):
    job_id = f"job_{int(time.time())}"
    JOBS[job_id] = {
        "job_id": job_id,
        "source": req.source,
        "status": "running",
        "stage": "starting",
        "fraction": 0.0,
        "message": "Initializing job...",
        "created_at": time.time(),
        "request": req.dict(),
    }
    threading.Thread(target=_background_worker, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/api/jobs")
async def list_jobs():
    # Scan disk for saved manifests as well
    results = list(JOBS.values())
    if SHORTS_DIR.exists():
        for job_folder in sorted(SHORTS_DIR.iterdir(), reverse=True):
            manifest_file = job_folder / "job.json"
            if manifest_file.exists() and job_folder.name not in JOBS:
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    results.append({
                        "job_id": str(data.get("job_id")),
                        "source": data.get("source"),
                        "status": "completed",
                        "stage": "completed",
                        "fraction": 1.0,
                        "message": "Finished",
                        "result": data,
                        "created_at": data.get("created_at", 0),
                    })
                except (json.JSONDecodeError, OSError):
                    pass
    return sorted(results, key=lambda j: j.get("created_at", 0), reverse=True)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    q = EVENT_QUEUES.setdefault(job_id, queue.Queue())

    async def event_generator():
        while True:
            try:
                # Poll non-blocking with small sleep
                while not q.empty():
                    item = q.get_nowait()
                    yield f"data: {json.dumps(item)}\n\n"
                    if item.get("stage") in ("completed", "error"):
                        return
                await asyncio.sleep(0.3)
            except (asyncio.CancelledError, GeneratorExit):
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/clips/{job_id}/{filename}")
async def get_clip(job_id: str, filename: str):
    path = SHORTS_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(str(path), media_type="video/mp4")


@app.get("/api/config")
async def get_config():
    return load_config()


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    return save_config(updates)

