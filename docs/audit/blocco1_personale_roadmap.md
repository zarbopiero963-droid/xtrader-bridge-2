# BLOCCO 1 — USO PERSONALE — Roadmap (issue #86)

Questo documento mappa il piano di **issue #86** ("blocco 1 personale") nelle 13 PR
personali (PR-P1 → PR-P13). Ogni PR è **separata**, mirata e mergiata **manualmente**
dal proprietario; appena una PR viene mergiata si passa alla successiva.

## Obiettivo

Bridge per **uso personale**: Telegram → Parser → CSV/XTrader, con parser e name
mapping multi-sport e un sottosistema **Betfair Sync solo locale e read-only**.

## Regole assolute (valgono per TUTTE le PR del blocco)

- Betfair resta **100% locale**. Nessun dato Betfair esce dal PC/VPS.
- **Niente** Supabase, license key, Admin EXE, piani, pagamenti, dashboard clienti,
  cloud sync, backup/import/export Betfair.
- Il modulo Betfair è **solo read-only**. Operazioni **vietate**: `placeOrders`,
  `cancelOrders`, `replaceOrders`, `updateOrders` (vedi `xtrader_bridge/betfair/safety.py`).
- `sessionToken` **solo in RAM**, mai su disco. Mai loggare App Key, username,
  password, sessionToken, certificato, private key, headers, payload/response login.
- Nessun certificato incluso nel build.
- Il merge resta **sempre manuale** del proprietario.

## Scelta di struttura

Il repository usa un **package flat** `xtrader_bridge/` (60+ moduli) invece delle
cartelle top-level letterali del testo issue (`bridge_app/`, `betfair_sync/`,
`parser/`, `name_mapping/`, `xtrader_csv/`). Per coerenza con la convenzione
esistente, i nuovi moduli Betfair vivono nel **subpackage** `xtrader_bridge/betfair/`,
e parser / name mapping / CSV riusano i moduli già presenti
(`parser*.py`, `name_mapping_store.py`, `csv_writer.py`). Le regole di branch
richieste dall'issue sono già codificate in `AGENTS.md` / `CLAUDE.md` (mai su `main`,
crea branch se su `main`, continua se su branch non-main, una sola PR per scope) e
non vengono duplicate.

## Mappa PR

| PR     | Obiettivo                                   | Aree principali                                                        | Stato |
|--------|---------------------------------------------|-----------------------------------------------------------------------|-------|
| PR-P1  | Repository Foundation solo Bridge           | `betfair/` skeleton, guard read-only, hygiene test, questa roadmap     | merged (#165) |
| PR-P2  | Safe Logging + Secure Local Storage         | storage cifrato credenziali, sessionToken RAM-only, redaction filter   | in corso |
| PR-P3  | Tab Betfair Sync locale (GUI)               | tab GUI credenziali/sport/giorni/stato, pulsanti                       | TODO  |
| PR-P4  | Betfair Auth Client Italia                  | login/logout cert + Delayed App Key, token in RAM                      | TODO  |
| PR-P5  | Database Locale Betfair Multi-sport         | tabelle locali sport/comp/event/market/selection/sync/mapping         | TODO  |
| PR-P6  | Betfair Navigation + Catalogue Sync         | navigation menu + listMarketCatalogue, upsert read-only               | TODO  |
| PR-P7  | Sync Engine Manuale                         | motore unico sync manuale + riepilogo safe                            | TODO  |
| PR-P8  | Betfair Auto Sync Scheduler locale          | scheduler locale auto login→sync→auto logout                          | TODO  |
| PR-P9  | Parser Personalizzato Multi-sport / profilo | sport nel parser, campi core generici                                 | TODO  |
| PR-P10 | Name Mapping Multi-sport Locale             | tab mapping per sport/profilo, locale                                 | TODO  |
| PR-P11 | Dictionary Viewer Locale                    | viewer sola-lettura del dizionario Betfair                           | TODO  |
| PR-P12 | Telegram → Parser → Mapping → CSV XTrader   | integrazione flusso con fallback nomi                                 | TODO  |
| PR-P13 | Build EXE Personale                         | solo `XTraderBridge.exe`, nessun segreto/cert incluso                 | TODO  |

## Moduli implementati

### PR-P1 — `xtrader_bridge/betfair/`
- `safety.py`: guard read-only (`FORBIDDEN_BETTING_OPS`, `assert_read_only`,
  `is_forbidden_betting_op`, `ReadOnlyViolation`). Unico punto autorizzato a nominare
  le operazioni di scommessa vietate.

### PR-P2 — Safe Logging + Secure Local Storage
- `log_safety.py`: redazione dei log Betfair. `redact()` maschera header sensibili
  (`X-Authentication`, `X-Application`), `sessionToken`/`session_token` e qualsiasi
  segreto registrato via `register_secret()`/`unregister_secret()`.
  `SecretRedactionFilter` (logging.Filter) applica la redazione a ogni record;
  `quiet_http_libraries()` alza a WARNING i logger `requests`/`urllib3` (che a DEBUG
  riversano header/payload); `install_global_log_redaction()` installa il tutto.
- `session.py`: `BetfairSession` custodisce il `sessionToken` **solo in RAM** (mai su
  disco), non lo espone in `repr`/`str`, e lo registra/de-registra dai log a
  `set_token`/`clear`.
- `credential_store.py`: storage locale sicuro delle credenziali Betfair (Delayed App
  Key, username, password, percorsi cert/key) nel **keyring di sistema** (stesso
  pattern fail-safe di `token_store`). `masked()` mostra i segreti come `••••••` alla
  riapertura; i percorsi file restano in chiaro. Il `sessionToken` non è mai salvato.

## Definition of Done (blocco personale)

Il blocco è completo quando esiste `XTraderBridge.exe` personale; non esistono Admin
EXE/Supabase/licenza/pagamento; Betfair Sync usa la Delayed Key ed è read-only; le
credenziali Betfair sono locali e cifrate; il sessionToken resta in RAM; il dizionario
è locale; sono supportati Calcio/Tennis/Basket/Rugby Union; vengono salvati
MarketId/SelectionId correnti; l'Auto Sync fa auto login → sync → auto logout; il
parser e il name mapping sono multi-sport; Telegram → Parser → Mapping → CSV funziona;
nessun dato Betfair esce dal PC; nessun backup/import/export Betfair; nessun segreto
finisce nei log.
