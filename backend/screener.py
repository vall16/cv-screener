"""Gestore dei job di screening: lancia opencode in modalità agent e traccia lo stato."""
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CV_DIR = BASE_DIR / "CVs"
REPORT_DIR_NAME = "_report"

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_OUTPUT_LINES = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_cvs(cv_dir: Path | None = None) -> list[str]:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    allowed = (".pdf", ".txt")
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in allowed
    )


def delete_cv(name: str, cv_dir: Path | None = None) -> bool:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    target = folder / name
    if target.is_file() and target.suffix.lower() in (".pdf", ".txt"):
        target.unlink(missing_ok=True)
        return True
    return False


def list_reports(cv_dir: Path | None = None) -> list[str]:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    report_dir = folder / REPORT_DIR_NAME
    if not report_dir.is_dir():
        return []
    return sorted(p.name for p in report_dir.glob("*.md"))


def read_report(name: str, cv_dir: Path | None = None) -> str | None:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    target = folder / REPORT_DIR_NAME / name
    if target.is_file() and target.suffix.lower() == ".md":
        return target.read_text(encoding="utf-8", errors="replace")
    return None


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def get_jobs() -> list[dict]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j["started"], reverse=True)


def start_job(profile: str, cv_dir: Path | None = None) -> dict:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "profile": profile,
            "cv_dir": str(folder),
            "output": [],
            "error": None,
            "reports": [],
            "started": _now_iso(),
            "finished": None,
        }
        job = _jobs[job_id]
    threading.Thread(target=_run, args=(job_id, profile, folder), daemon=True).start()
    return job


def _append_output(job: dict, line: str) -> None:
    with _lock:
        job["output"].append(line)
        if len(job["output"]) > _MAX_OUTPUT_LINES:
            job["output"] = job["output"][-_MAX_OUTPUT_LINES:]


def _finish(job_id: str, status: str, error: str | None = None) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = status
        job["error"] = error
        job["finished"] = _now_iso()
        report_dir = Path(job["cv_dir"]) / REPORT_DIR_NAME
        if report_dir.is_dir():
            job["reports"] = sorted(p.name for p in report_dir.glob("*.md"))


def _find_opencode() -> list[str]:
    """Ritorna la lista di comando per lanciare opencode (gestisce gli shim .cmd di npm su Windows)."""
    exe = shutil.which("opencode")
    if not exe:
        raise FileNotFoundError(
            "opencode non trovato nel PATH. Installalo (npm i -g opencode-ai o via installer) e riprova."
        )
    path = Path(exe)
    suffix = path.suffix.lower()
    if suffix in (".cmd", ".bat", ".ps1"):
        # Gli shim npm contengono la chiamata al vero eseguibile (es. .\node_modules\opencode-ai\bin\opencode.exe).
        if suffix != ".ps1":
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'"([^"]*\\node_modules\\opencode-ai\\bin\\[^"]+)"', text)
                if m and Path(m.group(1)).is_file():
                    return [m.group(1)]
            except OSError:
                pass
        guess = path.parent / "node_modules" / "opencode-ai" / "bin"
        for name in ("opencode.exe", "opencode.js"):
            if (guess / name).is_file():
                return [str(guess / name)]
        return ["cmd", "/c", str(path)]
    return [str(path)]


def _run(job_id: str, profile: str, cv_dir: Path) -> None:
    prompt = (
        f"Analizza i CV contenuti nella cartella {cv_dir} per il profilo target: "
        f"'{profile}'. Esegui la procedura completa: per ogni CV scrivi un report "
        f"singolo, poi scrivi classifica.md con tabella comparativa e top-3. "
        f"Scrivi tutto nella sottocartella _report della cartella CV."
    )
    cmd = _find_opencode() + [
        "run",
        "--agent", "hr-recruiter",
        prompt,
        "--auto",
        "--format", "default",
    ]
    env = os.environ.copy()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_output(_jobs[job_id], line.rstrip("\n"))
        proc.wait(timeout=3600)
        status = "done" if proc.returncode == 0 else "error"
        error = None if proc.returncode == 0 else f"opencode uscito con codice {proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
    _finish(job_id, status, error)