from __future__ import annotations

import shutil
import uuid
import os
from pathlib import Path

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

for directory in (UPLOAD_DIR, OUTPUT_DIR):
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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


@app.get("/download/{filename}")
def download(filename: str) -> FileResponse:
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="model/stl", filename=filename)
