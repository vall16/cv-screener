"""Gestore dei job di screening: lancia opencode in modalità agent e traccia lo stato."""
import json
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
_JOBS_FILE = Path(__file__).resolve().parent / "jobs.json"
_SESSIONS_FILE = Path(__file__).resolve().parent / "sessions.json"

_jobs: dict[str, dict] = {}
_sessions: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_OUTPUT_LINES = 500


def _save_jobs() -> None:
    """Persiste i job su disco (chiamare dentro _lock)."""
    try:
        _JOBS_FILE.write_text(json.dumps(_jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_jobs() -> None:
    """Ricarica i job dal disco all'avvio. I job 'running' diventano 'interrupted'."""
    global _jobs
    if not _JOBS_FILE.is_file():
        return
    try:
        data = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
        for jid, job in data.items():
            if job.get("status") == "running":
                job["status"] = "interrupted"
                job["error"] = "Backend riavviato durante l'esecuzione"
            _jobs[jid] = job
    except (json.JSONDecodeError, OSError):
        pass


def _save_sessions() -> None:
    """Persiste le sessioni su disco (chiamare dentro _lock)."""
    try:
        _SESSIONS_FILE.write_text(json.dumps(_sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_sessions() -> None:
    global _sessions
    if not _SESSIONS_FILE.is_file():
        return
    try:
        data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        for sid, s in data.items():
            _sessions[sid] = s
    except (json.JSONDecodeError, OSError):
        pass


_load_jobs()
_load_sessions()


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


def _report_dir_for(session_id: str | None = None) -> Path:
    """Cartella report: _report/ per i report legacy (senza sessione), _report/<sid>/ per una sessione."""
    base = DEFAULT_CV_DIR / REPORT_DIR_NAME
    if session_id:
        return base / session_id
    return base


def list_reports(session_id: str | None = None) -> list[str]:
    report_dir = _report_dir_for(session_id)
    if not report_dir.is_dir():
        return []
    return sorted(p.name for p in report_dir.glob("*.md"))


def read_report(name: str, session_id: str | None = None) -> str | None:
    target = _report_dir_for(session_id) / name
    if target.is_file() and target.suffix.lower() == ".md":
        return target.read_text(encoding="utf-8", errors="replace")
    return None


def _field(content: str, label: str) -> str | None:
    """Estrae il valore di una riga '- **<label>...:** <valore>' da un report markdown.

    Prende la prima riga che contiene <label> e il testo dopo il primo ':' che segue
    la label, così i ':' dentro il valore (es. '10 anni: backend') non rompono l'estrazione.
    """
    for line in content.splitlines():
        low = line.lower()
        idx = low.find(label.lower())
        if idx < 0:
            continue
        rest = line[idx + len(label):]
        if ":" in rest:
            val = rest.split(":", 1)[1].replace("*", "").strip()
            return val or None
    return None


def _normalize_giudizio(value: str | None) -> str | None:
    if not value:
        return None
    v = value.lower().strip()
    if "passa" in v:
        return "Si passa"
    if "valuta" in v:
        return "Da valutare"
    if v.startswith("no"):
        return "No"
    return value.strip()


def _nome_from_filename(name: str) -> str:
    stem = Path(name).stem
    m = re.match(r"^\d+\s*[-–]\s*(.+)$", stem)
    if m:
        return m.group(1).strip()
    return stem


def parse_candidate(name: str, content: str) -> dict | None:
    """Estrae i campi strutturati da un report per-candidato.

    Ritorna None se il file non sembra un report per-candidato (nè voto nè giudizio).
    """
    voto_raw = _field(content, "Voto complessivo")
    giudizio_raw = _field(content, "Giudizio")
    if voto_raw is None and giudizio_raw is None:
        return None

    score = None
    if voto_raw:
        m = re.search(r"\d+", voto_raw)
        if m:
            score = int(m.group(0))

    nome = _nome_from_filename(name)
    if len(nome) < 2:
        m = re.search(
            r"^#\s*Valutazione:\s*(.+?)(?:\s*[—–-]\s*|\s*$)",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            nome = m.group(1).strip()

    return {
        "name": nome,
        "file": name,
        "score": score,
        "giudizio": _normalize_giudizio(giudizio_raw),
        "esperienza": _field(content, "Esperienza totale"),
        "fit": _field(content, "Fit tecnico"),
    }


def get_candidates_summary(session_id: str | None = None) -> list[dict]:
    """Parsea i report per-candidato della sessione (o legacy) in _report/ (salvo classifica.md)."""
    report_dir = _report_dir_for(session_id)
    if not report_dir.is_dir():
        return []
    out = []
    for p in sorted(report_dir.glob("*.md")):
        if "classifica" in p.name.lower():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cand = parse_candidate(p.name, content)
        if cand:
            out.append(cand)
    return out


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "posizione"


def list_sessions() -> list[dict]:
    with _lock:
        return sorted(_sessions.values(), key=lambda s: s.get("created_at", ""), reverse=True)


def get_session(session_id: str) -> dict | None:
    with _lock:
        return _sessions.get(session_id)


def create_session(name: str, profile: str, cvs: list[str]) -> dict:
    """Crea una posizione (sessione) con il suo set di CV. I report andranno in _report/<id>/."""
    base = _slugify(name)
    with _lock:
        sid = base
        n = 2
        while sid in _sessions:
            sid = f"{base}-{n}"
            n += 1
        session = {
            "id": sid,
            "name": name.strip(),
            "profile": profile,
            "cvs": list(cvs),
            "created_at": _now_iso(),
        }
        _sessions[sid] = session
        _save_sessions()
    return session


def delete_session(session_id: str) -> bool:
    """Elimina la posizione e la sua cartella report."""
    with _lock:
        if session_id not in _sessions:
            return False
        del _sessions[session_id]
        _save_sessions()
    report_dir = _report_dir_for(session_id)
    if report_dir.is_dir():
        shutil.rmtree(report_dir, ignore_errors=True)
    return True


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def get_jobs() -> list[dict]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j["started"], reverse=True)


def start_job(
    profile: str,
    cv_dir: Path | None = None,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
) -> dict:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "profile": profile,
            "cv_dir": str(folder),
            "session_id": session_id,
            "cvs": list(cv_names) if cv_names else [],
            "output": [],
            "error": None,
            "reports": [],
            "started": _now_iso(),
            "finished": None,
        }
        job = _jobs[job_id]
        _save_jobs()
    threading.Thread(
        target=_run,
        args=(job_id, profile, folder, session_id, cv_names),
        daemon=True,
    ).start()
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
        report_dir = _report_dir_for(job.get("session_id"))
        if report_dir.is_dir():
            job["reports"] = sorted(p.name for p in report_dir.glob("*.md"))
        _save_jobs()


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


def _run(
    job_id: str,
    profile: str,
    cv_dir: Path,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
) -> None:
    report_dir = _report_dir_for(session_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    if session_id and cv_names:
        cv_list = "\n".join(f"- {cv_dir / c}" for c in cv_names)
        prompt = (
            f"Analizza SOLO i CV elencati qui sotto (ignora qualsiasi altro file). "
            f"Profilo target: '{profile}'.\n\n"
            f"CV da analizzare:\n{cv_list}\n\n"
            f"Esegui la procedura completa: per ogni CV scrivi un report singolo "
            f"(<Numero>-<NomeCandidato>.md), poi scrivi classifica.md con tabella comparativa e top-3.\n"
            f"Scrivi TUTTI i file (report e classifica.md) ESCLUSIVAMENTE nella cartella: {report_dir}\n"
            f"Non scrivere nulla nella cartella _report principale."
        )
    else:
        prompt = (
            f"Analizza i CV contenuti nella cartella {cv_dir} per il profilo target: "
            f"'{profile}'. Esegui la procedura completa: per ogni CV scrivi un report "
            f"singolo, poi scrivi classifica.md con tabella comparativa e top-3. "
            f"Scrivi tutto nella cartella {report_dir}."
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