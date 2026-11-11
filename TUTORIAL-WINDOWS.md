# CV Screener — Tutorial Windows (versione portable)

## Requisiti

- Windows 10/11 (64-bit)
- **Google Chrome** installato (necessario per il downloader CV da Indeed)
- Niente altro: Python, Node.js e tutte le dipendenze sono già incluse nello zip

## Installazione

1. Scarica `cv-screener-portable.zip`
2. Estrai lo zip in una cartella **breve** (es. `C:\cv-screener`).
   - ⚠️ Non estrarre in `C:\Program Files` (permessi insufficienti)
   - ⚠️ Non estrarre in cartelle con spazi o caratteri speciali nel nome
3. Verifica che la cartella contenga:
   ```
   cv-screener\
   ├── AVVIA-CV-SCREENER.cmd
   ├── python\
   ├── backend\
   ├── frontend\
   ├── indeed-downloader\
   └── CVs\
   ```

## Avvio

Doppio click su **`AVVIA-CV-SCREENER.cmd`**

- Il server parte su **http://127.0.0.1:8000**
- Il browser si apre automaticamente quando il server è pronto
- Per fermare: chiudi la finestra del terminale

### Se la porta 8000 è occupata

Lo script tenta di chiudere l'istanza precedente. Se non ci riesce (es. avviata come admin), chiede l'elevazione UAC. Conferma nella finestra di Windows.

## Uso

### Upload CV

- Trascina i file CV (PDF, DOCX, TXT) nella pagina principale
- Oppure usa il pulsante "Carica CV"

### Screening

- Seleziona i CV da screenare
- Clicca "Avvia screening"
- I risultati (score, motivazione, skill rilevate) compaiono nella tabella

### Download CV da Indeed

1. Nel menu a tendina "Indeed", scegli l'opzione desiderata (es. "Scarica CV da Indeed")
2. Si apre una finestra Chrome: fai login al tuo account Indeed Employer
3. I CV vengono scaricati automaticamente nella cartella `indeed-downloader\downloads\`
4. I file vengono poi caricati nel sistema

> **Nota:** per il download Indeed serve che Chrome sia installato e che tu sia loggato.
> Se Chrome è già aperto con sessioni attive, usa **`AVVIA-CV-SCREENER-ADMIN.cmd`** (richiede UAC).

### Export

- **Classifica CSV**: esporta la classifica in formato CSV (separatore `;`, compatibile Excel italiano)
- **Report PDF**: genera un report PDF per ogni CV screenato

## Cartelle

| Cartella | Contenuto |
|----------|-----------|
| `CVs\` | File CV caricati (PDF, DOCX, TXT) |
| `CVs\_report\` | Report PDF generati |
| `indeed-downloader\downloads\` | CV scaricati da Indeed |
| `indeed-downloader\logs\` | Log del downloader |
| `python\` | Runtime Python embedded (non modificare) |

## Risoluzione problemi

| Problema | Soluzione |
|----------|-----------|
| "Installazione incompleta" | Ri-estrai lo zip completo, assicurati che tutte le cartelle siano presenti |
| Porta 8000 occupata | Chiudi altre istanze di CV Screener o riavvia il PC |
| Chrome non si apre per Indeed | Verifica che Chrome sia installato; prova `AVVIA-CV-SCREENER-ADMIN.cmd` |
| Screening non parte | Verifica la connessione al server LLM (vedi configurazione) |
| Antivirus blocca lo script | Aggiungi un'eccezione per la cartella `cv-screener` |

## Configurazione (opzionale)

### Server LLM per lo screening

Lo screening usa un modello LLM locale. Il file di configurazione è in:
```
~/.qwen/settings.json
```
(oppure `%USERPROFILE%\.qwen\settings.json`)

Assicurati che il server LLM sia raggiungibile dall'IP configurato.

### Indeed (credenziali)

Le credenziali Indeed non sono necessarie: il login avviene direttamente nel browser Chrome durante il download.

## Aggiornamento

Per aggiornare a una nuova versione:
1. Chiudi CV Screener
2. Sostituisci la cartella con la nuova estrazione
3. **Conserva la cartella `CVs\`** se vuoi mantenere i CV già caricati
