#!/usr/bin/env bash
#
# deploy.sh — deploy automatico di cv-screener su server Linux (/home/wvallone)
# Esegue i passi 3-4 di DEPLOY.md: setup (backend + frontend) e avvio via systemd.
#
# Uso (sul server, come root):
#   1) Trasferisci cv-screener.zip in /home/wvallone (WinSCP / scp)
#   2) cd /home/wvallone && unzip cv-screener.zip
#   3) bash /home/wvallone/cv-screener/deploy.sh
#
set -euo pipefail

# ---------------- Configurazione ----------------
APP_DIR="/home/wvallone/cv-screener"
ZIP="/home/wvallone/cv-screener.zip"
PORT=8000
SERVICE="cv-screener"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"

# ---------------- Helper ----------------
log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*"; exit 1; }

# ---------------- 0. Precondizioni ----------------
log "Controllo prerequisiti"
command -v python3 >/dev/null 2>&1 || die "python3 non trovato (serve Python 3.11+)"
command -v node    >/dev/null 2>&1 || die "node non trovato (serve Node.js 20+)"
command -v npm     >/dev/null 2>&1 || die "npm non trovato"
command -v unzip   >/dev/null 2>&1 || die "unzip non trovato (apt install unzip)"

# ---------------- 1. Estrazione ----------------
if [ ! -d "$APP_DIR" ]; then
  [ -f "$ZIP" ] || die "Né $APP_DIR né $ZIP esistono. Trasferisci prima cv-screener.zip in /home/wvallone."
  log "Estrazione di $ZIP in /home/wvallone"
  cd /home/wvallone
  unzip -o "$ZIP" -d "$APP_DIR"
else
  log "Cartella $APP_DIR già presente (salto l'estrazione)"
fi

# ---------------- 2. Backend ----------------
log "Setup backend (venv + dipendenze)"
cd "$APP_DIR/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# ---------------- 3. Frontend ----------------
log "Build frontend (npm install + build)"
cd "$APP_DIR/frontend"
npm install
npm run build

# ---------------- 4. Servizio systemd ----------------
log "Creazione servizio systemd: $SERVICE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CV Screener
After=network.target

[Service]
WorkingDirectory=${APP_DIR}/backend
ExecStart=${APP_DIR}/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT}
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# ---------------- 5. Stato ----------------
sleep 2
systemctl --no-pager status "$SERVICE" || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "Deploy completato"
echo "  URL locale: http://127.0.0.1:${PORT}"
[ -n "${IP:-}" ] && echo "  URL server: http://${IP}:${PORT}"
echo "  Log: journalctl -u ${SERVICE} -f"
