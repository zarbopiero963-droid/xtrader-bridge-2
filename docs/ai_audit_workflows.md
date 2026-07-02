# Workflow AI di review e audit (GitHub Actions)

Quattro workflow GitHub Actions usano modelli AI esterni (OpenAI e Anthropic)
come **filtro tecnico aggiuntivo** — mai come sostituto del controllo umano.
Nessuno di loro modifica codice, committa, pusha, apre PR, approva o merge:
**il merge resta sempre manuale del proprietario**.

| Workflow | File | Trigger | Modello | Output |
| --- | --- | --- | --- | --- |
| GPT-5.5 Secure PR Review | `.github/workflows/openai-gpt-pr-review.yml` | automatico su ogni PR (opened/synchronize/reopened/ready_for_review) | `gpt-5.5` (Responses API, `store: false`) | un commento sulla PR (aggiornato in place) |
| Claude Fable 5 Secure PR Review | `.github/workflows/claude-fable-pr-review.yml` | automatico su ogni PR (stessi eventi) | `claude-fable-5` (Messages API) | un commento sulla PR (aggiornato in place) |
| Manual Full Repository AI Audit | `.github/workflows/manual-full-repo-ai-audit.yml` | **solo manuale** (Actions → Run workflow) | `gpt-5.5` | artifact `full-repo-ai-audit-<run>` (Markdown + JSON) |
| Claude Fable 5 Manual Full Repo Audit | `.github/workflows/claude-fable-full-repo-audit.yml` | **solo manuale** (Actions → Run workflow) | `claude-fable-5` | artifact `claude-fable-full-repo-audit-<run>` (Markdown + JSON) |

## Secrets richiesti

Da creare in *Settings → Secrets and variables → Actions → Secrets*:

- `OPENAI_API_KEY` — per i due workflow OpenAI;
- `ANTHROPIC_API_KEY` — per i due workflow Claude.

Se il secret manca, il workflow fallisce subito con un errore chiaro (nessuna
chiamata parziale). Le chiavi sono mascherate nei log (`::add-mask::`) e non
vengono mai stampate.

## Postura di sicurezza (invarianti difese da `tests/safety/test_ai_audit_workflows.py`)

- **Permessi minimi**: tutti hanno `contents: read`; i PR review aggiungono solo
  `pull-requests: read` + `issues: write` (per pubblicare il commento). Nessun
  workflow ha `contents: write`, `pull-requests: write` o `actions: write`.
- **Niente `pull_request_target`**, niente PR draft, niente PR da fork esterni
  (guard `if:` sul job).
- **PR review diff-only**: il patch viene letto dalla GitHub API — **nessun
  checkout e nessuna esecuzione del codice della PR**.
- **Audit read-only**: snapshot tarball del repo, nessun checkout scrivibile;
  producono solo un artifact scaricabile. I **symlink non vengono mai seguiti**
  (un link committato non può far leggere file del runner fuori dallo
  snapshot) e i finding del modello sono **clampati al file/chunk realmente
  analizzato**.
- **Redaction pre-invio**: possibili segreti (token Telegram, chiavi API,
  private key, assegnazioni `password=`/`token=` ecc.) vengono offuscati
  **prima** di inviare qualsiasi contenuto ai modelli — inclusi i **nomi
  file/path**, che possono anch'essi contenere un segreto. Gli audit fanno
  anche un secret-scan locale che finisce nel report come finding
  `critical`/`high`.
- **Prompt-injection hardening**: i prompt dichiarano il contenuto dei
  file/diff come non attendibile (il modello non deve seguire istruzioni
  scritte nel codice in analisi).
- **OpenAI `store: false`**: le richieste alla Responses API chiedono di non
  memorizzare la response.
- **Actions pinnate a SHA** (convenzione hardening del repo; `upload-artifact`
  è pinnata allo stesso SHA v4.6.2 di `build.yaml`).
- **Budget duri** su file, chunk, caratteri e token di output per limitare i
  costi (Fable 5 costa più di Sonnet; GPT-5.5 su repo interi costa in fretta).
- **Script inline per design**: il Python vive negli heredoc dei workflow, non
  in moduli del repo, perché i PR review non fanno checkout e gli audit devono
  eseguire solo codice versionato **col workflow** (non codice preso dallo
  snapshot del ref scansionato, che è input non attendibile). La duplicazione
  tra le varianti GPT/Claude è il prezzo accettato di questo isolamento; le
  invarianti comuni sono difese in un punto solo dal test di safety.

## PR review automatici — cosa fanno

Su ogni PR non-draft interna al repo:

1. leggono l'elenco file + patch dalla GitHub API (con budget per file e
   totale; i file saltati sono elencati nel commento);
2. redigono i possibili segreti dal diff;
3. chiedono al modello una review in italiano con sezioni fisse (Esito,
   Bloccanti, Rischi da controllo manuale, Sicurezza e segreti, Windows,
   CSV/Telegram/Parser, Test consigliati, Miglioramenti opzionali);
4. pubblicano/aggiornano **un solo commento** per workflow (marker HTML
   nascosto: niente spam di commenti a ogni push);
5. se la PR tocca **aree sensibili** (workflow, requirements, telegram, csv,
   parser, config, secret, betfair, licenze, updater, …) aggiungono l'avviso
   **«⚠️ RICHIEDE CONTROLLO MANUALE»** e provano ad applicare la label
   `manual-review-required` (se la label non esiste nel repo il workflow non
   fallisce: logga un warning).

Nota: i due review girano in parallelo e sono indipendenti; puoi disattivarne
uno rimuovendo il file o il secret corrispondente.

## Audit full-repo manuali — come si lanciano

*GitHub → Actions → nome del workflow → Run workflow*, scegliendo branch e
input. Solo i file **testuali** vengono analizzati (riga per riga, con numeri
riga); binari, cache, `dist/`, `node_modules/`, virtualenv e file oltre il
limite di dimensione vengono saltati e **tracciati in `skipped-files.json`** —
nessun troncamento silenzioso.

Input principali (entrambi gli audit): `target_ref` (vuoto = la branch scelta),
`audit_depth` (`standard`/`deep`/`paranoid`), `max_files`, `max_chunks`,
`max_file_kb`, `chunk_max_chars`, `fail_on_critical` (fallisce il job se
trova finding critical — utile come gate di release). Il workflow Claude ha
anche `max_output_tokens_per_chunk`.

Valori consigliati:

- **GPT-5.5, run normale**: `deep`, `max_files=800`, `max_chunks=180`,
  `max_file_kb=512`, `chunk_max_chars=18000`;
- **GPT-5.5, scansione aggressiva**: `paranoid`, `max_files=3000`,
  `max_chunks=700`, `max_file_kb=1024`;
- **Claude Fable 5, run normale (default prudenti per i costi)**: `standard`,
  `max_files=500`, `max_chunks=45`, `max_file_kb=300`, `chunk_max_chars=9000`,
  `max_output_tokens_per_chunk=800`;
- **Claude Fable 5, release importante**: `deep`, `max_files=1200`,
  `max_chunks=120`, `max_file_kb=500`, `chunk_max_chars=12000`,
  `max_output_tokens_per_chunk=1000`.

L'artifact (retention 14 giorni) contiene: report Markdown con sintesi AI e
findings ordinati per severità, `*findings.json` (metadati + findings
deduplicati), `scanned-files.txt`, `skipped-files.json`, `errors.txt` ed
eventuali errori di parse grezzi (redatti).

## Cosa questi workflow NON fanno (per design)

- non fanno checkout del codice delle PR e non lo eseguono;
- non modificano file, non committano, non pushano;
- non aprono PR e non rispondono a comandi tipo «@bot fix it»;
- non approvano review e non abilitano auto-merge;
- non sostituiscono i gate esistenti (commit-gate, pr-checks,
  forbidden-files, merge-simulation): si aggiungono come filtro consultivo.

## Test

`tests/safety/test_ai_audit_workflows.py` verifica offline le invarianti di
sicurezza (permessi, trigger, no-checkout, secrets dai GitHub Secrets,
`store: false`, pin a SHA), compila il Python embedded negli heredoc ed
esercita le funzioni reali degli script di audit (redaction, chunking con
numeri riga, secret-scan locale, normalizzazione/dedupe dei findings, skip di
binari e directory generate). Il comportamento live (commento su PR reale,
run di audit reale con API key) non è testabile offline: si verifica alla
prima esecuzione reale.
