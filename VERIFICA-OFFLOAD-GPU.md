# Verifica offload GPU del modello di screening

Come capire se Qwen sta girando (tutto o in parte) sulla GPU o sulla CPU.
Ciò che conta non è il `contextWindowSize` nel `settings.json` di Qwen Code (è
solo lato client), ma con **quali flag è stato avviato il server** (`-ngl`, `-c`)
e cosa stampa all'avvio. La porta `11434` è quella di default di **Ollama**,
quindi prima bisogna capire cosa gira davvero.

## 0. Che cosa ascolta sulla 11434 (sul server)

```bash
ss -ltnp | grep 11434          # oppure: lsof -i :11434
ps aux | grep -Ei 'llama|ollama'
```

Dal PID si vedono anche i flag di avvio:

```bash
ps -o args= -p <PID>
```

- Se compare `llama-server ... -ngl 0` → **gira su CPU**, ecco la lentezza.
- Se compare `-ngl 999` (o un valore >= numero di layer) → punta al full GPU.
- Se il processo è `ollama` → è Ollama, non llama.cpp (vedi punto B).

## A. Se è llama.cpp (`llama-server`)

**Log di avvio** — cercare queste righe:

```bash
# se è un servizio systemd
journalctl -u llama-server -b --no-pager | grep -Ei 'offload|CUDA|buffer|KV|load_tensors|device'

# se è stato lanciato a mano / con nohup
grep -Ei 'offload|CUDA|buffer|KV' /percorso/llama.log   # o nohup.out
```

Le righe che contano:

```
load_tensors: offloaded 65/65 layers to GPU     ← 65/65 = TUTTO su GPU (bene)
load_tensors: offloaded 40/65 layers to GPU     ← parziale (male)
CUDA0 model buffer size = 15000.00 MiB
KV self size = 8192.00 MiB                       ← il contesto 128K gonfia questo
using device CUDA0 (NVIDIA ...)
```

Se non c'è `--log-file`, rilanciare con `--log-file /tmp/llama.log` e riavviare.

## B. Se è Ollama (probabile, porta 11434)

Il comando più diretto:

```bash
ollama ps
```

Colonna `PROCESSOR`:

```
NAME            SIZE     PROCESSOR          UNTIL
qwen...:27b     18 GB    100% GPU           4 minutes from now   ← ok
qwen...:27b     18 GB    70% GPU/30% CPU     4 minutes from now   ← lento
qwen...:27b     18 GB    100% CPU            ...                  ← lentissimo
```

Per i log dettagliati:

```bash
sudo systemctl edit ollama        # aggiungere: Environment="OLLAMA_DEBUG=1"
sudo systemctl restart ollama
journalctl -u ollama -b --no-pager | grep -Ei 'offload|CUDA|buffer|KV|gpu'
```

Nota: con Ollama il contesto non si imposta con `-c` ma con
`OLLAMA_CONTEXT_LENGTH` o `num_ctx` nel Modelfile. Se è a 131072, il KV cache è
enorme e può impedire il full offload.

## C. Verifica runtime (vale per entrambi)

Mentre gira lo screening, su un'altra shell:

```bash
watch -n1 nvidia-smi
# oppure
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv
```

- Il processo `llama-server`/`ollama` **deve comparire** nella lista processi con
  diversi GB di VRAM.
- Se la VRAM è quasi vuota durante lo screening → sta calcolando su CPU.
- Guardare anche `Memory-Usage`: se sfiora il 100% della VRAM, l'offload non è
  completo.

## D. Misurare la velocità vera (tok/s)

Nei log di llama.cpp, durante una richiesta:

```
prompt eval time = ... ms / ... tokens ( ... tok/s)
eval time        = ... ms / ... tokens ( ... tok/s)   ← generazione
```

- **> 20 tok/s** → GPU ok, il problema è il prompt/agent (round-trip, vision,
  thinking).
- **< 10 tok/s** → offload incompleto o CPU.

Se Ollama: `OLLAMA_DEBUG=1` e cercare `tokens per second` nel journal.

## In sintesi

1. `ss -ltnp | grep 11434` → scoprire se è `llama-server` o `ollama`.
2. `ollama ps` (se Ollama) o `journalctl -u llama-server | grep offload`
   (se llama.cpp).
3. `nvidia-smi` durante lo screening per confermare che il processo sia sulla GPU.
4. Controllare i flag di avvio (`ps -o args= -p PID`): `-ngl` deve essere pieno e
   `-c`/`num_ctx` basso.
