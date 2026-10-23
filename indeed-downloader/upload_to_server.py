"""Carica i CV scaricati da Indeed sul server CV Screener della LAN.

Uso:
    python upload_to_server.py http://192.168.1.10:8000

Senza argomento chiede l'URL a video. I PDF vengono presi da downloads/.
"""
import sys
from pathlib import Path

import requests

BATCH_SIZE = 10
MAX_MB = 15
ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = ROOT / "downloads"


def _normalize(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url
    return url


def main() -> int:
    base = _normalize(sys.argv[1] if len(sys.argv) > 1 else "")
    while not base:
        base = _normalize(input("URL del server CV Screener (es. http://192.168.1.10:8000): "))

    pdfs = sorted(p for p in DOWNLOAD_DIR.rglob("*.pdf") if p.is_file()) if DOWNLOAD_DIR.is_dir() else []
    if not pdfs:
        print("Nessun PDF trovato in downloads/. Esegui prima AVVIA-DOWNLOADER.cmd.")
        return 1

    print(f"Server: {base}")
    print(f"PDF trovati: {len(pdfs)}")

    try:
        health = requests.get(f"{base}/api/health", timeout=10)
        health.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"Server non raggiungibile: {exc}")
        print("Controlla l'URL e che la web UI di CV Screener sia aperta.")
        return 1

    uploaded = 0
    errors = 0
    for start in range(0, len(pdfs), BATCH_SIZE):
        batch = pdfs[start:start + BATCH_SIZE]
        files = []
        for path in batch:
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_MB:
                print(f"  salto {path.name}: {size_mb:.1f} MB (oltre {MAX_MB} MB)")
                errors += 1
                continue
            files.append(("files", (path.name, path.read_bytes(), "application/pdf")))
        if not files:
            continue
        try:
            resp = requests.post(f"{base}/api/cvs/upload", files=files, timeout=180)
        except Exception as exc:  # noqa: BLE001
            print(f"  errore di rete: {exc}")
            errors += len(batch)
            continue
        if resp.status_code >= 400:
            print(f"  errore HTTP {resp.status_code}: {resp.text[:300]}")
            errors += len(batch)
            continue
        data = resp.json()
        uploaded += len(data.get("saved", []))
        errors += len(data.get("errors", []))
        for message in data.get("errors", []):
            print(f"  scartato: {message}")
        done = min(start + BATCH_SIZE, len(pdfs))
        print(f"  {done}/{len(pdfs)}")

    print()
    print(f"Fatto: {uploaded} CV caricati, {errors} errori.")
    if uploaded:
        print("Ora apri la web UI di CV Screener: i CV sono pronti per lo screening.")
    return 0 if uploaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
