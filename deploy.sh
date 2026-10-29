#!/usr/bin/env bash
#
# deploy.sh — deploy automatico di cv-screener su server Linux (/home/wvallone)
# Esegue i passi di DEPLOY.md: setup (backend + frontend) e avvio via systemd.
# Il servizio gira come utente dedicato (non root).
#
# Uso (sul server, come root):
#   1) Copia la cartella cv-screener in /home/wvallone (WinSCP / scp)
#   2) sudo bash /home/wvallone/cv-screener/deploy.sh
#
set -euo pipefail

# ---------------- Configurazione ----------------
APP_DIR="/home/wvallone/cv-screener"
PORT=8000
SERVICE="cv-screener"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
SERVICE_USER="cvscreener"

# ---------------- Helper ----------------
log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*"; exit 1; }

# ---------------- 0. Precondizioni ----------------
log "Controllo prerequisiti"
command -v python3 >/dev/null 2>&1 || die "python3 non trovato (serve Python 3.11+)"
command -v node    >/dev/null 2>&1 || die "node non trovato (serve Node.js 20+)"
command -v npm     >/dev/null 2>&1 || die "npm non trovato"

# ---------------- 1. Verifica cartella app ----------------
[ -d "$APP_DIR" ] || die "Cartella $APP_DIR non trovata. Copia prima cv-screener in /home/wvallone."

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

# ---------------- 4. Utente dedicato ----------------
log "Preparo utente dedicato: $SERVICE_USER"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd -r -m -d "/home/$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
  log "Creato utente $SERVICE_USER"
fi
# L'utente deve poter attraversare la cartella padre e possedere l'app (venv, node_modules, CVs)
chmod 755 "$(dirname "$APP_DIR")"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
# Cartella config di Qwen Code per l'utente dedicato (metti qui settings.json)
mkdir -p "/home/$SERVICE_USER/.qwen"
chown "$SERVICE_USER:$SERVICE_USER" "/home/$SERVICE_USER/.qwen"
log "Config Qwen Code: /home/$SERVICE_USER/.qwen/settings.json"

# ---------------- 5. Servizio systemd ----------------
log "Creazione servizio systemd: $SERVICE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CV Screener
After=network.target

[Service]
WorkingDirectory=${APP_DIR}/backend
ExecStart=${APP_DIR}/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT}
Restart=always
User=${SERVICE_USER}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# ---------------- 6. Stato ----------------
sleep 2
systemctl --no-pager status "$SERVICE" || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "Deploy completato"
echo "  URL locale: http://127.0.0.1:${PORT}"
[ -n "${IP:-}" ] && echo "  URL server: http://${IP}:${PORT}"
echo "  Log: journalctl -u ${SERVICE} -f"
