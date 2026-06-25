# Remediation roadmap — issue #104 (audit) e #105

Tracking della chiusura **tecnica e completa** dei finding dell'audit. Regole: **una PR per
voce/cluster**, merge manuale del proprietario, poi si procede alla PR successiva. La issue
#104 resta **aperta** finché TUTTI i punti non sono chiusi. Poi si legge #105 e si ripete.

Legenda stato: ⬜ da fare · 🔧 in PR aperta · ✅ mergiato.

## Issue #104 — audit hard

### 🔴 Critici (rischio doppia/errata scommessa)
| ID | Finding | File | PR | Stato |
|----|---------|------|----|-------|
| A1 | SelectionName inventata nel fallback legacy (`"Over 0.5 Goals"`/`home`) | `csv_writer.py` | #107 | ✅ |
| A2 | Boundary del lock: `live_guard.evaluate` fuori da `_queue_lock` | `live_guard.py`, `app.py` | #111 | ✅ |
| A4 | Freshness fail-OPEN su timestamp mancante | `message_freshness.py` | #113 | ✅ |
| A3 | Timing scadenza coda su `time.monotonic()` (coda in-memory). `signal_dedupe` resta wallclock (PERSISTITO tra riavvii) e `message_freshness` resta wallclock (epoch assoluto Telegram) — carve-out dell'audit | `signal_queue.py`, `app.py` | #114 | ✅ |

### 🟠 HIGH
| ID | Finding | File | PR | Stato |
|----|---------|------|----|-------|
| B1 | CSV formula/control-char injection (no `'`-prefix) | `csv_writer.py` | #115 | ✅ |
| B2 | Quota HT/FT/Prematch decisa sull'intera riga (marker adiacente al numero) | `parser.py` | #116 | ✅ |
| B3 | Alias duplicato: ultimo vince in silenzio (legacy + percorso live, Codex P1) | `mapping.py`, `value_maps.py`, `dizionario.py` | #117 | ✅ |

### 🟡 MEDIUM
| ID | Finding | File | PR | Stato |
|----|---------|------|----|-------|
| C1 | Event loop mai chiuso + thread mai joinato su STOP/close | `app.py` | #118 | ✅ |
| C2 | STOP fire-and-forget con `except: pass` | `app.py` | #118 | ✅ |
| C3 | `init_csv`/clear può sollevare se XTrader tiene il lock (budget retry ~0.3s→~1s) | `csv_writer.py`, `app.py` | #119 | ✅ |
| C4 | `load_dizionario` senza validazione header (colonna rinominata → fail silenzioso/crash) | `dizionario.py` | #120 | ✅ |
| C5 | `load_config` senza migrazione/schema (tipi noti coerciti via `_migrate`) | `config_store.py` | #121 | ✅ |
| C6 | `should_reconnect` classifica per nome classe sull'MRO (ora `isinstance` sui tipi reali di `telegram.error`, fallback per nome) | `reconnect_policy.py` | #122 | ✅ |
| C7 | `save_config` ritorna shallow-copy con nested condivisi (ora `deepcopy`) | `config_store.py` | #121 | ✅ |
| C8 | Keyword conferma/notif-chat lette da snapshot mentre routing è live (ora config viva: `is_notification_chat` + keyword via `route_cfg`; `csv_path` resta di sessione) | `app.py`, `signal_router.py` | `fix/audit-104-c8` | 🔧 |

### 🟢 LOW / NIT — cluster in un'unica PR `fix/audit-104-low`
| ID | Finding | Fix | Stato |
|----|---------|-----|-------|
| L1 | `name_mapping_store` non normalizza i nomi-profilo con whitespace | `_norm_profile_name`+`_find_store_key` (come `market_mapping_store`) | 🔧 |
| L2 | `_safe_filename` accetta nomi device riservati Windows (`con`,`nul`) | mangling `_WIN_RESERVED` in `custom_parser` e `profile_store` | 🔧 |
| L3 | `migrate_legacy_config` usa `copyfile` non atomico | copia atomica tmp+fsync+`os.replace` | 🔧 |
| L4 | Regex decimali duplicata in 3+ moduli (drift) | frammento unico `numbers_re` (`DECIMAL`/`SIGNED_DECIMAL`) | 🔧 |
| L5 | `bet_type` con classe di caratteri accentati ristretta | tokenizzazione per lettere Unicode `[^\W\d_]` | 🔧 |
| L6 | `--ignore=tests/{e2e,slow,manual}` su dir inesistenti + marker inutilizzati | chiarito: marker auto-applicati per cartella (`conftest`); `--ignore` = difensivi forward-looking (documentati) | 🔧 |
| L7 | `cache-dependency-path` su `requirements-dev.txt` non invalida su bump | glob `requirements*.txt`+`requirements*.in` in tutti i workflow | 🔧 |
| L8 | Commento `# v1` vago su `action-gh-release` | commento esplicito sul pin SHA↔tag | 🔧 |

### Raggruppamento PR previsto (rivedibile)
1. **A1** (selezione non inventata) — *questa PR*
2. **A2** (lock boundary)
3. **A3+A4** (timing monotonic + freshness fail-closed)
4. **B1** (CSV injection)
5. **B2** (quota HT/FT adiacenza)
6. **B3** (alias duplicato)
7. **C1+C2** (teardown lifecycle + STOP logging)
8. **C3** (retry clear)
9. **C4** (header dizionario)
10. **C5+C7** (config migrazione + deepcopy)
11. **C6** (reconnect isinstance)
12. **C8** (keyword live-reload)
13. **LOW/NIT** (cluster)

## Issue #105 — audit Codex (CTO/hedge-fund, read-only)

L'audit #105 è stato scritto **prima** della remediation #104: alcune voci sono **già
risolte** da #104. Il resto è in gran parte **raccomandazioni architetturali/UX/security**
(non bug concreti). Triage: ✅ già fatto · 🔧 fix concreto in PR · ⬜ da fare ·
🧑‍⚖️ NEEDS_MANUAL (decisione del proprietario: refactor ampio / feature UX / scelta security).

> **Stato finale #105.** Tutti i **fix concreti** sono mergiati (#126–#131; la notif-chat era
> già coperta da #104 C8) con suite verde e `ruff` pulito a ogni PR. I **NEEDS_MANUAL** sotto
> sono stati **rimandati dal proprietario** (scelta esplicita): restano come roadmap futura, da
> affrontare singolarmente su richiesta. (Il merge resta manuale del proprietario, come per
> tutto il repo — vedi `CLAUDE.md`.)

### Fix concreti (safe, mirati — una PR per voce)
| ID | Finding | Esito |
|----|---------|-------|
| #105-P1 notif-chat live drift | chat-notifiche/keyword lette da snapshot mentre routing è live | ✅ **già risolto da #104 C8** (#123 live-reload + #124 fail-closed sul conflitto) |
| #105-P2 daily fsync | `_save_guard_state` salva il daily state senza `flush`/`fsync` (perdita conteggio in crash) | ✅ #126 (`safety_guard.save_state/load_state` atomici+fsync) |
| #105-P2 SignalTracker validation | `SignalTracker.register()` non valida `now`/`dedupe_window`/`max_per_minute` come `DailyLimiter` | ✅ #127 (`_require_positive_int`/`_require_finite_now` in `signal_dedupe`) |
| #105-P2 confirm CSV retry | mancava il test: conferma → `write_rows` fallisce → coda già svuotata → retry riscrive → niente riscrittura dopo STOP | ✅ #128 (test in `test_confirmation_flow.py`; comportamento già corretto) |
| #105-P2 clear_stale diagnostica | `clear_stale_csv` strict-header senza warning su mismatch | ✅ #129 (`logging.warning` con soli metadati strutturali, no contenuto — Codex P2) |
| #105-P2 backup_corrupted logging | `_backup_corrupted()` silenzia `OSError` (niente diagnosi) | ✅ #130 (`logging.warning` con path+errore) |
| #105-P1 token storage | `bot_token` non più in chiaro: salvato nel **keyring** di sistema | ✅ risolto (vedi sotto, sezione lavorazione #136 — `token_store` + `config_store`; fallback documentato in README "Dove sta il Bot Token") |
| #105-P2 P.Bet hardcoded (doc) | documentare che il parser P.Bet è solo compat/test, non live | 🔧 README: nota "non attivo nel live" + chiarito `active_parser=""` (questa PR) |

### NEEDS_MANUAL — decisione del proprietario (non auto-patchabili in sicurezza)
| ID | Finding | Perché manuale |
|----|---------|----------------|
| #105-P1 `app.py` monolite | refactor runtime in moduli (`session`/`telegram_listener`/`signal_executor`/…) | refactor ampio multi-sprint, alto rischio di regressioni — richiede scope/approvazione |
| #105-P2 dry-run real-mode UX | doppia conferma, banner rosso, evento `REAL_MODE_ENABLED`, armed-until-close | feature GUI/UX |
| #105-P2 multi-signal UX | warning modale, max active signals, indicatore righe attive | feature GUI/UX |

> **Lavorazione issue #136 (chiusura "sul serio" dei NEEDS_MANUAL, una PR alla volta).**
> I punti sopra vengono affrontati singolarmente. Già fatto:
> - **#105-P1 token storage sicuro** ✅ — nuovo modulo `xtrader_bridge/token_store.py`
>   (wrapper `keyring`: Windows Credential Manager / macOS Keychain / Secret Service).
>   `config_store.save_config` salva il `bot_token` nel keyring e lascia la chiave **vuota**
>   sul disco; `load_config` lo re-inietta in memoria per il runtime. Un sentinel esplicito
>   `bot_token_storage` (`keyring`/`plaintext`/`none`) disambigua lo stato così un delete
>   fallito o un disco interrotto non fanno **risorgere** un token cancellato; il keyring è
>   aggiornato **dopo** la scrittura su disco e un save parziale (senza la chiave) non lo
>   tocca (hardening Codex/CodeRabbit). **Fallback** esplicito al token in chiaro (con avviso)
>   se non c'è un backend. Dipendenza `keyring>=24.0` in `requirements.in` (+`bot_token_storage`
>   tra le `SECRET_KEYS` dei profili). Test: `tests/unit/test_token_store.py`, `test_config_basic.py`.
>   **Nota manuale:** aggiungendo una dipendenza runtime, il `requirements-build.lock` va
>   **rigenerato su Windows** (workflow *Generate Windows Lockfile*) prima della build EXE.
> - **#105-P1 privacy mode dei log** ✅ — flag `debug_message_payload` (default OFF =
>   privacy on) in `config_store`; modulo puro `xtrader_bridge/log_privacy.py`
>   (`redact_message`: hash sha256 + lunghezza + prima riga troncata; payload completo
>   solo con opt-in esplicito). Agganciato ai due log del runtime in `app.py` (`IN (chat …)`
>   e `🧾 Messaggio→CSV`) + toggle GUI nella tab *Sicurezza* + `settings_controller`.
>   Test: `tests/unit/test_log_privacy.py`, `test_settings_controller.py`, `test_config_basic.py`.
> - **#105-P3 atomic helper unico** ✅ — centralizzato in `xtrader_bridge/atomic_io.py`
>   (`atomic_write` + `atomic_write_text`/`atomic_write_json`): `mkstemp` nella stessa
>   cartella → `flush`/`fsync` → `os.replace` (cleanup su errore, `replace` iniettabile per
>   il retry su lock Windows). Vi delegano `config_store`, `csv_writer`, `safety_guard`,
>   `signal_dedupe`, `custom_parser`, `profile_store`, `parser_io` (niente più 7 copie a
>   rischio drift). Test: `tests/safety/test_atomic_io.py`.
> - **#105-P3 / #133 item 6 — validatori condivisi** ✅ — nuovo modulo
>   `xtrader_bridge/validators.py`: `require_positive_int`/`require_finite_now` (erano
>   duplicati in `safety_guard` e `signal_dedupe`) e il nucleo `safe_filename_core` +
>   `WIN_RESERVED` (condiviso da `custom_parser` e `profile_store`, che mantengono il
>   PROPRIO fallback: `"parser"` vs `""`). Test: `tests/unit/test_validators.py`.

I P3 restanti sono **giudizi positivi** (validazione prezzi/BetType, recognition mode,
difesa CSV/chat) — nessuna azione.
