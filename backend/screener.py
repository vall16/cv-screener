"""Gestore dei job di screening: lancia opencode in modalità agent e traccia lo stato."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid 
from concurrent.futures import ThreadPoolExecutor, as_completed
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
_procs: dict[str, list[subprocess.Popen]] = {}  # job_id -> processi qwen in corso


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


def _fmt_duration(seconds: float | int | None) -> str:
    """Durata leggibile, es. '2 h 10 min 6 s' oppure '45 s'."""
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min {s} s"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


def _fmt_local(value: str | float | None) -> str:
    """Data/ora in fuso locale. Accetta una stringa ISO (UTC) o un timestamp epoch."""
    if value is None:
        return "—"
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OSError):
        return "—"
    return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def _record_candidate_timing(
    job_id: str,
    cv: str,
    report_name: str | None,
    started_ts: float,
    status: str,
    error: str | None = None,
) -> dict | None:
    """Salva (o aggiorna) i tempi di analisi del singolo CV nel job."""
    finished_ts = time.time()
    entry = {
        "cv": cv,
        "name": _candidate_name(cv),
        "report": report_name,
        "started": datetime.fromtimestamp(started_ts, timezone.utc).isoformat(),
        "finished": datetime.fromtimestamp(finished_ts, timezone.utc).isoformat(),
        "duration_seconds": round(finished_ts - started_ts, 1),
        "status": status,
        "error": error,
    }
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return entry
        candidates = job.setdefault("candidates", [])
        candidates[:] = [c for c in candidates if c.get("cv") != cv]
        candidates.append(entry)
        candidates.sort(key=lambda c: c.get("started", ""))
        _save_jobs()
    return entry


def _write_report_timing(path: Path, started_ts: float, finished_ts: float) -> None:
    """Aggiunge in coda al report del candidato una riga con inizio/fine/durata."""
    if not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    marker = "**Tempi di analisi:**"
    idx = content.find(marker)
    if idx >= 0:
        prefix = content[:idx]
        cut = prefix.rfind("\n---")
        content = prefix[:cut] if cut >= 0 else prefix
    block = (
        f"\n\n---\n\n{marker} inizio {_fmt_local(started_ts)} · "
        f"fine {_fmt_local(finished_ts)} · durata {_fmt_duration(finished_ts - started_ts)}\n"
    )
    _atomic_write(path, content.rstrip() + block)


def _write_classifica_timing(job_id: str, report_dir: Path) -> None:
    """Aggiunge alla classifica una sezione deterministica con i tempi totali e per CV."""
    path = report_dir / "classifica.md"
    if not path.is_file():
        return
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        started = job.get("started")
        finished = job.get("finished") or _now_iso()
        candidates = [dict(c) for c in job.get("candidates", [])]
    try:
        duration = (
            datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        ).total_seconds()
    except (ValueError, TypeError):
        duration = None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    marker = "## Tempi di esecuzione"
    idx = content.find(marker)
    if idx >= 0:
        content = content[:idx]
    lines = [
        "",
        marker,
        "",
        f"- **Inizio screening:** {_fmt_local(started)}",
        f"- **Fine screening:** {_fmt_local(finished)}",
        f"- **Durata totale:** {_fmt_duration(duration)}",
        "",
    ]
    if candidates:
        lines += [
            "| Candidato | Inizio | Fine | Durata |",
            "|---|---|---|---|",
        ]
        for c in candidates:
            lines.append(
                f"| {c.get('name', '')} | {_fmt_local(c.get('started'))} | "
                f"{_fmt_local(c.get('finished'))} | {_fmt_duration(c.get('duration_seconds'))} |"
            )
        lines.append("")
    _atomic_write(path, content.rstrip() + "\n" + "\n".join(lines))


def _flatten(value) -> str:
    """Riduce un valore (anche lista) a una singola riga di testo."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v is not None)
    return re.sub(r"\s+", " ", str(value)).strip()


def _shorten(value, limit: int) -> str:
    """Testo su una riga, troncato con ellissi oltre `limit` caratteri."""
    text = _flatten(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _md_cell(value) -> str:
    """Valore sicuro per una cella di tabella markdown."""
    return (_flatten(value) or "—").replace("|", "\\|")


def _sorted_candidates(candidates: list[dict]) -> list[dict]:
    """Ordina per voto decrescente; i candidati senza voto vanno in fondo."""
    return sorted(
        candidates,
        key=lambda c: (
            c.get("score") is None,
            -(c.get("score") or 0),
            str(c.get("name") or "").casefold(),
        ),
    )


def _fallback_summary(candidates: list[dict], failed: list[str]) -> str:
    """Riepilogo deterministico usato se la sintesi LLM non è disponibile."""
    total = len(candidates)
    counts = {"Sì passa": 0, "Da valutare": 0, "No": 0}
    for cand in candidates:
        giudizio = cand.get("giudizio")
        if giudizio in counts:
            counts[giudizio] += 1
    intro = "1 candidato analizzato" if total == 1 else f"{total} candidati analizzati"
    parts = [
        f"{intro}: {counts['Sì passa']} Sì passa, "
        f"{counts['Da valutare']} Da valutare, {counts['No']} No."
    ]
    scored = [c for c in candidates if c.get("score") is not None]
    if scored:
        best = max(scored, key=lambda c: c["score"])
        parts.append(f"Miglior punteggio: {_flatten(best.get('name')) or '—'} ({best['score']}/100).")
    if failed:
        parts.append(f"{len(failed)} CV non analizzati per errore.")
    return " ".join(parts)


def _build_classifica(
    profile: str,
    candidates: list[dict],
    failed: list[str],
    narrative: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Costruisce classifica.md dai dati strutturati (nessuna inferenza LLM)."""
    when = generated_at or datetime.now()
    ordered = _sorted_candidates(candidates)
    lines = [
        f"# Classifica — {_flatten(profile) or 'Profilo non specificato'}",
        "",
        f"_Generata il {when.strftime('%d/%m/%Y %H:%M')} · "
        f"{'1 candidato analizzato' if len(ordered) == 1 else f'{len(ordered)} candidati analizzati'}_",
        "",
        "## Sintesi",
        "",
        (narrative or "").strip() or _fallback_summary(ordered, failed),
        "",
        "## Tabella comparativa",
        "",
        "| # | Nome | Esperienza | Fit | Voto | Giudizio |",
        "|---|------|------------|-----|------|----------|",
    ]
    for pos, cand in enumerate(ordered, start=1):
        score = cand.get("score")
        lines.append(
            f"| {pos} | {_md_cell(cand.get('name'))} | "
            f"{_md_cell(_shorten(cand.get('esperienza'), 40))} | "
            f"{_md_cell(_shorten(cand.get('fit'), 40))} | "
            f"{score if score is not None else '—'} | {_md_cell(cand.get('giudizio'))} |"
        )

    lines += ["", "## Top 3", ""]
    top = ordered[:3]
    if top:
        for pos, cand in enumerate(top, start=1):
            score = cand.get("score")
            score_txt = f"{score}/100" if score is not None else "voto non assegnato"
            giudizio = cand.get("giudizio") or "—"
            lines.append(
                f"{pos}. **{_flatten(cand.get('name')) or '—'}** — {score_txt} · {giudizio}"
            )
            motivo = _flatten(cand.get("motivazione")) or _flatten(cand.get("red_flags"))
            if motivo:
                lines.append(f"   {motivo}")
            lines.append("")
    else:
        lines += ["_Nessun candidato._", ""]

    lines += ["## Da scartare", ""]
    rejected = [c for c in ordered if c.get("giudizio") == "No"]
    if rejected:
        for cand in rejected:
            motivo = (
                _flatten(cand.get("motivazione"))
                or _flatten(cand.get("red_flags"))
                or "—"
            )
            lines.append(f"- **{_flatten(cand.get('name')) or '—'}** — {motivo}")
    else:
        lines.append("_Nessun candidato scartato._")
    lines.append("")

    missing = [c for c in ordered if c.get("score") is None]
    if missing:
        lines += ["## Note", ""]
        for cand in missing:
            lines.append(
                f"- **{_flatten(cand.get('name')) or '—'}**: voto non assegnato nel report."
            )
        lines.append("")

    if failed:
        lines += ["## CV non analizzati", ""]
        lines += [f"- {_flatten(name)}" for name in failed]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_classifica(
    profile: str,
    candidates: list[dict],
    failed: list[str],
    report_dir: Path,
    narrative: str | None = None,
) -> None:
    _atomic_write(
        report_dir / "classifica.md",
        _build_classifica(profile, candidates, failed, narrative),
    )


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

    red_flags = _field(content, "Rischi/red flags") or _field(content, "Red flags")
    return {
        "name": nome,
        "file": name,
        "score": score,
        "giudizio": _normalize_giudizio(giudizio_raw),
        "esperienza": _field(content, "Esperienza totale"),
        "fit": _field(content, "Fit tecnico"),
        "red_flags": [red_flags] if red_flags else [],
        "motivazione": _field(content, "Motivazione"),
    }


def _candidate_from_json(json_path: Path, md_name: str) -> dict | None:
    """Costruisce il dict candidato da un sidecar JSON, se valido.

    `file` è derivato dal nome del report .md (non dal JSON), così le chiavi
    shortlist/tracking restano coerenti con i file. Ritorna None se il JSON non
    è leggibile, non è un oggetto, o non ha né score né giudizio (in quel caso
    il chiamante ricade sul parsing del markdown).
    """
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    score = data.get("score")
    if isinstance(score, str):
        m = re.search(r"\d+", score)
        score = int(m.group(0)) if m else None
    elif not isinstance(score, int):
        score = None
    giudizio = _normalize_giudizio(data.get("giudizio"))
    if score is None and not giudizio:
        return None
    name = data.get("name") or _nome_from_filename(md_name)
    return {
        "name": str(name).strip(),
        "file": md_name,
        "score": score,
        "giudizio": giudizio,
        "esperienza": data.get("esperienza"),
        "fit": data.get("fit"),
        "email": data.get("email"),
        "telefono": data.get("telefono"),
        "skills": data.get("skills") or [],
        "red_flags": data.get("red_flags") or [],
        "motivazione": data.get("motivazione"),
    }


def get_candidates_summary(session_id: str | None = None) -> list[dict]:
    """Candidati della sessione (o legacy) in _report/ (salvo classifica.md).

    Preferisce il sidecar JSON strutturato scritto dall'agente accanto al .md;
    se assente o non valido, ricade sul parsing del markdown (report legacy).
    """
    report_dir = _report_dir_for(session_id)
    if not report_dir.is_dir():
        return []
    out = []
    for p in sorted(report_dir.glob("*.md")):
        if "classifica" in p.name.lower():
            continue
        json_path = p.with_suffix(".json")
        if json_path.is_file():
            cand = _candidate_from_json(json_path, p.name)
            if cand:
                out.append(cand)
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


def _remove_session_reports(session_id: str, keep_keys: set[str]) -> int:
    """Elimina report e stato shortlist dei candidati non più nella posizione."""
    report_dir = _report_dir_for(session_id)
    if not report_dir.is_dir():
        return 0
    removed: set[str] = set()
    for path in report_dir.glob("*.md"):
        if "classifica" in path.name.lower():
            continue
        key = _candidate_key(path.name)
        if key in keep_keys:
            continue
        try:
            path.unlink()
            path.with_suffix(".json").unlink(missing_ok=True)
            removed.add(key)
        except OSError:
            pass
    if not removed:
        return 0
    with _lock:
        entries = _shortlist.get(session_id, {})
        for filename in list(entries):
            if _candidate_key(filename) in removed:
                entries.pop(filename, None)
        _save_shortlist()
    return len(removed)


def update_session(
    session_id: str,
    name: str | None = None,
    profile: str | None = None,
    cvs: list[str] | None = None,
) -> dict | None:
    """Aggiorna nome, profilo e CV di una posizione esistente.

    Se `cvs` è indicato, i report dei candidati rimossi vengono eliminati
    insieme al loro stato in shortlist. Ritorna None se la posizione non esiste.
    """
    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            return None
        if any(
            job.get("session_id") == session_id and job.get("status") == "running"
            for job in _jobs.values()
        ):
            raise ValueError("Screening in corso: fermalo prima di modificare la posizione")
        new_name = session.get("name", session_id)
        if name is not None:
            new_name = name.strip()
            if not new_name:
                raise ValueError("Inserisci il nome della posizione")
        new_profile = session.get("profile", "")
        if profile is not None:
            new_profile = profile.strip()
            if not new_profile:
                raise ValueError("Inserisci il profilo target")
        new_cvs: list[str] | None = None
        if cvs is not None:
            DEFAULT_CV_DIR.mkdir(parents=True, exist_ok=True)
            new_cvs = _dedupe_cv_names(_resolve_cv_names(cvs, DEFAULT_CV_DIR))
            if not new_cvs:
                raise ValueError("Seleziona almeno un CV per la posizione")
        session["name"] = new_name
        session["profile"] = new_profile
        if new_cvs is not None:
            session["cvs"] = new_cvs
        session["updated_at"] = _now_iso()
        _save_sessions()
        updated = dict(session)
    if new_cvs is not None:
        removed = _remove_session_reports(
            session_id, {_candidate_key(cv) for cv in new_cvs}
        )
        if removed:
            _write_classifica(
                updated.get("profile", ""),
                get_candidates_summary(session_id),
                [],
                _report_dir_for(session_id),
            )
    return updated


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


_VALID_MODES = {"all", "new", "failed"}


def _list_cv_files(folder: Path) -> list[str]:
    """Nomi dei CV supportati presenti nella cartella."""
    return sorted(
        p.name
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in (".pdf", ".txt", ".docx")
    )


def _candidate_key(name: str) -> str:
    """Chiave stabile del candidato, indipendente dal timestamp Indeed e dal prefisso report."""
    if re.match(r"^\d+\s*[-–]\s*", Path(name).stem):
        name = _nome_from_filename(name)
    return _cv_prefix(_safe_report_stem(name))


def _dedupe_cv_names(cv_names: list[str]) -> list[str]:
    """Un solo CV per candidato: a parità di chiave preferisce il file con nome più recente."""
    by_key: dict[str, str] = {}
    order: list[str] = []
    for cv in cv_names:
        key = _candidate_key(cv)
        if key not in by_key:
            order.append(key)
            by_key[key] = cv
        elif cv > by_key[key]:
            by_key[key] = cv
    return [by_key[key] for key in order]


def _existing_report_keys(report_dir: Path) -> set[str]:
    """Chiavi candidate che hanno già un report (esclusa classifica.md)."""
    if not report_dir.is_dir():
        return set()
    keys: set[str] = set()
    for path in report_dir.glob("*.md"):
        if "classifica" in path.name.lower():
            continue
        keys.add(_candidate_key(path.name))
    return keys


def _latest_cv_outcomes(session_id: str | None) -> dict[str, str]:
    """Ultimo esito noto per candidato nei job della sessione."""
    with _lock:
        jobs = [
            job for job in _jobs.values()
            if job.get("session_id") == session_id
        ]
        jobs.sort(key=lambda job: job.get("started") or "")
        outcomes: dict[str, str] = {}
        for job in jobs:
            for cand in job.get("candidates", []):
                cv = cand.get("cv")
                status = cand.get("status")
                if cv and status:
                    outcomes[_candidate_key(cv)] = status
    return outcomes


def _filter_cvs_by_mode(
    cv_names: list[str], session_id: str | None, mode: str
) -> list[str]:
    """Seleziona i CV da analizzare in base alla modalità richiesta."""
    if mode == "all":
        return cv_names
    report_keys = _existing_report_keys(_report_dir_for(session_id))
    outcomes = _latest_cv_outcomes(session_id) if mode == "failed" else {}
    selected: list[str] = []
    for cv in cv_names:
        key = _candidate_key(cv)
        if mode == "new":
            if key in report_keys:
                continue
        elif mode == "failed":
            if key in report_keys and outcomes.get(key) not in ("error", "cancelled"):
                continue
        selected.append(cv)
    return selected


def _safe_report_stem(value: str) -> str:
    """Nome file valido su Windows per il report del candidato."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", value).strip(" .")
    return (cleaned or "candidato")[:100]


def _assign_report_names(cv_names: list[str], report_dir: Path) -> dict[str, str]:
    """Assegna a ogni CV il nome del report, riusando quello esistente se c'è.

    I nuovi candidati prendono il primo numero libero dopo i report presenti,
    così uno screening incrementale non sovrascrive report di altri candidati.
    """
    existing: dict[str, str] = {}
    used_numbers: set[int] = set()
    if report_dir.is_dir():
        for path in report_dir.glob("*.md"):
            if "classifica" in path.name.lower():
                continue
            match = re.match(r"^(\d+)", path.stem)
            if match:
                used_numbers.add(int(match.group(1)))
            existing.setdefault(_candidate_key(path.name), path.name)
    next_number = max(used_numbers, default=0) + 1
    names: dict[str, str] = {}
    for cv in cv_names:
        key = _candidate_key(cv)
        if key in existing:
            names[cv] = existing[key]
            continue
        while next_number in used_numbers:
            next_number += 1
        report_name = f"{next_number:02d}-{_safe_report_stem(_candidate_name(cv))}.md"
        used_numbers.add(next_number)
        existing[key] = report_name
        names[cv] = report_name
        next_number += 1
    return names


def start_job(
    profile: str,
    cv_dir: Path | None = None,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
    mode: str = "all",
) -> dict:
    folder = Path(cv_dir) if cv_dir else DEFAULT_CV_DIR
    folder.mkdir(parents=True, exist_ok=True)
    mode = (mode or "all").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError("Modalità non valida: usa 'all', 'new' o 'failed'")
    if cv_names:
        cv_names = _resolve_cv_names(cv_names, folder)
        if not cv_names:
            raise FileNotFoundError("Nessun CV valido nella selezione (tutti i file sono stati rimossi)")
    elif mode != "all":
        cv_names = _list_cv_files(folder)
    if cv_names:
        cv_names = _dedupe_cv_names(cv_names)
        cv_names = _filter_cvs_by_mode(cv_names, session_id, mode)
        if not cv_names:
            if mode == "new":
                raise ValueError("Nessun CV nuovo da analizzare: tutti hanno già un report.")
            if mode == "failed":
                raise ValueError("Nessun CV da riprendere: nessuna analisi fallita o mancante.")
            raise FileNotFoundError("Nessun CV valido nella selezione")
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "profile": profile,
            "cv_dir": str(folder),
            "session_id": session_id,
            "mode": mode,
            "cvs": list(cv_names) if cv_names else [],
            "output": [],
            "error": None,
            "reports": [],
            "candidates": [],
            "started": _now_iso(),
            "finished": None,
            "duration_seconds": None,
        }
        job = _jobs[job_id]
        _save_jobs()
    threading.Thread(
        target=_run,
        args=(job_id, profile, folder, session_id, cv_names, mode),
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
        try:
            job["duration_seconds"] = round(
                (
                    datetime.fromisoformat(job["finished"])
                    - datetime.fromisoformat(job["started"])
                ).total_seconds(),
                1,
            )
        except (ValueError, TypeError):
            job["duration_seconds"] = None
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


def _run_qwen_once(
    job_id: str, prompt: str, timeout: int, capture: bool = False
) -> tuple[bool, str | None, str | None]:
    """Lancia una singola sessione qwen headless e streama l'output nel job.

    Con `capture=True` ritorna anche il testo finale prodotto da qwen.
    """
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
    with _lock:
        if job_id not in _procs:
            _procs[job_id] = []
        _procs[job_id].append(proc)
    captured: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip("\n")
            if capture:
                captured.append(text)
            with _lock:
                if _jobs.get(job_id):
                    job = _jobs[job_id]
                    job["output"].append(text)
                    if len(job["output"]) > _MAX_OUTPUT_LINES:
                        job["output"] = job["output"][-_MAX_OUTPUT_LINES:]
        proc.wait(timeout=timeout)
        if proc.returncode == 0:
            return True, None, ("\n".join(captured).strip() if capture else None)
        return False, f"qwen uscito con codice {proc.returncode}", None
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False, f"Timeout: qwen non ha terminato entro {timeout // 60} min", None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), None
    finally:
        with _lock:
            if job_id in _procs and proc in _procs[job_id]:
                _procs[job_id].remove(proc)
            if job_id in _procs and not _procs[job_id]:
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
        ok, error, _ = _run_qwen_once(job_id, prompt, timeout)
        if ok:
            return True, None
    return False, error


def _run_single_cv(
    job_id: str,
    profile: str,
    cv_dir: Path,
    report_dir: Path,
    cv: str,
    idx: int,
    total: int,
    report_name: str,
    instructions: str,
) -> tuple[bool, str]:
    if _is_cancelled(job_id):
        return False, "annullato"
    started_ts = time.time()
    with _lock:
        if _jobs.get(job_id):
            _jobs[job_id]["output"].append(f"\n[{idx}/{total}] {cv} — avvio analisi…\n")
            if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
    json_name = Path(report_name).with_suffix(".json").name
    task = (
        f"Analizza il CV: {cv_dir / cv}\n"
        f"Profilo target: '{profile}'.\n\n"
        f"Esegui la procedura completa di screening per questo singolo CV e scrivi il report "
        f"nel file: {report_dir / report_name}\n"
        f"Scrivi ANCHE il sidecar JSON strutturato nel file: {report_dir / json_name} "
        f"(schema esatto nelle tue istruzioni).\n"
        f"Non scrivere altri file: niente classifica.md, niente altre cartelle."
    )
    prompt = f"{instructions}\n\n{task}" if instructions else task
    ok, err = _run_qwen_with_retry(job_id, prompt, attempts=2, timeout=3600)
    if _is_cancelled(job_id):
        _record_candidate_timing(job_id, cv, None, started_ts, "cancelled", "annullato")
        return False, "annullato"
    if ok:
        finished_ts = time.time()
        _record_candidate_timing(job_id, cv, report_name, started_ts, "done")
        _write_report_timing(report_dir / report_name, started_ts, finished_ts)
        with _lock:
            if _jobs.get(job_id):
                _jobs[job_id]["output"].append(f"[{idx}/{total}] {cv} — report scritto ({report_name})\n")
                if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                    _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
        return True, report_name
    else:
        _record_candidate_timing(job_id, cv, None, started_ts, "error", err or "errore sconosciuto")
        with _lock:
            if _jobs.get(job_id):
                _jobs[job_id]["output"].append(f"[{idx}/{total}] {cv} — ERRORE: {err}\n")
                if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                    _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
        return False, err or "errore sconosciuto"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_narrative(text: str) -> str | None:
    """Estrae il paragrafo utile dallo stdout del CLI, scartando log e ANSI."""
    text = _ANSI_RE.sub("", text)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    for block in reversed(blocks):
        if block.startswith((">", "[", "●", "✓", "✗")):
            continue
        if len(block) >= 40:
            return re.sub(r"\s+", " ", block)[:2000]
    return None


def _generate_classifica_narrative(
    job_id: str, profile: str, candidates: list[dict]
) -> str | None:
    """Chiede al modello solo un paragrafo di sintesi; None se non disponibile.

    La classifica è già completa e deterministica: questa chiamata è opzionale
    e un suo fallimento non compromette il job.
    """
    if not candidates or _is_cancelled(job_id):
        return None
    compact = [
        {
            "nome": c.get("name"),
            "voto": c.get("score"),
            "giudizio": c.get("giudizio"),
            "esperienza": c.get("esperienza"),
            "fit": c.get("fit"),
            "motivazione": c.get("motivazione"),
            "red_flags": c.get("red_flags"),
        }
        for c in _sorted_candidates(candidates)
    ]
    prompt = (
        "Scrivi in italiano una sintesi discorsiva dei risultati dello screening "
        "(massimo 120 parole, un solo paragrafo). Non usare tabelle, elenchi o titoli. "
        "Cita i candidati migliori e quelli da scartare senza inventare dati.\n"
        f"Profilo target: {_flatten(profile)}\n"
        f"Dati: {json.dumps(compact, ensure_ascii=False)}"
    )
    try:
        ok, err, text = _run_qwen_once(job_id, prompt, timeout=300, capture=True)
    except Exception as exc:  # noqa: BLE001
        ok, err, text = False, str(exc), None
    if ok and text:
        narrative = _clean_narrative(text)
        if narrative:
            return narrative
    with _lock:
        job = _jobs.get(job_id)
    if job:
        _append_output(
            job,
            f"[classifica] sintesi LLM non disponibile ({err or 'output vuoto'}), "
            "uso il riepilogo automatico\n",
        )
    return None


def _run(
    job_id: str,
    profile: str,
    cv_dir: Path,
    session_id: str | None = None,
    cv_names: list[str] | None = None,
    mode: str = "all",
) -> None:
    """Screening parallelo: più sessioni qwen contemporanee per CV, poi classifica finale."""
    report_dir = _report_dir_for(session_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    if not cv_names:
        cv_names = _list_cv_files(cv_dir)
    cv_names = _dedupe_cv_names(cv_names)
    if not cv_names:
        _finish(job_id, "error", "Nessun CV trovato nella cartella")
        return
    instructions = _recruiter_instructions()
    total = len(cv_names)
    report_names = _assign_report_names(cv_names, report_dir)
    failed: list[str] = []
    max_workers = min(3, total)
    mode_label = {"new": "solo nuovi", "failed": "solo falliti/non completati"}.get(mode)
    with _lock:
        if _jobs.get(job_id):
            if mode_label:
                _jobs[job_id]["output"].append(f"\nModalità: {mode_label} — {total} CV da analizzare.\n")
            _jobs[job_id]["output"].append(f"\nAvvio screening parallelo ({max_workers} worker)...\n")
            if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_single_cv,
                job_id, profile, cv_dir, report_dir, cv, idx, total,
                report_names[cv], instructions,
            ): cv
            for idx, cv in enumerate(cv_names, start=1)
        }
        for fut in as_completed(futures):
            if _is_cancelled(job_id):
                executor.shutdown(wait=False, cancel_futures=True)
                return
            cv = futures[fut]
            try:
                ok, res = fut.result()
                if not ok and res != "annullato":
                    failed.append(cv)
            except Exception as exc:
                failed.append(cv)
                with _lock:
                    if _jobs.get(job_id):
                        _jobs[job_id]["output"].append(f"Errore inatteso su {cv}: {exc}\n")
                        if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                            _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
    if _is_cancelled(job_id):
        return
    with _lock:
        if _jobs.get(job_id):
            _jobs[job_id]["output"].append(f"\n[{total + 1}/{total + 1}] Generazione classifica.md…\n")
            if len(_jobs[job_id]["output"]) > _MAX_OUTPUT_LINES:
                _jobs[job_id]["output"] = _jobs[job_id]["output"][-_MAX_OUTPUT_LINES:]
    candidates = get_candidates_summary(session_id)
    if not candidates:
        _write_classifica(profile, [], failed, report_dir)
        _finish(job_id, "error", "Nessun report generato")
        return
    narrative = _generate_classifica_narrative(job_id, profile, candidates)
    if _is_cancelled(job_id):
        return
    _write_classifica(profile, candidates, failed, report_dir, narrative)
    if not (report_dir / "classifica.md").is_file():
        _finish(job_id, "error", "Classifica non generata")
        return
    _finish(job_id, "done")
    _write_classifica_timing(job_id, report_dir)


def cancel_job(job_id: str) -> bool:
    """Uccide i processi qwen del job e lo marca come 'cancelled'."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["status"] != "running":
            return False
        procs = list(_procs.get(job_id, []))
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        except Exception:
            pass
    with _lock:
        _procs.pop(job_id, None)
    _finish(job_id, "cancelled", "Job annullato dall'utente")
    return True