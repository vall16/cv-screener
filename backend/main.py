"""API FastAPI del progetto cv-screener."""
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import screener

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist" / "cv-screener"
if (FRONTEND_DIST / "browser").is_dir():
    FRONTEND_DIST = FRONTEND_DIST / "browser"

app = FastAPI(title="cv-screener", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ALLOWED_EXT = {".pdf", ".txt"}
_MAX_UPLOAD_MB = 15


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── CV ────────────────────────────────────────────────
@app.get("/api/cvs")
def api_list_cvs():
    return {"cvs": screener.list_cvs()}


@app.post("/api/cvs/upload")
async def api_upload_cvs(files: list[UploadFile] = File(...)):
    saved = []
    errors = []
    for f in files:
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in _ALLOWED_EXT:
            errors.append((name or "file") + ": formato non supportato (solo PDF/TXT)")
            continue
        if f.size and f.size > _MAX_UPLOAD_MB * 1024 * 1024:
            errors.append(f"{name}: oltre {_MAX_UPLOAD_MB} MB")
            continue
        target = screener.DEFAULT_CV_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        chunk = await f.read()
        if len(chunk) > _MAX_UPLOAD_MB * 1024 * 1024:
            errors.append(f"{name}: oltre {_MAX_UPLOAD_MB} MB")
            continue
        target.write_bytes(chunk)
        saved.append(name)
    return {"saved": saved, "errors": errors, "cvs": screener.list_cvs()}


@app.delete("/api/cvs/{name}")
def api_delete_cv(name: str):
    if not screener.delete_cv(name):
        raise HTTPException(status_code=404, detail="CV non trovato")
    return {"ok": True}


# ── Jobs ──────────────────────────────────────────────
@app.get("/api/jobs")
def api_list_jobs():
    return {"jobs": screener.get_jobs()}


@app.post("/api/jobs")
def api_start_job(profile: str):
    if not profile or not profile.strip():
        raise HTTPException(status_code=422, detail="Inserisci il profilo target")
    if not screener.list_cvs():
        raise HTTPException(status_code=422, detail="Nessun CV presente nella cartella CVs")
    job = screener.start_job(profile.strip())
    return {"job": job}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    job = screener.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return {"job": job}


# ── Report ────────────────────────────────────────────
@app.get("/api/reports")
def api_list_reports():
    return {"reports": screener.list_reports()}


@app.get("/api/reports/{name}")
def api_get_report(name: str):
    content = screener.read_report(name)
    if content is None:
        raise HTTPException(status_code=404, detail="Report non trovato")
    return {"name": name, "content": content}


# ── Frontend statico (build) ──────────────────────────
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)