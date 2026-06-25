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
| C4 | `load_dizionario` senza validazione header (colonna rinominata → fail silenzioso/crash) | `dizionario.py` | `fix/audit-104-c4` | 🔧 |
| C5 | `load_config` senza migrazione/schema | `config_store.py` | — | ⬜ |
| C6 | `should_reconnect` classifica per nome classe sull'MRO | `reconnect_policy.py` | — | ⬜ |
| C7 | `save_config` ritorna shallow-copy con nested condivisi | `config_store.py` | — | ⬜ |
| C8 | Keyword conferma/notif lette da snapshot mentre routing è live | `app.py` | — | ⬜ |

### 🟢 LOW / NIT
| ID | Finding | Stato |
|----|---------|-------|
| L1 | `name_mapping_store` non normalizza i nomi-profilo con whitespace | ⬜ |
| L2 | `_safe_filename` accetta nomi device riservati Windows (`con`,`nul`) | ⬜ |
| L3 | `migrate_legacy_config` usa `copyfile` non atomico | ⬜ |
| L4 | Regex decimali duplicata in 3 moduli (drift) | ⬜ |
| L5 | `bet_type` con classe di caratteri accentati ristretta | ⬜ |
| L6 | `--ignore=tests/{e2e,slow,manual}` su dir inesistenti + marker inutilizzati | ⬜ |
| L7 | `cache-dependency-path` su `requirements-dev.txt` non invalida su bump | ⬜ |
| L8 | Commento `# v1` vago su `action-gh-release` | ⬜ |

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

## Issue #105 — *(da leggere quando #104 è interamente chiusa)*
Roadmap da compilare dopo la lettura.
