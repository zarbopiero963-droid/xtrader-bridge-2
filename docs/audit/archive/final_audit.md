# Audit finale — XTrader Signal Bridge (Release Candidate)

> Documento di chiusura (PR-20, PHASE 9). Sintetizza lo stato del progetto dopo le
> PHASE 0–8 e mappa i problemi di `known_issues.md` alle PR che li hanno chiusi.
>
> **Onestà sui limiti:** questo audit è basato sull'analisi del codice e sui test
> automatici **offline** (headless). I passi che richiedono **Windows**, la **build
> EXE reale** o **XTrader live** NON sono eseguibili in questo ambiente e sono
> elencati come **verifiche manuali del proprietario** (vedi `release_checklist.md`
> e `xtrader_simulation_test.md`). Dove un esito non è stato verificato qui, è
> dichiarato esplicitamente "da verificare a mano", non "passato".

---

## 1. Esito sintetico

| Dimensione | Stato | Note |
|---|---|---|
| Contratto CSV XTrader (14 col) | ✅ Conforme | barriera di test `contract`; `utf-8-sig` + `QUOTE_ALL` |
| Parser (hardcoded + Parser Personalizzato) | ✅ Coperto da test | catena Telegram→riga validata, fail-closed |
| Validazione pre-scrittura | ✅ Implementata | nessun segnale invalido raggiunge il CSV |
| Telegram — filtro chat (single) | ✅ **Richiesto allo START** (PR-25) | `app._start` annulla l'avvio se non c'è `chat_id`/`parser_by_chat`/sorgente (`has_chat_filter`) — vedi §4 |
| Telegram — multi-chat (provider/mode) | ✅ **Agganciata al runtime** (PR-24) | `signal_router` ammette le sorgenti attive e usa il provider per-chat (PRE→TG_PRE/LIVE→TG_LIVE) |
| Config persistente (`%APPDATA%`) | ✅ Implementata | migrazione legacy + backup config corrotta |
| Scrittura CSV atomica + svuotamento | ✅ Implementata | tmp+rename, header sempre presente |
| Anti-duplicato + limite/minuto + limite/giorno | ✅ **Agganciati al runtime** (PR-21) | `live_guard` in `app._process` (dedup+rate `signal_dedupe`, giorno `safety_guard`) |
| DRY_RUN (simulazione) | ✅ **Agganciato al runtime** (PR-21) | in DRY_RUN il CSV operativo NON viene scritto |
| Coda multi-segnale | ✅ **Agganciata al runtime** (PR-22) | `signal_queue` in `app._process` + scrittura CSV multi-riga; default OVERWRITE_LAST |
| Conferma XTrader | ✅ **Agganciata al runtime** (PR-23) | `confirmation_reader` in `app._process_confirmation`; chat notifiche → CONFIRMED/REJECTED rimuove il segnale |
| Build EXE Windows (versionata) | ⚠️ Workflow pronto, build non eseguita qui | verifica manuale |
| Supply-chain (action SHA-pinned) | ✅ Implementato | test di enforcement |
| Test automatici | ✅ 628 passed, 3 skipped | vedi §3 |
| Segreti nel repo | ✅ Nessuno | `forbidden-files` + test no-secrets |

**Stato complessivo:** RELEASE CANDIDATE per i test in **simulazione**. Non è un via
libera all'uso reale: il merge resta manuale e l'uso operativo richiede le verifiche
manuali su Windows/XTrader e l'attivazione esplicita della modalità reale.

---

## 2. Mappa problemi (`known_issues.md`) → PR che li chiude

| # | Problema | Chiuso da | Stato |
|---|---|---|---|
| 1 | Validazione segnale prima del CSV | PR-01, PR-06, PR-10 | ✅ |
| 2 | Race write/clear | PR-05, PR-16 | ✅ |
| 3 | Parser P.Bet. senza emoji | PR-09 | ✅ |
| 4 | Formato CSV README vs codice | PR-01 | ✅ |
| 5 | Timestamp anti-duplicato | PR-01 (fuori CSV) + PR-15 | ✅ |
| 6 | Scrittura atomica / lock | PR-05 | ✅ |
| 7 | `.gitignore` mancante | PR-00 | ✅ |
| 8 | Filtro `chat_id` permissivo | PR-11, PR-12 | ✅ |
| 9 | `TELEGRAM_OK` mai controllato | PR-03, PR-11 | ✅ |
| 10 | Validazione input GUI | PR-13 | ✅ |
| 11 | Errori silenziati | PR-11, PR-14 | ✅ |
| 12 | Stake / MinPrice / MaxPrice | PR-01, PR-13 | ✅ (Stake gestito in XTrader) |
| 13 | Test automatici assenti | PR-02 + ogni PR | ✅ |
| 14 | README rotto/incoerente | PR-01, PR-18, PR-20 | ✅ |
| 15 | Build EXE | PR-18 | ⚠️ workflow pronto, build manuale |

> **Nota:** "Chiuso da" indica la PR che ha implementato la logica, **ora tutta
> agganciata al runtime**: anti-duplicato (#5) + DRY_RUN/limiti (PR-21), coda
> multi-segnale (#2 residuo, PR-22), conferma XTrader (PR-23), multi-chat (PR-24).
> Unica avvertenza: il filtro chat (#8) è effettivo solo con `chat_id`/sorgente
> configurati — vedi §4.

---

## 3. Stato per area

### CSV (contratto)
- Header a 14 colonne in `csv_writer.CSV_HEADER`, order-sensitive; `BetType` ∈
  {PUNTA, BANCA}; `Handicap`=0; `Points` vuoto; `utf-8-sig` + `QUOTE_ALL`.
- Barriera di test `tests/unit/test_csv_contract.py` (job CI `contract`): diventa
  rossa se cambiano header/ordine/encoding/quoting o rientrano `Stake`/`Timestamp`.
- Scrittura atomica (`write_atomic`/tmp+rename) e svuotamento che mantiene l'header.

### Parser
- **Hardcoded** (`parser.py`): P.Bet. con/senza emoji, quota `,`/`.`, squadre `Home v Away`.
- **Parser Personalizzato** (CP-01…CP-10): regole configurabili (`start_after`/
  `end_before`), trasformazioni, value-map (dizionario + bettype), gate "Non pronto",
  routing per chat. Catena end-to-end testata in `tests/integration`.
- Fail-closed: un segnale incompleto/ambiguo NON produce una riga CSV.

### Mapping / dizionario
- `mapping.py`, `value_maps.py`, `dizionario.py`: alias Telegram → MarketType/
  SelectionName XTrader; alias ambigui scartati (mai una selezione tradotta a caso).

### Telegram
- **Agganciato al runtime** (`app` → `signal_router.should_process`/`resolve_row`):
  `drop_pending_updates`; filtro chat `is_chat_allowed`. **Attenzione:** con
  `chat_id`, `parser_by_chat` **e** sorgenti `source_chats` tutti vuoti, `is_chat_allowed`
  ammette **tutte** le chat (comportamento legacy). Il filtro è effettivo **solo** se in
  config c'è almeno un `chat_id`/override/sorgente; la release checklist lo richiede.
- **Multi-chat AGGANCIATO (PR-24):** `signal_router` ammette le sorgenti `source_chats`
  **attive** (disattivate ignorate) e `resolve_row` usa il **provider per-chat**
  (`source_manager.provider_for_chat`: esplicito, o PRE→`TG_PRE`/LIVE→`TG_LIVE`, con
  fallback al provider globale per le chat senza sorgente).
- `event_log`: log con **redazione dei segreti** (mai token Telegram nei log).

### Config
- `config_store`: `%APPDATA%\XTraderBridge\config.json`; migrazione legacy; backup
  `.bak` su config corrotta; default sicuri; chiavi additive senza rompere config vecchie.

### Anti-duplicato / limiti / DRY_RUN — AGGANCIATI (PR-21)
- `app._process` chiama `live_guard.evaluate(cfg, tracker, daily, text)` prima di
  scrivere: **un duplicato, una raffica oltre il limite/minuto, il superamento del
  limite/giorno o la modalità DRY_RUN sopprimono la scrittura del CSV** (solo `WRITE`
  scrive). Il `SignalTracker` (PR-15) persiste in `%APPDATA%\XTraderBridge\
  dedupe_state.json` → i duplicati recenti restano riconosciuti dopo un riavvio.
  `DailyLimiter` (PR-19) usa `max_per_day` dalla config. La protezione
  doppia-scommessa è **attiva** a runtime.

### Coda multi-segnale — AGGANCIATA (PR-22)
- `app._process` usa `signal_queue.SignalQueue` (modalità da `queue_mode`, default
  **OVERWRITE_LAST** = un solo segnale attivo) e scrive **tutte** le righe attive con
  `csv_writer.write_rows`. Timeout per-segnale = `clear_delay`; un tick di scadenza
  rimuove i segnali scaduti e riscrive le righe rimaste (o svuota il CSV). Su scrittura
  fallita il segnale viene tolto dalla coda (riprovabile).

### Conferma XTrader — AGGANCIATA (PR-23)
- `app._handle` instrada i messaggi dalla chat `xtrader_notification_chat_id`
  (separata dalle sorgenti) a `_process_confirmation`, che costruisce i `pending`
  dalla coda (`SignalQueue.pending()`) e chiama `confirmation_reader.interpret`.
  **CONFIRMED/REJECTED** → il segnale è rimosso dalla coda e dal CSV; UNKNOWN/UNMATCHED
  → solo log; il TIMEOUT è coperto dalla scadenza coda. Attiva solo se la chat
  notifiche è configurata. Match per nomi (la riga CSV non ha un SignalRef).

### Build / supply-chain
- `build.yaml`: test → compile → PyInstaller `--windowed` → artifact **versionato**
  (`__version__` 0.1.0 + data); release solo su tag `v*`.
- Tutte le action dei workflow sono **fissate a SHA** (hardening) con test di enforcement.

### Test / coverage
- Vedi sotto — 628 passed, 3 skipped (offline). I test live/manuali sono marcati `manual`.

```
unit         553 test
integration   21 test
safety        22 test
smoke         35 test
TOTALE       628 passed, 3 skipped (marcatore "manual" escluso)
```

---

## 4. Limiti noti / lavoro residuo (onesto)

> I punti seguenti sono **TODO rintracciabili** (greppabili come `TODO(wiring)`): da
> trasformare in una issue/PR di follow-up dedicata prima dell'uso reale. Non sono
> note "stantie": descrivono lavoro non ancora fatto.

> **Cosa è agganciato al runtime oggi** (`app` → `signal_router`/`live_guard`): filtro
> chat (se `chat_id` configurato), parsing (hardcoded + Parser Personalizzato per chat),
> validazione contratto, **anti-duplicato + limite/minuto + limite/giorno + DRY_RUN**
> (PR-21), **coda multi-segnale + scrittura CSV multi-riga** (PR-22), **conferma
> XTrader** (PR-23), **multi-chat provider/mode** (PR-24), scrittura/svuotamento CSV
> atomici, log con redazione. **Tutta la logica di sicurezza è ora agganciata al
> runtime**; quanto resta sotto sono verifiche manuali e una nota sul filtro chat.
>
> ✅ **Agganciati**: DRY_RUN, anti-duplicato, limite/minuto, limite/giorno (PR-21);
> coda multi-segnale + timeout per-segnale (PR-22); conferma XTrader (PR-23);
> multi-chat provider/mode (PR-24). La protezione doppia-scommessa è attiva a runtime.

1. ✅ **Filtro chat richiesto allo START (PR-25)**: il caso "config vuota → ammetti
   tutte" non è più raggiungibile a runtime. `app._start` chiama
   `signal_router.has_chat_filter(cfg)` e **annulla l'avvio** se non c'è almeno un
   `chat_id`, un `parser_by_chat` o una `source_chats` (anche disattivata).
   `is_chat_allowed` conserva la semantica legacy (utile a test/funzioni pure), ma il
   bridge non parte senza un criterio di ammissione chat.
2. **GUI**: i controller sono testati headless, ma avvio GUI, START/STOP, salvataggio e
   builder del Parser Personalizzato vanno verificati a mano su Windows. ✅ **PR-13**:
   le impostazioni avanzate (`recognition_mode`, `require_price`, `dry_run`,
   `max_per_day`, `queue_mode`, chat notifiche XTrader) sono ora esposte in GUI a
   **tab** (logica in `settings_controller`, testata in CI); START si **blocca** se
   un'impostazione avanzata è invalida. `confirmation_timeout` è **collegato al
   runtime** (PR-17b: timeout per-segnale in `QUEUE_UNTIL_CONFIRMED`).
   ✅ **PR-14**: dashboard con **contatori di sessione**
   (ricevuti/scritti/scartati/duplicati/limitati/simulati/errori, modulo puro
   `dashboard_stats` testato in CI; agganciati in `_process`/`_after_non_write`).
   ✅ **PR-14b**: **filtro del log per livello** (Tutti/INFO/WARNING/ERROR/SIGNAL)
   nel riquadro log (logica pura `log_view` su `event_log.filter_by_level`, testata
   in CI). ✅ **PR-14c**: **diagnostica** — pannello STATO con ultimo messaggio/segnale/
   CSV/errore + pulsanti "📂 Apri cartella log" e "📋 Copia diagnostica" (report puro
   `diagnostics`, segreti redatti, testato in CI). ✅ **PR-13b**: editor delle
   **sorgenti multi-chat** (`source_chats`) in GUI
   (pulsante "📡 Chat sorgenti": nome/chat_id/attiva/modalità/provider, validazione via
   `source_editor`/`source_manager`, salvataggio in `config.json`) — non serve più
   editare il file a mano per il supporto multi-chat. ✅ **PR-13c**: override **parser
   per chat** (`parser_by_chat`) editabile dalla stessa finestra (colonna Parser per
   sorgente; le voci di chat non mostrate sono preservate). ✅ **PR-17c**: la tab
   *Conferme XTrader* espone ora anche `confirmation_timeout` (validato come intero > 0)
   e le parole chiave `confirmation_keywords` / `rejection_keywords` come **stringa CSV**
   (round-trip lista↔stringa in `settings_controller`, testato in CI). Restano da
   verificare a mano i widget su Windows.
3. **Build EXE**: workflow pronto, build reale non eseguibile qui.
4. **XTrader live**: lettura CSV, segnale verde, conferma Telegram sono passi manuali in
   **simulazione** (vedi `xtrader_simulation_test.md`).

---

## 5. Invarianti di sicurezza

**Attive a runtime (e verificate nei test offline):**
- Nessun segnale invalido raggiunge il CSV (validator + gate nel percorso `resolve_row`).
- **Anti-duplicato + limite/minuto + limite/giorno + DRY_RUN** (PR-21, `live_guard`):
  un duplicato/raffica/over-quota o la simulazione **sopprimono la scrittura**.
- **Coda dei segnali attivi** (PR-22, `signal_queue`): default OVERWRITE_LAST (un solo
  segnale attivo); timeout per-segnale rimuove gli scaduti e riscrive le righe rimaste.
- **Conferma XTrader** (PR-23, `confirmation_reader`): una notifica CONFIRMED/REJECTED
  dalla chat notifiche rimuove il segnale dalla coda e dal CSV (se la chat è configurata).
- **Multi-chat** (PR-24, `source_manager`): solo le sorgenti **attive** sono ammesse
  (disattivate ignorate); provider per-chat (PRE→TG_PRE/LIVE→TG_LIVE) nella riga CSV.
- Scrittura/svuotamento CSV atomici (incl. multi-riga `write_rows`); header sempre presente.
- Filtro chat **richiesto allo START** (PR-25, `has_chat_filter`): il bridge non parte
  senza almeno un `chat_id`/`parser_by_chat`/sorgente, quindi il caso "config vuota →
  ammetti tutte" non è raggiungibile a runtime (vedi §4 punto 1).
- Nessun token/segreto nei log (redazione) né nel repo (`forbidden-files` + test).
- Contratto CSV invariato dalle PR successive a PR-01 (barriera `contract`).
- Merge sempre **manuale** del proprietario; nessun auto-merge.

**Tutta la logica di sicurezza è ora agganciata al runtime** (PR-21→PR-24): non
restano moduli "puri ma non collegati". Il filtro chat è ora **richiesto allo START**
(PR-25). Restano solo le verifiche **manuali** su Windows/XTrader (GUI, build EXE,
simulazione end-to-end).

---

## 6. Conclusione

Il progetto soddisfa gli obiettivi della roadmap per una **release candidate da
testare in simulazione**. Prima di qualunque uso reale: eseguire
`release_checklist.md` e `xtrader_simulation_test.md` su Windows con XTrader in
**Modalità Simulazione**, stake basso, limiti chiari. Nessuna promessa di profitto.
