from __future__ import annotations

import shutil
import uuid
import os
import subprocess
import sys
import time
from pathlib import Path
import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stl_repair.repair import RepairOptions, analyze_file, repair_file

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("STL_REPAIR_DATA_DIR", "/tmp/stl-repair" if os.environ.get("VERCEL") else BASE_DIR))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
JOBS_DIR = DATA_DIR / "jobs"

for directory in (UPLOAD_DIR, OUTPUT_DIR, JOBS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Local STL Repair")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "STL_REPAIR_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,https://stl-file-repair.vercel.app",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_private_network_access_header(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _safe_upload_name(filename: str) -> str:
    suffix = Path(filename or "model.stl").suffix.lower()
    if suffix not in {".stl", ".obj", ".ply"}:
        raise HTTPException(status_code=400, detail="Upload an STL, OBJ, or PLY mesh file.")
    return f"{uuid.uuid4().hex}{suffix}"


async def _save_upload(file: UploadFile) -> Path:
    upload_path = UPLOAD_DIR / _safe_upload_name(file.filename or "model.stl")
    with upload_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return upload_path


def _status_path(job_id: str) -> Path:
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=404, detail="Job not found.")
    return JOBS_DIR / f"{job_id}.json"


def _read_job(job_id: str) -> dict:
    path = _status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not read repair job status.") from exc


def _write_job(job_id: str, payload: dict) -> dict:
    payload["updated_at"] = time.time()
    path = _status_path(job_id)
    path.write_text(json.dumps(payload))
    return payload


def _update_job(job_id: str, payload: dict) -> dict:
    try:
        current = _read_job(job_id)
    except HTTPException:
        current = {"id": job_id}
    current.update(payload)
    return _write_job(job_id, current)


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, str | int]:
    return {
        "external_repair_api_url": os.environ.get("EXTERNAL_REPAIR_API_URL", "").rstrip("/"),
        "vercel_safe_upload_bytes": 4 * 1024 * 1024,
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)) -> dict:
    upload_path = await _save_upload(file)
    try:
        return {"filename": file.filename, "report": analyze_file(upload_path)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/repair")
async def repair(
    file: UploadFile = File(...),
    use_meshfix: bool = Form(True),
    join_components: bool = Form(True),
    remove_small_components: bool = Form(False),
) -> dict:
    upload_path = await _save_upload(file)
    output_name = f"{upload_path.stem}_repaired.stl"
    output_path = OUTPUT_DIR / output_name
    try:
        report = repair_file(
            upload_path,
            output_path=output_path,
            options=RepairOptions(
                use_meshfix=use_meshfix,
                join_components=join_components,
                remove_small_components=remove_small_components,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "filename": file.filename,
        "download_url": f"/download/{output_name}",
        "report": report,
    }


@app.post("/api/repair-job", status_code=202)
async def repair_job(
    file: UploadFile = File(...),
    use_meshfix: bool = Form(True),
    join_components: bool = Form(True),
    remove_small_components: bool = Form(False),
) -> dict:
    upload_path = await _save_upload(file)
    job_id = uuid.uuid4().hex
    output_name = f"{upload_path.stem}_repaired.stl"
    output_path = OUTPUT_DIR / output_name
    status_path = _status_path(job_id)
    _write_job(
        job_id,
        {
            "id": job_id,
            "filename": file.filename,
            "status": "queued",
            "stage": "starting",
            "started_at": time.time(),
            "output_name": output_name,
        },
    )
    command = [
        sys.executable,
        "-m",
        "stl_repair.job_runner",
        "--job-id",
        job_id,
        "--input",
        str(upload_path),
        "--output",
        str(output_path),
        "--status",
        str(status_path),
    ]
    if not use_meshfix:
        command.append("--no-meshfix")
    if not join_components:
        command.append("--keep-components")
    if remove_small_components:
        command.append("--remove-small-components")

    log_path = JOBS_DIR / f"{job_id}.log"
    log_handle = log_path.open("wb")
    try:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as exc:
        log_handle.close()
        _update_job(
            job_id,
            {
                "status": "failed",
                "stage": "failed",
                "error": f"Could not start repair job: {exc}",
                "finished_at": time.time(),
            },
        )
        raise HTTPException(status_code=500, detail=f"Could not start repair job: {exc}") from exc

    job = _update_job(
        job_id,
        {
            "pid": process.pid,
        },
    )
    return {"job": job}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = _read_job(job_id)
    if job.get("status") in {"queued", "running"} and not _pid_running(job.get("pid")):
        job = _write_job(
            job_id,
            {
                **job,
                "status": "failed",
                "stage": "failed",
                "error": "The local repair process stopped unexpectedly. This usually means MeshFix ran out of available memory on this mesh.",
                "finished_at": time.time(),
            },
        )
    if job.get("download_url"):
        job["download_url"] = str(job["download_url"])
    return {"job": job}


@app.get("/download/{filename}")
def download(filename: str) -> FileResponse:
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="model/stl", filename=filename)
