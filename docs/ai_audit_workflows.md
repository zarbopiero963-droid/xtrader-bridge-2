# Workflow AI di review e audit (GitHub Actions)

Sei workflow GitHub Actions usano modelli AI esterni come **filtro tecnico
aggiuntivo** — mai come sostituto del controllo umano. Nessuno modifica codice,
committa, pusha, apre PR, approva o merge: **il merge resta sempre manuale del
proprietario**.

| Workflow | File | Trigger | Modello | Output |
| --- | --- | --- | --- | --- |
| PR Review GPT-5.5 | `.github/workflows/pr-review-gpt55.yml` | automatico su ogni push della PR | `gpt-5.5` (OpenAI Responses API, `store: false`) | un commento per range |
| PR Review Claude Fable 5 | `.github/workflows/pr-review-claude-fable5.yml` | automatico su ogni push della PR | `claude-fable-5` (Anthropic Messages API) | un commento per range |
| PR Review GLM 5.2 | `.github/workflows/pr-review-openrouter-glm52.yml` | automatico su ogni push della PR | `z-ai/glm-5.2` (OpenRouter) | un commento per range |
| PR Review Fugu Ultra | `.github/workflows/pr-review-openrouter-fugu-ultra.yml` | automatico su ogni push della PR | `sakana/fugu-ultra` (OpenRouter) | un commento per range |
| Manual Full Repo Audit (GPT) | `.github/workflows/manual-full-repo-ai-audit.yml` | **solo manuale** (Actions → Run workflow) | `gpt-5.5` | artifact Markdown + JSON |
| Manual Full Repo Audit (Claude) | `.github/workflows/claude-fable-full-repo-audit.yml` | **solo manuale** (Actions → Run workflow) | `claude-fable-5` | artifact Markdown + JSON |

I quattro modelli hanno ruoli complementari: **GLM 5.2** reviewer economico per
feedback continuo, **GPT-5.5** reviewer bilanciato su bug/test/regressioni,
**Claude Fable 5** reviewer profondo su edge case e problemi complessi, **Fugu
Ultra** reviewer avanzato su concorrenza/sicurezza per PR critiche.

## Secrets richiesti

Da creare in *Settings → Secrets and variables → Actions → Secrets*:

- `OPENAI_API_KEY` — PR review GPT-5.5 + audit GPT;
- `ANTHROPIC_API_KEY` — PR review Claude Fable 5 + audit Claude;
- `OPENROUTER_API_KEY` — PR review GLM 5.2 + Fugu Ultra.

I **PR review sono reviewer opzionali**: se il secret corrispondente non è
configurato il job esce con **successo** (skip, con una nota nei log), **non**
fa fallire la PR con un check rosso. Puoi quindi abilitare solo i modelli che
vuoi creando solo i relativi secret. Le chiavi sono mascherate nei log
(`::add-mask::`) e non vengono mai stampate.

## Novità: review sul range del push (non sul diff cumulativo)

I quattro PR review analizzano **solo i commit del push corrente**, non l'intero
diff della PR a ogni commit. Su un evento `pull_request` `synchronize` usano il
range `before...after` del push via l'endpoint GitHub **Compare** (`GET
/repos/{owner}/{repo}/compare/{base}...{head}`, che restituisce file cambiati e
patch). Se Claude pusha 3 commit insieme, i reviewer analizzano quei 3 commit;
se ne pusha 1, solo quello — senza rileggere tutta la PR ogni volta e senza
perdere commit intermedi. Su `opened`/`reopened`/`ready_for_review` (dove non
c'è un push precedente) usano il range dell'intera PR; se il `before` manca o il
compare fallisce, fanno **fallback** al parent singolo dell'HEAD. Ogni commento
mostra scope, range `base...head`, numero di commit e una stima del costo token.

## Postura di sicurezza (invarianti difese da `tests/safety/test_ai_audit_workflows.py`)

- **Permessi minimi**: tutti hanno `contents: read`; i PR review aggiungono solo
  `pull-requests: read` + `issues: write`. Nessuno ha `contents: write`,
  `pull-requests: write` o `actions: write`.
- **Niente `pull_request_target`**, niente PR draft, niente PR da fork esterni.
- **PR review diff-only**: il diff viene letto dalla GitHub API — **nessun
  checkout e nessuna esecuzione del codice della PR**.
- **Reviewer opzionali fail-open sul check**: key assente → `exit 0` (skip),
  mai un check rosso.
- **Audit read-only**: snapshot tarball, nessun checkout scrivibile; solo un
  artifact. I **symlink non vengono mai seguiti** (un link committato non può
  far leggere file del runner fuori dallo snapshot) e i finding del modello sono
  **clampati al file/chunk realmente analizzato**.
- **Redaction pre-invio**: possibili segreti (token Telegram, chiavi
  OpenAI/OpenRouter, PAT GitHub classici **e fine-grained `github_pat_`**,
  private key, assegnazioni `password=`/`token=`) vengono offuscati **prima**
  dell'invio — inclusi **nomi file/path** e il **ref**, che possono contenere un
  segreto e da cui vengono rimossi anche i control-char (niente iniezione di
  campi nei prompt). Gli audit fanno anche un secret-scan locale che finisce nel
  report come finding `critical`/`high`.
- **Prompt-injection hardening**: i prompt dichiarano diff/file come non
  attendibili.
- **OpenAI `store: false`**: le richieste alla Responses API non memorizzano.
- **Audit fail-closed**: se sono stati tentati chunk ma **nessuno** è andato a
  buon fine (API giù, key invalida), l'audit **fallisce** invece di sembrare
  verde; le righe singole oltre budget vengono troncate e la redaction del PEM
  preserva i numeri riga.
- **Action pinnate a SHA**: solo gli audit usano `uses:` (`upload-artifact`
  pinnata allo stesso SHA v4.6.2 di `build.yaml`); i PR review non usano action.
- **Budget duri** su file, chunk, caratteri e token di output per limitare i
  costi; ogni commento riporta la stima di spesa.

## Audit full-repo manuali — come si lanciano

*GitHub → Actions → nome del workflow → Run workflow*, scegliendo branch e
input. Solo i file **testuali** vengono analizzati (riga per riga, con numeri
riga); binari, cache, `dist/`, `node_modules/`, virtualenv e file oltre il
limite di dimensione vengono saltati e **tracciati in `skipped-files.json`** —
nessun troncamento silenzioso.

Input principali (entrambi gli audit): `target_ref` (vuoto = la branch scelta;
validato fail-closed `^[A-Za-z0-9._/-]+$` e percent-encodato per il tarball),
`audit_depth` (`standard`/`deep`/`paranoid`), `max_files`, `max_chunks`,
`max_file_kb`, `chunk_max_chars`, `fail_on_critical`. Il workflow Claude ha
anche `max_output_tokens_per_chunk`.

Valori consigliati:

- **GPT-5.5, run normale**: `deep`, `max_files=800`, `max_chunks=180`,
  `max_file_kb=512`, `chunk_max_chars=18000`;
- **Claude Fable 5, run normale (default prudenti)**: `standard`,
  `max_files=500`, `max_chunks=45`, `max_file_kb=300`, `chunk_max_chars=9000`,
  `max_output_tokens_per_chunk=800`.

L'artifact (retention 14 giorni) contiene report Markdown con sintesi e findings
ordinati per severità, `*findings.json`, `scanned-files.txt`,
`skipped-files.json` ed `errors.txt`.

## Cosa questi workflow NON fanno (per design)

- non fanno checkout del codice delle PR e non lo eseguono;
- non modificano file, non committano, non pushano;
- non aprono PR e non rispondono a comandi tipo «@bot fix it»;
- non approvano review e non abilitano auto-merge;
- non sostituiscono i gate esistenti: si aggiungono come filtro consultivo.

## Test

`tests/safety/test_ai_audit_workflows.py` verifica offline le invarianti di
sicurezza (permessi, trigger, no-checkout, reviewer opzionale con `exit 0`,
push-range via Compare API, secrets dai GitHub Secrets, `store: false`, pin a
SHA, redaction del PAT fine-grained, fix incorporati nei PR review), compila il
Python embedded ed esercita le funzioni reali degli script di audit (redaction,
`safe_display`, redaction del ref, chunking con numeri riga e troncamento righe
lunghe, secret-scan locale, normalizzazione/dedupe dei findings, skip di
binari/dir generate/symlink, guard di fallimento se tutti i chunk AI falliscono).
Il comportamento live (commento su PR reale, run di audit con API key) non è
testabile offline: si verifica alla prima esecuzione reale.
