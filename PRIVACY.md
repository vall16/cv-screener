# Privacy e trattamento dei CV

## Dove vanno i dati

| Tool | CLI | Modello | I CV escono dall'ufficio? |
|------|-----|---------|--------------------------|
| Opencode (big-pickle) | Locale | Cloud (opencode) | Sì |
| Qwen Code | Locale | Cloud (Alibaba) | Sì |
| Ollama + modello locale | Locale | Locale (GPU) | **No** |

Il CLI legge i file localmente, ma il contenuto viene inviato via API al modello in cloud per l'analisi.

## Rischio GDPR

- I CV contengono **dati personali** (nome, contatti, storico lavorativo) → rientrano nel GDPR.
- Come azienda che li processa, hai obblighi: base giuridica, informativa candidati, eventuale DPA con il provider AI.
- I provider (opencode, Alibaba) hanno server **fuori UE** → trasferimento extra-UE.
- I provider seri dichiarano di **non usare i dati per training** di default, ma non c'è garanzia contrattuale senza DPA.

## Rischio in pratica

- I CV già girano su server Indeed (cloud, extra-UE) prima di arrivare qui.
- Il rischio "aggiuntivo" di passarli a un LLM è marginale rispetto al flusso Indeed.
- Per uso interno con pochi CV: rischio basso.
- Per processing su larga scala con dati sensibili: serve valutazione formale.

## Come azzerare il rischio

Usare un modello self-hosted:

```bash
# Esempio con Ollama (serve GPU ~24GB VRAM)
ollama pull qwen2.5:72b
```

Poi configurare opencode o il backend per puntare a `http://localhost:11434` invece dell'API cloud. I CV non escono mai dalla macchina.
