#!/usr/bin/env bash
# Legge lo screening più recente da backend/jobs.json (status, errore, ultime righe di output).
# Funziona anche se il backend è fermo: legge il file, non l'API.
#
# Uso:
#   ./screening-log.sh            # ultime 30 righe
#   ./screening-log.sh 80         # ultime 80 righe
#   ./screening-log.sh 80 <id>    # job specifico (id da jobs.json)
set -euo pipefail

N="${1:-30}"
JOB_ID="${2:-}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOBS="$DIR/backend/jobs.json"

if [[ ! -f "$JOBS" ]]; then
  echo "jobs.json non trovato in: $JOBS" >&2
  exit 1
fi

python3 - "$JOBS" "$N" "$JOB_ID" <<'PY'
import json, sys

path, n, job_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]
jobs = json.load(open(path, encoding="utf-8"))
if not jobs:
    print("Nessun job in jobs.json")
    sys.exit(0)

if job_id:
    j = jobs.get(job_id)
    if j is None:
        print(f"Job non trovato: {job_id}")
        sys.exit(1)
else:
    j = sorted(jobs.values(), key=lambda x: x.get("started", ""), reverse=True)[0]

print("id:      ", j.get("id"))
print("profilo: ", j.get("profile"))
print("status:  ", j.get("status"))
print("error:   ", j.get("error"))
print("start:   ", j.get("started"))
print("fine:    ", j.get("finished"))
print("--- ultime %d righe dello screening ---" % n)
for line in j.get("output", [])[-n:]:
    print(line)
PY
