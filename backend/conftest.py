"""Assicura che la cartella backend/ sia sul sys.path per `import screener`."""
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parent)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
