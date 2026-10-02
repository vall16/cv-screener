"""Avvia il downloader Indeed applicando a runtime le patch necessarie su Windows.

Non modifica il downloader ne i pacchetti della sua venv: la correzione vale
solo per questa esecuzione. Serve per due problemi noti di
chromedriver-autoinstaller 0.6.2:

- get_chrome_version scandisce solo "C:\\Program Files\\..." e lascia che
  os.scandir sollevi FileNotFoundError su installazioni Chrome 32-bit in
  "C:\\Program Files (x86)\\..." (WinError 3), rendendo irraggiungibile il
  fallback che il pacchetto stesso dichiara nei commenti.
- la ricerca del chromedriver non conosce le versioni Chrome piu recenti: viene
  lasciata fallire in silenzio, e il driver lo risolve Selenium Manager, che
  selenium 4.16 porta con se.
"""
import os
import platform
import re
import runpy
import sys
from pathlib import Path

DEFAULT_SCRIPT = Path.home() / "indeedBulkResumesDownloader" / "indeed_downloader.py"

CHROME_DIRS = (
    r"C:\Program Files\Google\Chrome\Application",
    r"C:\Program Files (x86)\Google\Chrome\Application",
)


def _chrome_version_from_disk() -> str:
    """Versione di Chrome piu alta trovata fra le cartelle di installazione note."""
    for folder in CHROME_DIRS:
        try:
            with os.scandir(folder) as entries:
                found = [e.name for e in entries if e.is_dir() and re.match(r"^[0-9.]+$", e.name)]
        except OSError:
            continue
        if found:
            return max(found)
    return ""


def patch_chromedriver_autoinstaller() -> None:
    """Rende tollerante chromedriver_autoinstaller.utils.get_chrome_version."""
    try:
        from chromedriver_autoinstaller import utils
    except ImportError:
        return

    original = utils.get_chrome_version

    def get_chrome_version() -> str:
        try:
            return original()
        except OSError:
            if platform.system() != "Windows":
                return ""
            return _chrome_version_from_disk()

    utils.get_chrome_version = get_chrome_version


def main() -> None:
    script = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_SCRIPT
    if not script.is_file():
        raise SystemExit(f"Downloader non trovato: {script}")
    patch_chromedriver_autoinstaller()
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()