"""FastAPI Web Server with Real-Time SSE Job Streaming, Security Guards, and Healthcheck."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

from config import SHORTS_DIR, detect_hardware, load_config, save_config
from core.logger import logger
from core.pipeline import process_video
from core.security import mask_secret, safe_resolve_path, validate_source
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

SERVER_START_TIME = time.time()

app = FastAPI(
    title="ClipCraft — Next-Gen AI Video Clipper",
    description="Universal AI shorts generation engine with real-time SSE streaming and GPU acceleration.",
    version="1.0.0",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Security Headers Middleware (pure ASGI middleware - zero overhead, deadlock-free)
class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"x-xss-protection", b"1; mode=block"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(SecurityHeadersMiddleware)


# Serve frontend static assets
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory job state, concurrency control, and SSE event queues
JOBS: dict[str, dict[str, Any]] = {}
EVENT_QUEUES: dict[str, queue.Queue] = {}
JOB_CANCEL_EVENTS: dict[str, threading.Event] = {}
JOB_SEMAPHORE = threading.Semaphore(2)


class JobCreateRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=2048, description="URL or local media path")
    num_clips: int = Field(3, ge=1, le=20, description="Clips to extract (1-20)")
    content_type: str = Field("general", pattern=r"^(general|gaming|podcast|educational|education|vlog)$")
    layout: str = Field("facetrack", pattern=r"^(facetrack|center|stacked|blur_padding)$")
    captions: str = Field("bold_yellow", pattern=r"^(bold_yellow|cyber_green|clean_minimal)$")
    prompt: str = Field("", max_length=1000, description="Custom prompt guidance")


class ConfigUpdateRequest(BaseModel):
    llm_provider: str | None = Field(None, pattern=r"^(gemini|groq|openai|ollama)$")
    gemini_api_key: str | None = Field(None, max_length=256)
    groq_api_key: str | None = Field(None, max_length=256)
    openai_api_key: str | None = Field(None, max_length=256)
    ollama_base_url: str | None = Field(None, max_length=512)
    whisper_model: str | None = Field(None, pattern=r"^(tiny|base|small|medium|large-v3)$")
    whisper_device: str | None = Field(None, pattern=r"^(auto|cuda|cpu)$")


def _background_worker(job_id: str, req: JobCreateRequest, cancel_event: threading.Event):
    q = EVENT_QUEUES.setdefault(job_id, queue.Queue())

    def on_progress(stage: str, frac: float, msg: str):
        payload = {"job_id": job_id, "stage": stage, "fraction": frac, "message": msg}
        q.put(payload)
        if job_id in JOBS:
            JOBS[job_id]["stage"] = stage
            JOBS[job_id]["fraction"] = frac
            JOBS[job_id]["message"] = msg

    try:
        with JOB_SEMAPHORE:
            if cancel_event.is_set():
                JOBS[job_id]["status"] = "cancelled"
                JOBS[job_id]["message"] = "Job cancelled before start"
                return

            logger.info(f"Starting job {job_id} for source: {req.source}")
            manifest = process_video(
                source_url_or_path=req.source,
                num_clips=req.num_clips,
                content_type=req.content_type,
                layout=req.layout,
                captions=req.captions,
                prompt=req.prompt,
                progress_callback=on_progress,
                cancel_event=cancel_event,
            )
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["result"] = manifest
            q.put({"job_id": job_id, "stage": "completed", "fraction": 1.0, "message": "Done", "manifest": manifest})
            logger.info(f"Job {job_id} completed successfully")
    except InterruptedError:
        logger.info(f"Job {job_id} cancelled by user.")
        JOBS[job_id]["status"] = "cancelled"
        JOBS[job_id]["message"] = "Job cancelled by user"
        q.put({"job_id": job_id, "stage": "cancelled", "fraction": 0.0, "message": "Cancelled"})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Job {job_id} failed: {e}")
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)
        q.put({"job_id": job_id, "stage": "error", "fraction": 0.0, "message": f"Failed: {e}"})


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>ClipCraft Dashboard Loading...</h1>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/health")
@app.get("/api/health")
async def health_check():
    """System health, hardware state, and resource utilization endpoint."""
    import shutil
    import psutil

    now = time.time()
    uptime = round(now - SERVER_START_TIME, 1)

    # Disk usage in GB
    total_b, used_b, free_b = shutil.disk_usage(str(SHORTS_DIR))
    disk_free_gb = round(free_b / (1024**3), 2)

    return {
        "status": "healthy",
        "service": "ClipCraft",
        "uptime_seconds": uptime,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_free_gb": disk_free_gb,
        "active_jobs": sum(1 for j in JOBS.values() if j.get("status") == "running"),
        "hardware": detect_hardware(),
    }


@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, bg: BackgroundTasks):
    """Validate source and initiate background video clipping job with concurrency control."""
    is_valid, err_msg = validate_source(req.source, allow_local=True)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Source validation rejected: {err_msg}")

    job_id = f"job_{int(time.time())}"
    cancel_event = threading.Event()
    JOB_CANCEL_EVENTS[job_id] = cancel_event

    JOBS[job_id] = {
        "job_id": job_id,
        "source": req.source,
        "status": "running",
        "stage": "starting",
        "fraction": 0.0,
        "message": "Initializing job...",
        "created_at": time.time(),
        "request": req.model_dump() if hasattr(req, "model_dump") else req.dict(),
    }
    threading.Thread(target=_background_worker, args=(job_id, req, cancel_event), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel an active or queued processing job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    cancel_event = JOB_CANCEL_EVENTS.get(job_id)
    if cancel_event:
        cancel_event.set()

    JOBS[job_id]["status"] = "cancelled"
    JOBS[job_id]["message"] = "Cancellation requested"
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/jobs")
async def list_jobs():
    """List running and historical jobs."""
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
    """Server-Sent Events (SSE) live progress stream."""
    q = EVENT_QUEUES.setdefault(job_id, queue.Queue())

    async def event_generator():
        while True:
            try:
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
    """Safely stream a generated video clip with strict path traversal prevention."""
    try:
        path = safe_resolve_path(SHORTS_DIR, job_id, filename)
    except (PermissionError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path or directory traversal detected") from None

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")

    return FileResponse(str(path), media_type="video/mp4")


@app.get("/api/config")
async def get_config():
    """Retrieve active system configuration with sensitive keys masked."""
    conf = load_config()
    safe_conf = {}
    for k, v in conf.items():
        if "api_key" in k and isinstance(v, str):
            safe_conf[k] = mask_secret(v)
            safe_conf[f"has_{k}"] = bool(v.strip())
        else:
            safe_conf[k] = v
    return safe_conf


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """Safely update configuration values."""
    raw_updates = req.model_dump(exclude_unset=True) if hasattr(req, "model_dump") else req.dict(exclude_unset=True)
    clean_updates = {}
    for k, v in raw_updates.items():
        if v is not None and isinstance(v, str):
            clean_updates[k] = v.strip()
    return save_config(clean_updates)
