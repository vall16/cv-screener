"""Test delle funzioni pure di screener.py (nessun lancio di qwen).

Coprono la logica di parsing dei report, le chiavi candidati, dedupe/resolve
dei nomi CV, assegnazione nomi report, filtri per modalità e helper di formattazione.
"""
import json

import screener


# ── Nomi e chiavi candidati ──────────────────────────
def test_cv_prefix():
    assert screener._cv_prefix("Mario Rossi_20260101_120000.pdf") == "mario rossi"
    assert screener._cv_prefix("plain-name.pdf") == "plain-name"
    assert screener._cv_prefix("note.txt") == "note"


def test_nome_from_filename():
    assert screener._nome_from_filename("01-Mario Rossi.md") == "Mario Rossi"
    assert screener._nome_from_filename("Mario Rossi.pdf") == "Mario Rossi"


def test_candidate_key():
    assert screener._candidate_key("Mario Rossi_20260101_120000.pdf") == "mario rossi"
    # Il nome report con prefisso numerico risale allo stesso candidato
    assert screener._candidate_key("01-Mario Rossi.md") == "mario rossi"


def test_safe_report_stem():
    assert screener._safe_report_stem("Mario Rossi") == "Mario Rossi"
    assert screener._safe_report_stem("A/B:C") == "A-B-C"
    assert screener._safe_report_stem("   ") == "candidato"


def test_slugify():
    assert screener._slugify("Senior Backend Dev") == "senior-backend-dev"
    assert screener._slugify("  --Weird__Name--  ") == "weird-name"
    assert screener._slugify("!!!") == "posizione"


# ── Dedupe e resolve dei nomi CV ─────────────────────
def test_dedupe_cv_names():
    # Stesso candidato con due timestamp: resta quello più recente (nome maggiore)
    out = screener._dedupe_cv_names([
        "Mario Rossi_20250101_000000.pdf",
        "Mario Rossi_20260101_000000.pdf",
        "Luca Bianchi_20260101_000000.pdf",
    ])
    assert out == ["Mario Rossi_20260101_000000.pdf", "Luca Bianchi_20260101_000000.pdf"]


def test_resolve_cv_names(tmp_path):
    (tmp_path / "Mario Rossi_20260101_120000.pdf").write_bytes(b"x")
    (tmp_path / "Luca Bianchi_20260102_120000.pdf").write_bytes(b"x")
    # Un nome con timestamp vecchio si risolve per prefisso sul file attuale
    out = screener._resolve_cv_names(
        ["Mario Rossi_20250101_000000.pdf", "Luca Bianchi_20260102_120000.pdf"],
        tmp_path,
    )
    assert out == ["Mario Rossi_20260101_120000.pdf", "Luca Bianchi_20260102_120000.pdf"]


# ── Assegnazione nomi report ─────────────────────────
def test_assign_report_names(tmp_path):
    names = screener._assign_report_names(["Mario Rossi.pdf", "Luca Bianchi.pdf"], tmp_path)
    assert names["Mario Rossi.pdf"] == "01-Mario Rossi.md"
    assert names["Luca Bianchi.pdf"] == "02-Luca Bianchi.md"


def test_assign_report_names_reuses_existing(tmp_path):
    (tmp_path / "01-Mario Rossi.md").write_text("x")
    names = screener._assign_report_names(["Mario Rossi.pdf", "Anna Verdi.pdf"], tmp_path)
    # Il candidato esistente riusa il nome; il nuovo prende il numero successivo
    assert names["Mario Rossi.pdf"] == "01-Mario Rossi.md"
    assert names["Anna Verdi.pdf"] == "02-Anna Verdi.md"


# ── Filtri per modalità ──────────────────────────────
def test_filter_mode_all():
    assert screener._filter_cvs_by_mode(["a.pdf", "b.pdf"], None, "all") == ["a.pdf", "b.pdf"]


def test_filter_mode_new(monkeypatch, tmp_path):
    monkeypatch.setattr(screener, "DEFAULT_CV_DIR", tmp_path)
    sid = "s2"
    (tmp_path / "_report" / sid).mkdir(parents=True)
    (tmp_path / "_report" / sid / "01-A.md").write_text("x")
    # A ha già un report -> scartato; B è nuovo -> selezionato
    assert screener._filter_cvs_by_mode(["A.pdf", "B.pdf"], sid, "new") == ["B.pdf"]


def test_filter_mode_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(screener, "DEFAULT_CV_DIR", tmp_path)
    sid = "s1"
    report_dir = tmp_path / "_report" / sid
    report_dir.mkdir(parents=True)
    (report_dir / "01-A.md").write_text("x")
    (report_dir / "02-C.md").write_text("x")
    monkeypatch.setattr(screener, "_jobs", {
        "j1": {
            "session_id": sid,
            "started": "2026-01-01T00:00:00+00:00",
            "candidates": [
                {"cv": "A.pdf", "status": "done"},
                {"cv": "C.pdf", "status": "error"},
            ],
        }
    })
    # A: report + esito done -> scartato. B: nessun report -> selezionato.
    # C: report + esito error -> selezionato (ripresa)
    assert screener._filter_cvs_by_mode(["A.pdf", "B.pdf", "C.pdf"], sid, "failed") == ["B.pdf", "C.pdf"]


# ── Parsing dei report ───────────────────────────────
def test_field():
    content = (
        "Voto complessivo: 85/100\n"
        "Giudizio: Sì passa\n"
        "Esperienza totale: 10 anni: backend\n"
    )
    assert screener._field(content, "Voto complessivo") == "85/100"
    assert screener._field(content, "Giudizio") == "Sì passa"
    # I ':' dentro il valore non rompono l'estrazione
    assert screener._field(content, "Esperienza totale") == "10 anni: backend"
    assert screener._field(content, "Assente") is None


def test_normalize_giudizio():
    assert screener._normalize_giudizio("Sì passa") == "Sì passa"
    assert screener._normalize_giudizio("passa") == "Sì passa"
    assert screener._normalize_giudizio("Da valutare") == "Da valutare"
    assert screener._normalize_giudizio("no") == "No"
    assert screener._normalize_giudizio(None) is None
    assert screener._normalize_giudizio("") is None


def test_parse_candidate():
    content = (
        "# Valutazione: Mario Rossi — Backend\n"
        "Voto complessivo: 82/100\n"
        "Giudizio: Sì passa\n"
        "Esperienza totale: 8 anni\n"
        "Fit tecnico: alto\n"
        "Motivazione: buon match\n"
        "Rischi/red flags: gap di 6 mesi\n"
    )
    c = screener.parse_candidate("01-Mario Rossi.md", content)
    assert c is not None
    assert c["name"] == "Mario Rossi"
    assert c["score"] == 82
    assert c["giudizio"] == "Sì passa"
    assert c["esperienza"] == "8 anni"
    assert c["fit"] == "alto"
    assert c["motivazione"] == "buon match"
    assert c["red_flags"] == ["gap di 6 mesi"]


def test_parse_candidate_none():
    assert screener.parse_candidate("x.md", "testo senza campi strutturati") is None


def test_candidate_from_json(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps({
        "name": "Mario Rossi", "score": 88, "giudizio": "Sì passa",
        "esperienza": "9 anni", "fit": "alto", "email": "m@x.it",
        "skills": ["python"], "red_flags": [], "motivazione": "ok",
    }), encoding="utf-8")
    c = screener._candidate_from_json(p, "01-Mario Rossi.md")
    assert c is not None
    assert c["file"] == "01-Mario Rossi.md"
    assert c["score"] == 88
    assert c["email"] == "m@x.it"
    assert c["skills"] == ["python"]


def test_candidate_from_json_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert screener._candidate_from_json(bad, "x.md") is None
    # Nessun score e nessun giudizio -> None (ricade sul parsing markdown)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"name": "X"}), encoding="utf-8")
    assert screener._candidate_from_json(empty, "x.md") is None


# ── Classifica e ordinamento ─────────────────────────
def test_sorted_candidates():
    cands = [
        {"name": "A", "score": 50},
        {"name": "B", "score": None},
        {"name": "C", "score": 90},
    ]
    out = screener._sorted_candidates(cands)
    assert [c["name"] for c in out] == ["C", "A", "B"]


def test_build_classifica():
    candidates = [
        {"name": "Mario", "score": 90, "giudizio": "Sì passa",
         "esperienza": "8 anni", "fit": "alto", "motivazione": "ok"},
        {"name": "Luca", "score": 40, "giudizio": "No",
         "esperienza": "2 anni", "fit": "basso", "motivazione": "no"},
    ]
    md = screener._build_classifica("Backend", candidates, [])
    assert "# Classifica — Backend" in md
    assert "## Tabella comparativa" in md
    assert "## Da scartare" in md
    # Ordinati per voto decrescente: Mario prima di Luca
    assert md.index("Mario") < md.index("Luca")


# ── Helper di formattazione ──────────────────────────
def test_fmt_duration():
    assert screener._fmt_duration(None) == "—"
    assert screener._fmt_duration(45) == "45 s"
    assert screener._fmt_duration(125) == "2 min 5 s"
    assert screener._fmt_duration(3661) == "1 h 1 min 1 s"


def test_flatten_shorten_mdcell():
    assert screener._flatten(None) == ""
    assert screener._flatten(["a", "b"]) == "a, b"
    assert screener._flatten("  multi \n line ") == "multi line"
    assert screener._shorten("abcdefghij", 5) == "abcd…"
    assert screener._md_cell("a|b") == "a\\|b"
    assert screener._md_cell(None) == "—"
