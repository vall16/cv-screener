# Deploy su server

## 1. Trasferimento

Da Windows (locale):
```bat
cd C:\Users\vallo\cv-screener
git archive -o C:\Users\vallo\cv-screener.zip HEAD
```
Trasferisci `cv-screener.zip` via WinSCP sul server.

## 2. Setup sul server

```bash
# Estrai
cd /var/www
unzip cv-screener.zip
mv * cv-screener/   # se non hai già la cartella padre

# Backend
cd /var/www/cv-screener/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd /var/www/cv-screener/frontend
npm install
npm run build

# Avvio
cd /var/www/cv-screener/backend
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

## 3. Avvio permanente (systemd)

Crea `/etc/systemd/system/cv-screener.service`:

```ini
[Unit]
Description=CV Screener
After=network.target

[Service]
WorkingDirectory=/var/www/cv-screener/backend
ExecStart=/var/www/cv-screener/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable cv-screener
systemctl start cv-screener
```

## 4. Note

- Il server deve avere: Python 3.11+, Node.js 20+, npm
- `opencode` deve essere installato nel PATH del server (per lo screening AI)
- I CV si caricano via web UI (nessun Indeed download dal server: serve Chrome locale)
- La cartella `CVs/` e `CVs/_report/` vengono create automaticamente
