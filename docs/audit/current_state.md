# Stato attuale del progetto — XTrader Signal Bridge

> Documento di baseline (PR-00). Fotografa lo stato del repository **prima**
> di qualsiasi modifica funzionale. Non descrive comportamenti futuri.

**Data baseline:** 2026-06-16
**Verdetto generale:** prototipo funzionante a livello di struttura, **non pronto per la produzione**.

---

## Struttura del repository

```
xtrader-bridge/
├── main.py                      ← intera app: GUI + parser + CSV + Telegram
├── requirements.txt             ← 2 dipendenze runtime
├── README.md                    ← documentazione (parzialmente incoerente col codice)
├── AGENTS.md                    ← regole operative per agenti
├── CLAUDE.md                    ← regole operative per agenti (vincolanti)
├── .gitignore                   ← aggiunto in PR-00 (prima assente)
├── .github/workflows/build.yaml ← build EXE Windows via PyInstaller
└── docs/audit/                  ← documentazione audit (PR-00)
```

Non esistono: cartella `tests/`, `pytest.ini`, `.gitignore` (prima di PR-00),
moduli separati, configurazione linter/formatter/type-checker.

---

## Componenti presenti

| Componente | File / funzione | Stato |
|---|---|---|
| GUI desktop (CustomTkinter) | `App` in `main.py` | Presente |
| Config locale JSON | `_load_config` / `_save_config` | Presente (accanto all'EXE) |
| Listener Telegram | `_run_bot` / `_handle` | Presente |
| Parser segnali P.Bet. | `parse_message()` | Presente, fragile |
| Costruzione riga CSV | `build_csv_row()` | Presente |
| Scrittura/svuotamento CSV | `init_csv()` / `write_csv()` | Presente, non atomico |
| Auto-clear con timeout | `threading.Timer` in `_process` | Presente |
| Build EXE Windows | `.github/workflows/build.yaml` | Presente, non eseguita in questo ambiente |

---

## Comportamento runtime attuale (verificato)

- `python -m py_compile main.py` → **PASS**.
- Header CSV reale generato dal codice (`CSV_HEADER`):
  `Provider, SelectionId, MarketId, SelectionName, MarketName, EventName, MarketType, BetType, Price, MinPrice, MaxPrice`
- Il CSV viene **sempre riscritto** (`open(path, 'w')`) → un solo segnale alla volta.
- Auto-clear dopo `clear_delay` secondi (default 90) → resta solo l'header.
- Il parser estrae i campi **principalmente tramite emoji** (`🏆 🆚 ⚽ ⌚ 📊`);
  su un messaggio testuale come quello del README, `teams`/`competition`/`score`
  restano vuoti.
- Filtro `chat_id`: attivo solo se il campo è valorizzato; se vuoto il bot
  ascolta **tutte** le chat.

---

## Classificazione: prototipo vs produzione

| Aspetto | Prototipo (oggi) | Richiesto per produzione |
|---|---|---|
| Parsing | Solo formato emoji | Emoji + testo |
| CSV | Header non finale | Contratto XTrader fisso |
| Validazione | Assente | Bloccante pre-scrittura |
| Concorrenza | Nessun lock | Scrittura atomica + lock |
| Test | Assenti | Suite pytest in CI |
| Config | Accanto all'EXE | `%APPDATA%` persistente |
| Sicurezza | Token in chiaro nel config | `.gitignore` + niente token nei log |

Il dettaglio dei problemi è in `known_issues.md`. Il piano di chiusura è in `roadmap.md`.
