# Deploy su server

Deploy di cv-screener su un server Linux (es. Ubuntu). Il servizio gira come
**utente dedicato** (`cvscreener`), non root. Lo screening AI usa **Qwen Code**
(`qwen`), non opencode.

## Prerequisiti sul server

- Python 3.11+
- Node.js 20+ e npm
- Qwen Code installato nel PATH:
  ```bash
  npm i -g @qwen-code/qwen-code
  ```
- Un modello LLM raggiungibile (es. llama.cpp / Ollama). L'endpoint si configura
  in `settings.json` (vedi passo 2).

## 1. Trasferimento

Da Windows (locale):
```bat
cd C:\Users\vallo\cv-screener
git archive -o C:\Users\vallo\cv-screener.zip HEAD
```
Trasferisci `cv-screener.zip` via WinSCP in `/home/wvallone` ed estrai, così da
avere la cartella `/home/wvallone/cv-screener/`.

## 2. Config di Qwen Code

`deploy.sh` crea l'utente `cvscreener` e la cartella `/home/cvscreener/.qwen/`.
Metti lì il file `settings.json` con il modello da usare per lo screening.

Se llama.cpp gira **sullo stesso server**, usa `localhost`:
```json
{
  "modelProviders": {
    "openai": [
      {
        "id": "qwen3.8-27b",
        "name": "Qwen3.8 su llama.cpp",
        "envKey": "LOCAL_LLM_API_KEY",
        "localBaseUrl": "http://127.0.0.1:11434/v1",
        "baseUrl": "http://127.0.0.1:11434/v1",
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
  "model": { "name": "qwen3.8-27b" }
}
```

## 3. Deploy

Sul server, come root:
```bash
sudo bash /home/wvallone/cv-screener/deploy.sh
```
Lo script esegue in automatico:
1. controllo prerequisiti (python3 / node / npm);
2. setup backend (venv + dipendenze);
3. build frontend (npm install + build);
4. crea l'utente dedicato `cvscreener`, assegna i permessi su `/home/wvallone/cv-screener`
   e prepara `/home/cvscreener/.qwen/`;
5. crea e avvia il servizio systemd `cv-screener` (porta 8000, `User=cvscreener`);
6. mostra stato e URL.

Lo script è **idempotente**: ri-lancialo per i re-deploy.

## 4. Verifica

```bash
systemctl status cv-screener
journalctl -u cv-screener -f        # log in tempo reale
```
Poi apri `http://<IP-server>:8000` dal browser.

## Note

- Il servizio gira come `cvscreener` (non root): la config di Qwen Code va in
  `/home/cvscreener/.qwen/settings.json`.
- I CV si caricano via web UI. Il download da Indeed **non** parte dal server
  (serve Chrome locale): scarica i CV sulla macchina Windows e sincronizzali.
- Le cartelle `CVs/` e `CVs/_report/` vengono create automaticamente.
