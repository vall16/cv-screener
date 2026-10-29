#!/usr/bin/env bash
#
# setup-qwen-config.sh — crea la config di Qwen Code per l'utente dedicato
# del servizio cv-screener e riavvia il servizio.
#
# Uso (sul server, come root):
#   sudo bash /home/wvallone/cv-screener/setup-qwen-config.sh
#
# Se il modello su llama.cpp ha un nome diverso, cambia MODEL_ID (e, se serve,
# LLM_BASE_URL) prima di lanciare.
#
set -euo pipefail

# ---------------- Configurazione ----------------
SERVICE_USER="cvscreener"
SERVICE="cv-screener"
CONFIG_DIR="/home/${SERVICE_USER}/.qwen"
CONFIG_FILE="${CONFIG_DIR}/settings.json"
MODEL_ID="qwen3.8-27b"
LLM_BASE_URL="http://127.0.0.1:11434/v1"

# ---------------- Esecuzione ----------------
mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_FILE" <<EOF
{
  "modelProviders": {
    "openai": [
      {
        "id": "${MODEL_ID}",
        "name": "Modello screening (llama.cpp)",
        "envKey": "LOCAL_LLM_API_KEY",
        "localBaseUrl": "${LLM_BASE_URL}",
        "baseUrl": "${LLM_BASE_URL}",
        "capabilities": { "vision": true, "agent": true },
        "generationConfig": {
          "timeout": 600000,
          "streamIdleTimeoutMs": 600000,
          "maxRetries": 1,
          "contextWindowSize": 131072,
          "samplingParams": { "temperature": 0.2, "max_tokens": 8192 }
        }
      }
    ]
  },
  "env": { "LOCAL_LLM_API_KEY": "not-needed" },
  "security": { "auth": { "selectedType": "openai" } },
  "model": { "name": "${MODEL_ID}" }
}
EOF

chown -R "${SERVICE_USER}:${SERVICE_USER}" "$CONFIG_DIR"
echo "Config scritta in ${CONFIG_FILE} (modello: ${MODEL_ID}, endpoint: ${LLM_BASE_URL})"

systemctl restart "$SERVICE"
echo "Servizio ${SERVICE} riavviato."
echo "Verifica: systemctl status ${SERVICE}"
