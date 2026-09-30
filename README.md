# cv-screener

Screening di CV in stile *Cowork*: carichi i CV, scrivi il profilo target e un agente
recruiter li legge tutti e produce una **classifica motivata** — report per candidato,
tabella comparativa, top 3 e scartati con motivo.

Non è una SaaS: gira tutto in locale sulla tua macchina. Nessun dato esce dal computer,
i CV restano in una cartella e i report vengono scritti su file. prova

## Come funziona

```
frontend (Angular 20)  ──HTTP──▶  backend (FastAPI)  ──subprocess──▶  opencode run --agent hr-recruiter
   web UI @ :4200            API + job @ :8000                    legge i CV, scrive i report
```

- L'agente `hr-recruiter` è definito in `.opencode/agent/hr-recruiter.md`: lì ci sono
  ruolo, criteri di valutazione e permessi.
- Il backend non contiene logica di valutazione: si limita a lanciare `opencode run`
  in background, così puoi chiudere la pagina e tornare quando ha finito.
- L'ufficio dell'agente è il disco: legge da `CVs/` e scrive in `CVs/_report/`.

## Struttura

```
cv-screener/
├── .opencode/
│   ├── agent/hr-recruiter.md      # l'agente recruiter (ruolo, criteri, permessi)
│   └── command/screen-cvs.md      # comando /screen-cvs
├── backend/
│   ├── main.py                    # API FastAPI + hosting del frontend buildato
│   ├── screener.py                # gestione job e invocazione di opencode
│   └── requirements.txt
├── frontend/                      # Angular 20
│   └── src/app/                   # upload CV, avvio job, lista/visualizzazione report
├── CVs/                           # qui i CV da analizzare (PDF/TXT)
│   └── _report/                   # qui i report generati
├── screen-cvs.bat                 # flusso CLI senza web UI (doppio click)
└── opencode.json                  # modello di default
```

## Requisiti

- [opencode](https://opencode.ai) nel PATH (obbligatorio: è lui che legge i CV)
- Node.js 20+ e npm
- Python 3.11+

## Avvio rapido

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows (. venv/bin/activate su macOS/Linux)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm start                     # http://localhost:4200
```

Apri <http://localhost:4200>, carica i CV, scrivi il profilo target e premi invio.
I report compaiono nella sezione Report appena il job finisce.

### 3. (Opzionale) build di produzione

Se compili il frontend, il backend lo serve da solo su `http://127.0.0.1:8000`:

```bash
cd frontend
npm run build                 # output in frontend/dist/cv-screener/browser
```

## API

| Metodo | Endpoint | Descrizione |
| --- | --- | --- |
| `GET` | `/api/health` | stato del servizio |
| `GET` | `/api/cvs` | lista i CV presenti in `CVs/` |
| `POST` | `/api/cvs/upload` | upload multipla (solo PDF/TXT, max 15 MB per file) |
| `DELETE` | `/api/cvs/{name}` | rimuove un CV |
| `GET` | `/api/jobs` | lista i job |
| `POST` | `/api/jobs?profile=...` | avvia lo screening |
| `GET` | `/api/jobs/{id}` | stato e output live del job |
| `GET` | `/api/reports` | lista i report in `_report/` |
| `GET` | `/api/reports/{name}` | contenuto di un report |

## Uso senza web UI

Doppio click su `screen-cvs.bat`: ti chiede solo la cartella dei CV e il profilo target,
lancia lo screening e alla fine apre da sola la cartella `_report`.

Dal TUI di opencode:

```
/screen-cvs C:\percorso\CVs "senior backend developer"
```

Headless:

```bash
opencode run --agent hr-recruiter "Analizza i CV in /percorso/CVs per il profilo 'senior backend'. Scrivi report e classifica in _report" --auto
```

## Cosa produce l'agente

Per ogni candidato un report in `CVs/_report/N-Nome.md` con punteggio pesato:

| Criterio | Peso |
| --- | --- |
| Fit tecnico | 40% |
| Esperienza di settore | 30% |
| Soft skills / colloquio | 20% |
| Rischi e red flags | 10% |

Più `CVs/_report/classifica.md` con tabella comparativa, top-3 motivata e lista degli scartati.

## Note

- Formati supportati: **PDF e TXT**. I DOCX vanno convertiti o letti tramite MCP.
- L'agente non inventa dati: se un'informazione non è nel CV, lo scrive esplicitamente e
  cita la sezione da cui trae ogni affermazione.
- I job vivono in memoria: riavviando il backend la cronologia si azzera (i report su disco no).
- Per N posizioni diverse: lancia N job in parallelo su cartelle CV separate.
- I CV e i report sono in `.gitignore` per evitare di committare dati personali.
- Per usare l'agente in altri progetti basta copiare `.opencode/agent/hr-recruiter.md`
  in quel progetto (o in `~/.config/opencode/agent/` per averlo ovunque).
