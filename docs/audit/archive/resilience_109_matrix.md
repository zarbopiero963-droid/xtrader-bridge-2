# Matrice di copertura — piano di resilienza #109

Stato punto-per-punto dei 40 item del piano di resilienza/crash-recovery (issue #109).
Legenda: **COVERED** = test automatico reale esistente · **NEW** = aggiunto in questa PR ·
**MANUAL_ONLY** = richiede ambiente reale (Windows/EXE/XTrader/Telegram live/GUI), non
automatizzabile in CI → checklist di release in fondo.

> Nota sui due "code-fix" della baseline #109 (scritta il 2026-06-24): **entrambi già risolti**
> in `main` quando questa matrice è stata redatta.
> - **item 4** — `daily_state.json` ora è scritto **atomico + `fsync`** via
>   `atomic_io.atomic_write_json` (`safety_guard.save_state`, audit #105 P2). Il gap "senza fsync"
>   non esiste più.
> - **item 13** — `message_freshness.is_stale` è **fail-closed** su `msg.date=None`/timestamp
>   illeggibile (audit A4). Già il comportamento desiderato.

## 🔴 CRASH / POWER-LOSS RECOVERY
| # | Stato | Evidenza |
|---|---|---|
| 1 | COVERED | `tests/safety/test_csv_atomic.py::test_clear_stale_csv_rimuove_riga_orfana` |
| 2 | COVERED | `tests/unit/test_signal_dedupe.py::test_restart_riconosce_duplicati_recenti` |
| 3 | COVERED | `tests/unit/test_signal_dedupe.py::test_load_state_json_malformato_ritorna_false` |
| 4 | COVERED | `safety_guard.save_state` (atomic+fsync, #105 P2) · `tests/unit/test_safety_guard.py::test_stato_sopravvive_al_riavvio_stesso_giorno` |
| 5 | COVERED | `tests/unit/test_safety_guard.py` (restore malformato tollerante) |
| 6 | COVERED | `tests/safety/test_atomic_io.py` (crash tra `.tmp` e `replace`) |
| 7 | COVERED | `tests/integration/test_app_runtime_glue.py::test_confirmation_write_failure_segnale_rimosso_e_retry_breve` (no doppia; coda non persistita → restart vuoto fail-safe) |
| 8 | COVERED | `tests/unit/test_safety_guard.py::test_reset_al_cambio_giorno` |
| 9 | COVERED | `tests/unit/test_signal_dedupe.py::test_dedupe_robusto_a_clock_all_indietro` (#160) |

## 🔴 RICONNESSIONE / RETE
| # | Stato | Evidenza |
|---|---|---|
| 10 | COVERED | `tests/integration/test_listener_dispatch.py::test_start_polling_scarta_arretrati_e_ammette_channel_post` (#161) |
| 11 | COVERED | `tests/unit/test_reconnect_policy.py` (`effective_delay` con `retry_after`) |
| 12 | **NEW** | `tests/integration/test_resilience_109.py::test_errore_non_recuperabile_ferma_senza_retry` |
| 13 | COVERED | `tests/unit/test_message_freshness.py` (`msg.date=None` → fail-closed, A4) |
| 14 | **NEW** | `tests/integration/test_resilience_109.py::test_epoch_stale_non_avvia_un_secondo_poller` |

## 🔴 CONCORRENZA / RACE
| # | Stato | Evidenza |
|---|---|---|
| 15 | COVERED | `tests/unit/test_write_path.py` (sequenza valuta+coda+scrittura sotto un solo lock → una riga, una slot) + dedupe |
| 16 | **NEW** | `tests/integration/test_resilience_109.py::test_expire_tick_vs_process_concorrenti_non_corrompono_csv` |
| 17 | COVERED | `tests/integration/test_app_runtime_glue.py::test_process_gate_running_false_non_scrive` / `..._expire_tick_gate_running_false_non_riscrive` (#161) |
| 18 | **NEW** | `tests/safety/test_csv_atomic.py::test_stress_write_clear_500_iterazioni_non_corrompe` (`slow`) — estende il test base a 500 iter |

## 🟠 LIFECYCLE / TEARDOWN
| # | Stato | Evidenza |
|---|---|---|
| 19 | MANUAL_ONLY | chiusura finestra con thread bot + loop asyncio reali (GUI Tk) — checklist |
| 20 | MANUAL_ONLY | START/STOP/START con thread/loop reali — checklist (la logica epoch è in #14) |
| 21 | COVERED | `tests/integration/test_app_runtime_glue.py::test_stop_svuota_coda_e_csv_attivo_non_gui` (#161) |
| 22 | COVERED | `tests/integration/test_app_runtime_glue.py::test_manual_clear_write_failure_non_svuota_coda` + `tests/unit/test_csv_lock_escalation.py` |

## 🟠 AUTO-START
| # | Stato | Evidenza |
|---|---|---|
| 23 | COVERED | `tests/unit/test_autostart.py` (conferma richiesta in modalità reale) |
| 24 | COVERED | `tests/unit/test_autostart.py` (token/chat mancanti → non avviabile) |
| 25 | **NEW** | `tests/integration/test_resilience_109.py::test_cancel_pending_autostart_annulla_il_callback` |

## 🟠 PERSISTENZA CONFIG / STATO
| # | Stato | Evidenza |
|---|---|---|
| 26 | COVERED | `tests/unit/test_config_basic.py::test_backup_corrotto_fallito_logga_warning` |
| 27 | COVERED | `tests/unit/test_config_basic.py::test_save_config_fallback_write_fallita_ritorna_ok_false` |
| 28 | **NEW** | `tests/unit/test_config_basic.py::test_roundtrip_csv_path_windows_backslash_spazi_unicode` |
| 29 | MANUAL_ONLY | reinstall preserva config in `%APPDATA%` — checklist Windows |

## 🟡 INPUT-HARDENING / FUZZ
| # | Stato | Evidenza |
|---|---|---|
| 30 | COVERED | `tests/unit/test_signal_dedupe.py` + `tests/unit/test_validators.py` (now/parametri fail-closed) |
| 31 | COVERED | `tests/unit/test_parser_fuzz.py` (fuzz deterministico, mai riga senza obbligatori) |
| 32 | COVERED | `tests/unit/test_csv_contract.py` (injection `=`/`+`/`@`/CR neutralizzata) |
| 33 | COVERED | `tests/unit/test_dizionario.py` (alias duplicato segnalato) |

## 🟡 WINDOWS / EXE / XTRADER REALE — checklist di release (MANUAL_ONLY)
Non automatizzabili in CI: vanno eseguiti a mano su Windows con XTrader/Telegram reali e
spuntati prima di una release. Vedi anche `docs/audit/release_checklist.md` e
`docs/audit/xtrader_simulation_test.md`.

- [ ] 34 — Build PyInstaller EXE su Windows.
- [ ] 35 — CSV scritto nel path XTrader reale, importato correttamente.
- [ ] 36 — File lock Windows mentre XTrader legge (`_replace_with_retry` reale; logica pura già in `tests/safety/test_csv_atomic.py`).
- [ ] 37 — Antivirus/quarantena EXE.
- [ ] 38 — DPI/scaling display.
- [ ] 39 — Permessi cartella XTrader (logica `errore_permessi` già coperta con mock).
- [ ] 40 — Telegram sandbox con bot finto end-to-end.
- [ ] 19/20/29 — teardown finestra, START/STOP ripetuti, reinstall/AppData: smoke manuale (la logica pura/glue sottostante è coperta dai test headless sopra).

## Riepilogo
- **COVERED (esistenti):** 1,2,3,4,5,6,7,8,9,10,11,13,15,17,21,22,23,24,26,27,30,31,32,33
- **NEW (questa PR):** 12,14,16,18,25,28
- **MANUAL_ONLY (checklist release):** 19,20,29,34,35,36,37,38,39,40
- I due "code-fix" della baseline (4 fsync, 13 fail-open) erano **già risolti** in `main`.
