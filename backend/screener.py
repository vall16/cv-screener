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
_PROFILES_FILE = Path(__file__).resolve().parent / "profiles.json"
_SHORTLIST_FILE = Path(__file__).resolve().parent / "shortlist.json"

_jobs: dict[str, dict] = {}
_sessions: dict[str, dict] = {}
_profiles: dict[str, dict] = {}
_shortlist: dict[str, dict[str, str]] = {}  # {session_id: {filename: status}}
_lock = threading.Lock()
_MAX_OUTPUT_LINES = 500
_procs: dict[str, subprocess.Popen] = {}  # job_id -> processo qwen in corso


def _atomic_write(path: Path, data: str) -> None:
    """Scrivi in .tmp poi os.replace: se il processo muore a metà, il file originale resta intatto."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)


def _save_jobs() -> None:
    """Persiste i job su disco (chiamare dentro _lock)."""
    try:
        _atomic_write(_JOBS_FILE, json.dumps(_jobs, ensure_ascii=False, indent=2))
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
        _atomic_write(_SESSIONS_FILE, json.dumps(_sessions, ensure_ascii=False, indent=2))
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


def _save_profiles() -> None:
    try:
        _atomic_write(_PROFILES_FILE, json.dumps(_profiles, ensure_ascii=False, indent=2))
    except OSError:
        pass


def _save_shortlist() -> None:
    try:
        _atomic_write(_SHORTLIST_FILE, json.dumps(_shortlist, ensure_ascii=False, indent=2))
    except OSError:
        pass


def _load_shortlist() -> None:
    global _shortlist
    if not _SHORTLIST_FILE.is_file():
        return
    try:
        _shortlist = json.loads(_SHORTLIST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _shortlist = {}


def _load_profiles() -> None:
    global _profiles
    if not _PROFILES_FILE.is_file():
        return
    try:
        data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
        for pid, p in data.items():
            _profiles[pid] = p
    except (json.JSONDecodeError, OSError):
        pass


_load_jobs()
_load_sessions()
_load_profiles()
_load_shortlist()


def list_profiles() -> list[dict]:
    with _lock:
        return sorted(_profiles.values(), key=lambda p: p.get("name", ""), )


def save_profile(name: str, profile: str) -> dict:
    pid = _slugify(name)
    with _lock:
        _profiles[pid] = {"id": pid, "name": name, "profile": profile}
        _save_profiles()
        return _profiles[pid]


def delete_profile(pid: str) -> bool:
    with _lock:
        if pid in _profiles:
            del _profiles[pid]
            _save_profiles()
            return True
    return False


# ── Shortlist / Tracking ──────────────────────────────
_VALID_STATUSES = {"", "screened", "interview", "interviewed", "offer", "hired", "rejected"}


def _normalize_entry(val) -> dict:
    """Converte un valore legacy (stringa) o nuovo (dict) nel formato dict."""
    if isinstance(val, str):
        return {"status": val, "note": "", "updated_at": ""}
    if isinstance(val, dict):
        return {
            "status": val.get("status", ""),
            "note": val.get("note", ""),
            "updated_at": val.get("updated_at", ""),
        }
    return {"status": "", "note": "", "updated_at": ""}


def get_shortlist(session_id: str | None = None) -> dict[str, dict]:
    with _lock:
        if session_id:
            raw = _shortlist.get(session_id, {})
            return {k: _normalize_entry(v) for k, v in raw.items()}
        merged: dict[str, dict] = {}
        for s in _shortlist.values():
            for k, v in s.items():
                merged[k] = _normalize_entry(v)
        return merged


def set_shortlist_status(session_id: str, filename: str, status: str, note: str = "") -> dict[str, dict]:
    if status not in _VALID_STATUSES:
        raise ValueError(f"Stato non valido: {status}")
    with _lock:
        if status == "" and not note:
            _shortlist.get(session_id, {}).pop(filename, None)
        else:
            _shortlist.setdefault(session_id, {})[filename] = {
                "status": status,
                "note": note,
                "updated_at": _now_iso(),
            }
        _save_shortlist()
        return {k: _normalize_entry(v) for k, v in _shortlist.get(session_id, {}).items()}


def get_all_tracking() -> list[dict]:
    """Aggrega tutti i candidati di tutte le sessioni con i loro dati di tracking."""
    with _lock:
        sessions = dict(_sessions)
        shortlist = {sid: {k: _normalize_entry(v) for k, v in entries.items()} for sid, entries in _shortlist.items()}
    out: list[dict] = []
    for sid, session in sessions.items():
        candidates = get_candidates_summary(sid)
        tracking = shortlist.get(sid, {})
        for c in candidates:
            t = tracking.get(c["file"], {"status": "", "note": "", "updated_at": ""})
            out.append({
                "name": c["name"],
                "file": c["file"],
                "score": c["score"],
                "giudizio": c["giudizio"],
                "esperienza": c["esperienza"],
                "session_id": sid,
                "session_name": session.get("name", sid),
                "status": t["status"],
                "note": t["note"],
                "updated_at": t["updated_at"],
            })
    # Candidati legacy (senza sessione)
    legacy_candidates = get_candidates_summary(None)
    legacy_tracking = shortlist.get("", {"": {"status": "", "note": "", "updated_at": ""}})
    for c in legacy_candidates:
        t = legacy_tracking.get(c["file"], {"status": "", "note": "", "updated_at": ""})
        out.append({
            "name": c["name"],
            "file": c["file"],
            "score": c["score"],
            "giudizio": c["giudizio"],
            "esperienza": c["esperienza"],
            "session_id": "",
            "session_name": "—",
            "status": t["status"],
            "note": t["note"],
            "updated_at": t["updated_at"],
        })
    return out


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


def list_cv_details(cv_dir: Path | None = None) -> list[dict]:
    """Metadati dei CV (nome, dimensione in byte, data modifica ISO) per la UI."""
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    allowed = (".pdf", ".txt")
    details = []
    for p in sorted(folder.iterdir()):
        if not (p.is_file() and p.suffix.lower() in allowed):
            continue
        st = p.stat()
        details.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        })
    return details


def _safe_name(name: str) -> str | None:
    """Rifiuta nomi con separatori o '..' (path traversal)."""
    if not name or name != Path(name).name:
        return None
    return name


def delete_cv(name: str, cv_dir: Path | None = None) -> bool:
    safe = _safe_name(name)
    if safe is None:
        return False
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    target = folder / safe
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
    safe = _safe_name(name)
    if safe is None:
        return None
    target = _report_dir_for(session_id) / safe
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
        return "Sì passa"
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


def delete_job(job_id: str) -> bool:
    with _lock:
        if job_id not in _jobs:
            return False
        del _jobs[job_id]
        _save_jobs()
    return True


def _cv_prefix(name: str) -> str:
    """Prefisso di un nome CV: nome candidato senza il suffisso <YYYYMMDD>_<HHMMSS>.

    I file Indeed sono nominati <NomeCandidato>_<YYYYMMDD>_<HHMMSS>.pdf e cambiano
    nome a ogni download (nuovo timestamp), quindi il prefisso è la chiave stabile
    per riconoscere lo stesso candidato.
    """
    m = re.match(r"^(.*)_\d{8}_\d{6}\.\w+$", name, re.IGNORECASE)
    return (m.group(1) if m else Path(name).stem).strip().lower()


def _resolve_cv_names(cv_names: list[str], folder: Path) -> list[str]:
    """Risolvi i nomi CV sui file reali in `folder`.

    I nomi salvati in una posizione possono non esistere piu' dopo un ri-download
    (il timestamp nel nome cambia). Per ogni nome assente, prova l'abbinamento per
    prefisso (nome candidato) contro i file attuali. Ritorna i nomi risolti, senza
    duplicati, nell'ordine originale.
    """
    existing = {p.name for p in folder.iterdir() if p.is_file()}
    by_prefix: dict[str, list[str]] = {}
    for name in existing:
        by_prefix.setdefault(_cv_prefix(name), []).append(name)

    resolved: list[str] = []
    seen: set[str] = set()
    for name in cv_names:
        if name in existing:
            pick = name
        else:
            cands = by_prefix.get(_cv_prefix(name), [])
            pick = sorted(cands)[0] if cands else None
        if pick and pick not in seen:
            resolved.append(pick)
            seen.add(pick)
    return resolved


def start_job(
    profile: str,
    cv_dir: Path | None = None,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
) -> dict:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    if cv_names:
        cv_names = _resolve_cv_names(cv_names, folder)
        if not cv_names:
            raise FileNotFoundError("Nessun CV valido nella selezione (tutti i file sono stati rimossi)")
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


def _find_qwen() -> list[str]:
    """Ritorna la lista di comando per lanciare Qwen Code (gestisce gli shim npm su Windows)."""
    exe = shutil.which("qwen")
    if not exe:
        raise FileNotFoundError(
            "qwen (Qwen Code) non trovato nel PATH. Installalo (npm i -g @qwen-code/qwen-code) e riprova."
        )
    path = Path(exe)
    if path.suffix.lower() in (".cmd", ".bat"):
        # Shim npm Windows: lancia direttamente `node cli-entry.js` per evitare il
        # quoting di cmd.exe con prompt lunghi.
        entry = path.parent / "node_modules" / "@qwen-code" / "qwen-code" / "cli-entry.js"
        if entry.is_file():
            return ["node", str(entry)]
        return ["cmd", "/c", str(path)]
    return [str(path)]


def _recruiter_instructions() -> str:
    """Corpo delle istruzioni del recruiter (da .opencode/agent/hr-recruiter.md, senza frontmatter)."""
    agent_file = BASE_DIR / ".opencode" / "agent" / "hr-recruiter.md"
    try:
        text = agent_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def _candidate_name(cv_name: str) -> str:
    """Nome candidato dal nome file CV, senza suffisso <YYYYMMDD>_<HHMMSS> (case preservata)."""
    m = re.match(r"^(.*)_\d{8}_\d{6}\.\w+$", cv_name, re.IGNORECASE)
    return (m.group(1) if m else Path(cv_name).stem).strip()


def _is_cancelled(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return job is None or job["status"] != "running"


def _run_qwen_once(job_id: str, prompt: str, timeout: int) -> tuple[bool, str | None]:
    """Lancia una singola sessione qwen headless e streama l'output nel job."""
    cmd = _find_qwen() + ["--yolo", "-o", "text", prompt]
    env = os.environ.copy()
    env["QWEN_CODE_SUPPRESS_YOLO_WARNING"] = "1"
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
    _procs[job_id] = proc
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_output(_jobs[job_id], line.rstrip("\n"))
        proc.wait(timeout=timeout)
        if proc.returncode == 0:
            return True, None
        return False, f"qwen uscito con codice {proc.returncode}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False, f"Timeout: qwen non ha terminato entro {timeout // 60} min"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        _procs.pop(job_id, None)


def _run_qwen_with_retry(
    job_id: str, prompt: str, attempts: int, timeout: int
) -> tuple[bool, str | None]:
    error: str | None = None
    for attempt in range(1, attempts + 1):
        if _is_cancelled(job_id):
            return False, "annullato"
        if attempt > 1:
            _append_output(_jobs[job_id], f"\n[retry {attempt}/{attempts}] qwen fallito, rilancio…\n")
        ok, error = _run_qwen_once(job_id, prompt, timeout)
        if ok:
            return True, None
    return False, error


def _run(
    job_id: str,
    profile: str,
    cv_dir: Path,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
) -> None:
    """Screening a sessioni singole: una sessione qwen per CV, poi una finale per la classifica."""
    report_dir = _report_dir_for(session_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    if not cv_names:
        cv_names = sorted(
            p.name
            for p in cv_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".txt", ".docx")
        )
    if not cv_names:
        _finish(job_id, "error", "Nessun CV trovato nella cartella")
        return
    instructions = _recruiter_instructions()
    total = len(cv_names)
    failed: list[str] = []
    for idx, cv in enumerate(cv_names, start=1):
        if _is_cancelled(job_id):
            return
        candidate = _candidate_name(cv)
        report_name = f"{idx:02d}-{candidate}.md"
        _append_output(_jobs[job_id], f"\n[{idx}/{total}] {cv} — avvio analisi…\n")
        task = (
            f"Analizza il CV: {cv_dir / cv}\n"
            f"Profilo target: '{profile}'.\n\n"
            f"Esegui la procedura completa di screening per questo singolo CV e scrivi il report "
            f"ESCLUSIVAMENTE nel file: {report_dir / report_name}\n"
            f"Non scrivere altri file: niente classifica.md, niente altre cartelle."
        )
        prompt = f"{instructions}\n\n{task}" if instructions else task
        ok, err = _run_qwen_with_retry(job_id, prompt, attempts=2, timeout=3600)
        if _is_cancelled(job_id):
            return
        if ok:
            _append_output(_jobs[job_id], f"[{idx}/{total}] {cv} — report scritto ({report_name})\n")
        else:
            failed.append(cv)
            _append_output(_jobs[job_id], f"[{idx}/{total}] {cv} — ERRORE: {err}\n")
    if _is_cancelled(job_id):
        return
    _append_output(_jobs[job_id], f"\n[{total + 1}/{total + 1}] Generazione classifica.md…\n")
    task = (
        f"Leggi tutti i report .md nella cartella {report_dir} (ignora classifica.md se esiste) "
        f"e scrivi {report_dir / 'classifica.md'} con tabella comparativa completa, top-3 motivata "
        f"e lista degli scartati con motivo.\n"
        f"Profilo target: '{profile}'.\n"
        f"Non riscrivere i report singoli."
    )
    prompt = f"{instructions}\n\n{task}" if instructions else task
    ok, err = _run_qwen_with_retry(job_id, prompt, attempts=2, timeout=3600)
    if _is_cancelled(job_id):
        return
    if ok:
        _finish(job_id, "done")
    else:
        _finish(job_id, "error", f"Classifica non generata: {err}")


def cancel_job(job_id: str) -> bool:
    """Uccide il processo qwen del job e lo marca come 'cancelled'."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["status"] != "running":
            return False
    proc = _procs.get(job_id)
    if proc is not None and proc.poll() is None:
        proc.kill()
        proc.wait()
    _procs.pop(job_id, None)
    _finish(job_id, "cancelled", "Job annullato dall'utente")
    return True