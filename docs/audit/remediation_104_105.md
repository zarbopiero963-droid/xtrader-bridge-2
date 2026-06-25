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

### Fix concreti (safe, mirati — una PR per voce)
| ID | Finding | Esito |
|----|---------|-------|
| #105-P1 notif-chat live drift | chat-notifiche/keyword lette da snapshot mentre routing è live | ✅ **già risolto da #104 C8** (#123 live-reload + #124 fail-closed sul conflitto) |
| #105-P2 daily fsync | `_save_guard_state` salva il daily state senza `flush`/`fsync` (perdita conteggio in crash) | ✅ #126 (`safety_guard.save_state/load_state` atomici+fsync) |
| #105-P2 SignalTracker validation | `SignalTracker.register()` non valida `now`/`dedupe_window`/`max_per_minute` come `DailyLimiter` | ✅ #127 (`_require_positive_int`/`_require_finite_now` in `signal_dedupe`) |
| #105-P2 confirm CSV retry | mancava il test: conferma → `write_rows` fallisce → coda già svuotata → retry riscrive → niente riscrittura dopo STOP | ✅ #128 (test in `test_confirmation_flow.py`; comportamento già corretto) |
| #105-P2 clear_stale diagnostica | `clear_stale_csv` strict-header senza warning su mismatch | ✅ #129 (`logging.warning` con soli metadati strutturali, no contenuto — Codex P2) |
| #105-P2 backup_corrupted logging | `_backup_corrupted()` silenzia `OSError` (niente diagnosi) | 🔧 `logging.warning` con path+errore (questa PR) |
| #105-P1 token plain JSON (short-term) | documentare che `bot_token` è in JSON plain nel profilo utente | ⬜ (doc) |
| #105-P2 P.Bet hardcoded (doc) | documentare che il parser P.Bet è solo compat/test, non live | ⬜ (doc) |

### NEEDS_MANUAL — decisione del proprietario (non auto-patchabili in sicurezza)
| ID | Finding | Perché manuale |
|----|---------|----------------|
| #105-P1 `app.py` monolite | refactor runtime in moduli (`session`/`telegram_listener`/`signal_executor`/…) | refactor ampio multi-sprint, alto rischio di regressioni — richiede scope/approvazione |
| #105-P1 token storage | DPAPI/Windows Credential Manager / keyring | scelta di sicurezza + dipendenze/piattaforma |
| #105-P1 log payload privacy | privacy mode (hash+troncamento, full solo in debug) | scelta di policy + impatto UX/diagnostica |
| #105-P2 dry-run real-mode UX | doppia conferma, banner rosso, evento `REAL_MODE_ENABLED`, armed-until-close | feature GUI/UX |
| #105-P2 multi-signal UX | warning modale, max active signals, indicatore righe attive | feature GUI/UX |
| #105-P3 atomic helper unico | `atomic_write_text/json/csv` condiviso | refactor trasversale (rivedibile) |

I P3 restanti sono **giudizi positivi** (validazione prezzi/BetType, recognition mode,
difesa CSV/chat) — nessuna azione.
