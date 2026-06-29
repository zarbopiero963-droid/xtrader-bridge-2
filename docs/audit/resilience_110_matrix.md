# Matrice di copertura — piano di resilienza #110

La issue #110 è un secondo "Codex resilience / crash-recovery test plan", in larga parte
**sovrapposto a #109**. Questa matrice mappa la sua **"lista finale dei test potenti da
aggiungere"** (20 voci) allo stato attuale. Vedi anche `docs/audit/resilience_109_matrix.md`.

Legenda: **COVERED** = test automatico reale · **NEW** = aggiunto in questa PR ·
**MANUAL_ONLY** = richiede ambiente reale · **FEATURE** = non è un test ma una nuova
funzionalità (decisione del proprietario).

| # | Voce | Stato | Evidenza |
|---|---|---|---|
| 1 | App boot crash recovery: CSV con riga → cleanup prima di auto-start | PARTIAL | funzione coperta: `tests/safety/test_csv_atomic.py::test_clear_stale_csv_rimuove_riga_orfana`. L'ORDINE in `App.__init__` (cleanup PRIMA dell'auto-start) NON è testato a runtime headless (`__init__` apre Tk; un test sul solo sorgente sarebbe decorativo) → smoke manuale `release_checklist.md` §I (#110/1: CSV stantio + `auto_start_listener=true` → cleanup all'avvio PRIMA dell'auto-start). Difesa runtime aggiuntiva: anche `_start` chiama `init_csv` (svuota il CSV) prima di attivarsi, quindi una riga stantia non sopravvive comunque a un avvio |
| 2 | App auto-start dry-run: parte solo se token/chat ok | PARTIAL | decisione pura: `tests/unit/test_autostart.py` (`can_auto_start`/`is_enabled`) · gating runtime di `App._maybe_auto_start` (disabilitato/`_closing`/`_running` → non chiama `_start`): `tests/integration/test_reconnect_110.py::test_maybe_auto_start_gating_non_parte_se_disabilitato_chiusura_o_running` · gate fine token/chat dentro `_start` = GUI, non headless |
| 3 | App auto-start real: chiede conferma; se no non parte | PARTIAL | decisione pura: `tests/unit/test_autostart.py::test_conferma_richiesta_solo_in_modalita_reale` (`needs_real_mode_confirmation`) · il branch runtime `App._start(auto=True)` che onora un `messagebox.askyesno` NEGATO è dentro `_start` (GUI-coupled), NON testato headless → smoke manuale Windows (§F) |
| 4 | Mock Telegram `drop_pending_updates=True` (+allowed_updates) | COVERED | `tests/integration/test_listener_dispatch.py::test_start_polling_scarta_arretrati_e_ammette_channel_post` (#161) |
| 5 | Mock Telegram stale update → `_process` non chiamato | COVERED | `tests/integration/test_listener_dispatch.py::test_messaggio_vecchio_ignorato` (#161) |
| 6 | Reconnect lifecycle: errore transitorio → shutdown → backoff → retry → reset | **NEW** | `tests/integration/test_reconnect_110.py::test_reconnect_lifecycle_chiude_il_vecchio_updater_e_ritenta` |
| 7 | STOP durante backoff interrompe subito | **NEW** | `tests/integration/test_reconnect_110.py::test_stop_durante_backoff_vivo_interrompe_subito` (wait reale interrotto) + `::test_stop_reale_sveglia_il_backoff` (il vero `_stop` imposta `_stop_event`) |
| 8 | No double poller: nuovo START invalida vecchio epoch | COVERED | `tests/integration/test_resilience_109.py::test_epoch_stale_non_avvia_un_secondo_poller` (#162, epoch stale all'avvio) + `tests/integration/test_reconnect_110.py::test_epoch_cambiato_dopo_fallimento_non_ritenta` (epoch cambiato DURANTE il backoff dopo un fallimento → niente retry) |
| 9 | `_process` write failure rollback: queue/tracker/daily ripristinati | COVERED | `tests/integration/test_app_runtime_glue.py::test_process_write_failure_rollback_e_ritentabile` (#161) |
| 10 | Crash dopo CSV write prima di guard save | PARTIAL | Coperto: success-path (`test_process_write_success_accoda_e_scrive`) + rollback su write fallita (`test_process_write_failure_rollback_e_ritentabile`). NON simulata la finestra esatta "write riuscita → crash → prima di `_save_guard_state`": è un tradeoff fail-safe noto (issue #110 §4.4) — a restart il CSV è ripulito (niente riga orfana) e lo stato guard è best-effort persistito DOPO la write, quindi un crash in quella finestra può far "dimenticare" al dedupe/daily un segnale già scritto. Da blindare con un test mirato sul boundary, o accettato come design |
| 11 | Daily state atomico: fsync / replace failure / corrupt | COVERED | `tests/unit/test_safety_guard.py::test_save_load_state_round_trip_senza_temporanei`, `::test_save_state_atomico_non_distrugge_il_file_su_errore`, `::test_load_state_file_assente_o_corrotto_ritorna_false` |
| 12 | `_process_confirmation` write failure → retry breve | COVERED | `tests/integration/test_app_runtime_glue.py::test_confirmation_write_failure_segnale_rimosso_e_retry_breve` (#161) |
| 13 | STOP durante confirmation retry: non riscrive dopo clear | COVERED | gate `_running`: `tests/integration/test_app_runtime_glue.py::test_confirmation_gate_running_false_e_no_op` + `tests/integration/test_app_runtime_glue.py::test_expire_tick_gate_running_false_non_riscrive` (#161) |
| 14 | Manual clear running usa `_active_csv_path`, non il campo GUI | COVERED | `tests/integration/test_app_runtime_glue.py::test_manual_clear_running_usa_active_path_non_gui` (#161) |
| 15 | XTrader file lock Windows: START fallisce pulito, runtime retry | PARTIAL | logica low-level: `tests/safety/test_csv_atomic.py` (`_replace_with_retry`, `errore_permessi`) + `_manual_clear` su I/O fallito (`test_manual_clear_write_failure_non_svuota_coda`, #161). NON testato headless `App._start()` con `init_csv` che solleva → `_running` resta False (`_start` è fortemente accoppiato alla GUI, non istanziabile headless) · lock Windows reale + START fallito = manuale (`release_checklist.md` §I, #110/15) |
| 16 | Windows reboot manuale: Startup/Task Scheduler + auto_start | MANUAL_ONLY | `release_checklist.md` §I (#110/16) |
| 17 | Power-cut manuale: VM kill con CSV attivo | MANUAL_ONLY | `release_checklist.md` §I (#110/17) |
| 18 | Telegram live outage manuale: rete giù, backlog, reconnect | MANUAL_ONLY | `release_checklist.md` §I (#110/18) |
| 19 | XTrader sandbox: CSV reale letto una volta, clear, no duplicate | MANUAL_ONLY | `release_checklist.md` §I (#110/19) |
| 20 | Transaction/event journal strutturato ("cosa aveva fatto") | **DONE** | implementato (#230): ledger append-only `event_journal.py` **agganciato al runtime** (`app.py`) — `START`/`STOP`/`RECONNECT`/`SIGNAL_RECEIVED`/`SIGNAL_VALIDATED`/`CSV_WRITTEN`/`XTRADER_CONFIRMED`/`XTRADER_REJECTED`/`CRASH_RECOVERY_CSV_CLEARED`/`CSV_CLEARED`. Best-effort (mai bloccante), redatto, bounded (`prune_events` allo startup). Test: `tests/unit/test_event_journal.py` (modulo+retention) + `tests/integration/test_event_journal_wiring.py` (wiring) |

\* COVERED a livello di funzione/logica e (dove possibile) di glue headless; la verifica
end-to-end su GUI reale / Windows / XTrader resta nella checklist manuale.

## Riepilogo
- **NEW (questa PR):** 6, 7
- **COVERED (esistenti, molti da #160/#161/#162):** 4,5,8,9,11,12,13,14
- **PARTIAL:** 1 (ordine `__init__` non testabile headless; funzione coperta + difesa `_start`/`init_csv`) · 2 (gate token/chat dentro `_start` GUI, ma gating `_maybe_auto_start` testato) · 3 (branch `_start(auto=True)` con `askyesno` negato = GUI, ma decisione pura testata) · 10 (finestra crash post-write/pre-guard-save non simulata) · 15 (`App._start()` con `init_csv` fallito non testabile headless) — vedi righe
- **MANUAL_ONLY (checklist release):** 16,17,18,19 — passi esatti in `docs/audit/release_checklist.md` §I
- **FEATURE (decisione proprietario):** 20 — event journal transaction-grade

I due punti "deboli" segnalati dalla baseline #110 — daily_state senza fsync e listener
reale non testato — sono entrambi **chiusi**: il daily è atomico+fsync (#105 P2, testato) e
il supervisor reconnect è ora esercitato headless (voci 6/7 + 4/5/8).
