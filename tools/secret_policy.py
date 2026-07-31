#!/usr/bin/env python3
"""**Fonte unica** della policy anti-segreto — PR-D del piano #194 (B3, B14, B30, B31).

Perché esiste. Fino alla #194 le difese anti-segreto erano **tre liste separate**:

- `.gitignore` — quali file git non deve nemmeno vedere;
- `.github/workflows/forbidden-files.yml` — quali file non devono risultare tracciati, con una
  **copia** dei pattern scritta in `grep -E` dentro il YAML;
- `tools/secret_scan.py` — quali *contenuti* sono segreti.

Un file nuovo andava aggiunto a mano a tutte e tre, e il backup completo del License Manager
(che contiene il **seed Ed25519**, la chiave che firma tutte le licenze) non era in nessuna:
passava tutte e tre le difese indisturbato (B3). La separazione aveva già **prodotto una
divergenza misurabile**: il workflow cercava un bot-id Telegram `[0-9]{8,10}`, lo scanner
`[0-9]{8,12}` — cioè il gate CI non intercettava i bot-id lunghi che l'hook pre-commit
intercettava. Due copie corrette oggi sono due copie divergenti domani (Regola 3 di `CLAUDE.md`).

Da qui in avanti i pattern vivono **solo qui**:

- `tools/secret_scan.py` importa `SECRET_PATTERNS` (contenuti);
- `tools/forbidden_paths.py` importa le regole sui percorsi, e il workflow lo invoca invece di
  riscrivere le `grep`;
- `.gitignore` non può importare Python, quindi non è una copia ma un **mirror verificato**:
  `GITIGNORE_DEVE_COPRIRE` elenca ciò che deve risultare ignorato, e un test hard lo controlla
  con `git check-ignore` (`tests/safety/test_presidi_antisegreto_194.py`). Se qualcuno aggiunge
  un file qui e dimentica `.gitignore`, il test diventa rosso.
"""

import re

# ── Contenuti segreti ────────────────────────────────────────────────────────────────────────
# Pattern ad ALTO segnale, scelti per ~zero falsi positivi (verificati a 0 match sul repo).
# Su BYTES (come `grep -E`): nessun problema di encoding e niente decodifica del segreto.
# chat-id e path utente NON sono qui: come stringhe sono comuni nei doc/test (falsi positivi)
# e sono già coperti dal blocco per percorso di `forbidden_paths`.
SECRET_PATTERNS = [
    # AC-B37 audit #114: allargato il bot-id a `{8,12}` (prima `{8,10}`) per intercettare i
    # bot-id più lunghi dei bot Telegram recenti. La parte auth resta `{35}` (formato REALE del
    # token): NON allargata a `{30,}` come il redactor dei workflow (volutamente lasco per la
    # sola redazione), così il GATE non blocca falsi positivi — le fixture di test usano 32-34
    # char, sotto i 35 reali. NESSUN `\b`, né iniziale né finale (review Fable/GLM #131),
    # INTENZIONALMENTE come il pattern STORICO (`[0-9]{8,10}:…{35}`, che non ne aveva): il match
    # su substring intercetta anche un token EMBEDDED in una stringa più lunga (il `\b` finale su
    # `{35}` lo mancherebbe; quello iniziale mancherebbe un token preceduto da altre cifre). Per
    # un GATE la copertura più ampia è preferibile; la forma resta molto specifica
    # (`<8-12 cifre>:<35 char>`) → nessun falso positivo su sequenze numeriche nude (repo: 0 FP).
    ("Telegram bot token", re.compile(rb"[0-9]{8,12}:[A-Za-z0-9_-]{35}")),
    ("PEM private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # AKIA = chiave permanente; ASIA = credenziale TEMPORANEA STS (entrambe sono AWS access
    # key id valide e vanno intercettate — review CodeRabbit).
    ("AWS access key id", re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    # AC-M14 audit #114: le chiavi che il repo maneggia DAVVERO (Anthropic/OpenAI/OpenRouter,
    # GitHub token/PAT) erano redatte nei diff di review ma NON bloccate al commit dal gate.
    # `sk-…` copre OpenAI (`sk-`/`sk-proj-`), Anthropic (`sk-ant-…`) e OpenRouter (`sk-or-v1-…`).
    # `\b` INIZIALE mantenuto (evita match dentro parole tipo `disk-`/`task-`/`mask-`+20char =
    # falsi positivi); `\b` FINALE RIMOSSO (review Fugu #131): una chiave reale che TERMINA con
    # `-` (la classe include `-`) seguita da `"`/newline NON produrrebbe word-boundary → falso
    # NEGATIVO (chiave non bloccata). Senza `\b` finale il match su prefisso resta valido.
    ("OpenAI/Anthropic/OpenRouter API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub fine-grained PAT", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{30,}")),
    # B31 (#186 A4 · #187 S4) — il seed Ed25519 del License Manager: 32 byte = **64 caratteri
    # esadecimali**, il segreto più prezioso del sistema (firma TUTTE le licenze, non è
    # sostituibile senza riemetterle tutte).
    #
    # Il pattern è **contestuale di proposito**, e questa è la decisione delicata dell'intera PR:
    # 64 hex di fila sono anche la forma di uno **SHA-256**, e il repository ne contiene 291
    # righe solo fra `requirements-build.lock` e `requirements-build-linux.lock` (gli hash pip),
    # più la chiave **pubblica** embedded in `xtrader_bridge/licensing/license.py`. Un
    # `[0-9a-f]{64}` nudo avrebbe fatto fallire il gate sull'intero repo al primo push —
    # un gate che grida sempre viene disattivato, e allora non protegge più niente.
    #
    # Richiedendo la parola `seed` accanto al valore si coprono le due forme REALI in cui il
    # seed finisce su disco, misurate sul codice di produzione:
    #   1. `signing_key.json`      → `"seed": "<64 hex>"`
    #   2. backup completo         → `\"seed\": \"<64 hex>\"`  (il file-chiave è annidato come
    #      stringa JSON dentro il backup, quindi le virgolette sono **escapate**: un pattern
    #      scritto sulla sola forma 1 mancherebbe esattamente il file del bug B3)
    # e anche un letterale in codice (`SEED = "<64 hex>"`), con `:` o `=`.
    #
    # ⚠️ ALLARGATO nella PR che chiude la #205. La prima versione accettava solo le virgolette
    # **doppie**: `seed = 'ab…'` con gli apici singoli **passava il gate** (misurato). Il rilievo
    # è nato su una copia diversa di questo pattern — quella dei redattori dei workflow — e la
    # Regola 2 impone di correggere la CLASSE: il buco era identico qui, dove pesa di più,
    # perché il redattore protegge un diff che sta partendo mentre questo impedisce al seed di
    # **entrare** nel repository.
    #
    # Coperte ora anche le forme di nome reali: `seed_hex` è ciò che `core.generate_keypair`
    # ritorna davvero, quindi è il nome più probabile in un incollaggio accidentale; `SEED_HEX`
    # maiuscolo è la forma delle costanti. Collaterale misurato sul repo: **3 righe**, tutte
    # fixture di test con un seed finto, marcate con `pragma: allowlist secret` (marker onorato
    # solo sotto `tests/`). `(?i)` copre le varianti maiuscole.
    ("Ed25519 signing seed",
     re.compile(rb'''(?i)\\?['"]?(?:signing[_-]?)?seed(?:[_-]?hex)?\\?['"]?\s*[:=]\s*\\?['"]?[0-9a-f]{64}''')),
]

# ── Percorsi vietati ─────────────────────────────────────────────────────────────────────────
# Rete **case-insensitive** sui file tracciati. Serve perché su Linux `.gitignore` è
# case-sensitive: `git ls-files -i` NON cattura le varianti Windows (`Config.json`, `.ENV`,
# `secret.EXE`, `signals.CSV`). Qui i basename e le estensioni critici a prescindere dalle
# maiuscole, come singola espressione (era una `grep -E` dentro il YAML).
PERCORSI_VIETATI = re.compile(
    r"(?i)"
    r"(?:^|/)\.env$"
    r"|(?:^|/)config\.json$"
    # B14 (#186 A3 · #187 S3) — gli stati del License Manager. `licenses.jsonl` e
    # `revoked.jsonl` contengono i dati dei CLIENTI (nome, contatto, hardware id): non sono
    # "segreti" per pattern, quindi lo scanner dei contenuti non li vedrebbe mai. Vanno bloccati
    # per NOME, che è l'unica cosa che li identifica.
    r"|(?:^|/)(?:licenses|revoked)\.jsonl$"
    r"|(?:^|/)(?:signing_key|auto_backup|publish_config|publish_state|"
    r"restore_in_progress|license_state)\.json$"
    # B3 — il backup completo, che contiene il seed. Il nome lo sceglie l'utente nel dialogo di
    # salvataggio, quindi si intercetta la forma `*backup*.json` invece di un nome esatto.
    r"|(?:^|/)[^/]*backup[^/]*\.json$"
    r"|\.(?:exe|zip|log|spec|secret|bak)$"
)

# CSV: ammesso SOLO il dizionario ufficiale (file dati versionato, non un CSV generato dal
# bridge). Confronto esatto sul path completo, non sul basename.
CSV_CONSENTITI = frozenset({"data/dizionario_xtrader.csv"})

# ── Mirror verificato di `.gitignore` ────────────────────────────────────────────────────────
# `.gitignore` non può importare questo modulo: è un file di git, non Python. Invece di
# lasciarlo divergere in silenzio (che è **esattamente** come è nato B14), questo elenco dice
# cosa `.gitignore` DEVE ignorare, e un test hard lo verifica con `git check-ignore`. Aggiungere
# una voce qui senza aggiornare `.gitignore` rende il test rosso.
GITIGNORE_DEVE_COPRIRE = (
    "config.json",
    ".env",
    "signing_key.json",
    "licenses.jsonl",
    "revoked.jsonl",
    "auto_backup.json",
    "publish_config.json",
    "publish_state.json",
    "restore_in_progress.json",
    "license_state.json",
    "xtrader_license_backup_2026-07-31.json",
    "backup_licenze.json",
    "segnali.csv",
)

# Controprova del mirror: ciò che NON deve MAI risultare ignorato. Una regola troppo larga in
# `.gitignore` è pericolosa quanto una mancante — ingoierebbe un file che il repo deve spedire.
GITIGNORE_NON_DEVE_COPRIRE = (
    "data/dizionario_xtrader.csv",
)
