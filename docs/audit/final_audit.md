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
| Telegram — filtro chat (single) | ⚠️ Attivo **solo se `chat_id` configurato** | con `chat_id`/`parser_by_chat` vuoti il default è "ammetti tutte" (legacy) — vedi §4 |
| Telegram — multi-chat (provider/mode) | ⚠️ Logica pura, **non agganciata al runtime** | `source_manager`/`source_chats` non letti da `app`/`signal_router` — vedi §4 |
| Config persistente (`%APPDATA%`) | ✅ Implementata | migrazione legacy + backup config corrotta |
| Scrittura CSV atomica + svuotamento | ✅ Implementata | tmp+rename, header sempre presente |
| Anti-duplicato + limite/minuto + limite/giorno | ✅ **Agganciati al runtime** (PR-21) | `live_guard` in `app._process` (dedup+rate `signal_dedupe`, giorno `safety_guard`) |
| DRY_RUN (simulazione) | ✅ **Agganciato al runtime** (PR-21) | in DRY_RUN il CSV operativo NON viene scritto |
| Coda multi-segnale / conferma XTrader | ⚠️ Logica pura testata, **non agganciata** | `signal_queue`/`confirmation_reader` non usati da `app` — vedi §4 |
| Build EXE Windows (versionata) | ⚠️ Workflow pronto, build non eseguita qui | verifica manuale |
| Supply-chain (action SHA-pinned) | ✅ Implementato | test di enforcement |
| Test automatici | ✅ 536 passed, 2 skipped | vedi §3 |
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

> **Nota:** "Chiuso da" indica la PR che ha implementato la logica. Anti-duplicato (#5)
> e DRY_RUN/limiti sono ora **agganciati al runtime** (PR-21). Restano logiche pure non
> ancora collegate: coda (#2 residuo), conferma XTrader, multi-chat; il filtro chat (#8)
> è effettivo solo con `chat_id` configurato — vedi §4.

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
  `chat_id` **e** `parser_by_chat` entrambi vuoti, `is_chat_allowed` ammette **tutte**
  le chat (comportamento legacy). Il filtro è effettivo **solo** se in config c'è un
  `chat_id` (o un override per chat); la release checklist lo richiede esplicitamente.
- **NON agganciato al runtime:** `source_manager` e `source_chats` (multi-chat con
  provider/mode) non sono importati né letti da `app`/`signal_router` → chat disattivate
  e provider/mode per-chat sono **ignorati a runtime** (`TODO(wiring)`, §4).
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

### Coda / conferma (logica pura, NON ancora agganciata)
- `signal_queue` (coda multi-segnale + timeout) e `confirmation_reader` (lettura
  conferme XTrader): **moduli puri testati ma non usati da `app`** → una notifica
  XTrader **non** marca ancora alcun segnale CONFIRMED/REJECTED/TIMEOUT
  (`TODO(wiring)`, §4).

### Build / supply-chain
- `build.yaml`: test → compile → PyInstaller `--windowed` → artifact **versionato**
  (`__version__` 0.1.0 + data); release solo su tag `v*`.
- Tutte le action dei workflow sono **fissate a SHA** (hardening) con test di enforcement.

### Test / coverage
- Vedi sotto — 536 passed, 2 skipped (offline). I test live/manuali sono marcati `manual`.

```
unit         471 test
integration   17 test
safety        22 test
smoke         28 test
TOTALE       536 passed, 2 skipped (marcatore "manual" escluso)
```

---

## 4. Limiti noti / lavoro residuo (onesto)

> I punti seguenti sono **TODO rintracciabili** (greppabili come `TODO(wiring)`): da
> trasformare in una issue/PR di follow-up dedicata prima dell'uso reale. Non sono
> note "stantie": descrivono lavoro non ancora fatto.

> **Cosa è agganciato al runtime oggi** (`app` → `signal_router`/`live_guard`): filtro
> chat (se `chat_id` configurato), parsing (hardcoded + Parser Personalizzato per chat),
> validazione contratto, **anti-duplicato + limite/minuto + limite/giorno + DRY_RUN**
> (PR-21), scrittura/svuotamento CSV atomici, log con redazione. Quanto resta sotto è
> **logica pura testata ma non ancora collegata** al bot live.
>
> ✅ **Agganciati in PR-21** (non più TODO): DRY_RUN, anti-duplicato, limite/minuto,
> limite/giorno. La protezione doppia-scommessa è ora attiva a runtime.

1. **`TODO(wiring)` — Coda multi-segnale (PR-16)**: `signal_queue` (modalità + timeout per
   segnale) non è collegato al flusso live.
2. **`TODO(wiring)` — Conferma XTrader (PR-17)**: `confirmation_reader` non è usato da
   `app` → una notifica XTrader **non** marca alcun segnale CONFIRMED/REJECTED/TIMEOUT
   (richiede un listener sulla chat notifiche + coda dei pending).
3. **`TODO(wiring)` — Multi-chat (PR-12)**: `source_manager`/`source_chats` non letti a
   runtime → chat disattivate e provider/mode per-chat sono **ignorati**.
4. **`TODO(filter)` — Filtro chat aperto di default**: con `chat_id` e `parser_by_chat`
   vuoti, `is_chat_allowed` ammette **tutte** le chat. Mitigazione attuale: la release
   checklist **richiede** un `chat_id` esplicito prima dell'uso (in alternativa, irrigidire
   `is_chat_allowed`/`_start` per esigere una chat).
5. **GUI**: i controller sono testati headless, ma avvio GUI, START/STOP, salvataggio e
   builder del Parser Personalizzato vanno verificati a mano su Windows.
6. **Build EXE**: workflow pronto, build reale non eseguibile qui.
7. **XTrader live**: lettura CSV, segnale verde, conferma Telegram sono passi manuali in
   **simulazione** (vedi `xtrader_simulation_test.md`).

---

## 5. Invarianti di sicurezza

**Attive a runtime (e verificate nei test offline):**
- Nessun segnale invalido raggiunge il CSV (validator + gate nel percorso `resolve_row`).
- **Anti-duplicato + limite/minuto + limite/giorno + DRY_RUN** (PR-21, `live_guard`):
  un duplicato/raffica/over-quota o la simulazione **sopprimono la scrittura**.
- Scrittura/svuotamento CSV atomici; header sempre presente.
- Filtro chat effettivo **quando `chat_id` è configurato** (con config vuota ammette
  tutte — vedi §4 punto 4; la checklist richiede un `chat_id`).
- Nessun token/segreto nei log (redazione) né nel repo (`forbidden-files` + test).
- Contratto CSV invariato dalle PR successive a PR-01 (barriera `contract`).
- Merge sempre **manuale** del proprietario; nessun auto-merge.

**Implementate come logica pura ma NON ancora attive a runtime** (§4): coda
multi-segnale, conferma XTrader, multi-chat provider/mode. **Non vanno considerate
garanzie operative** finché non sono agganciate.

---

## 6. Conclusione

Il progetto soddisfa gli obiettivi della roadmap per una **release candidate da
testare in simulazione**. Prima di qualunque uso reale: eseguire
`release_checklist.md` e `xtrader_simulation_test.md` su Windows con XTrader in
**Modalità Simulazione**, stake basso, limiti chiari. Nessuna promessa di profitto.
