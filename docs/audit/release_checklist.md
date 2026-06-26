# Checklist di release — XTrader Signal Bridge

> PR-20 (PHASE 9). Passi da eseguire **prima** di distribuire una versione. Il merge
> e la pubblicazione restano **manuali del proprietario**. Spunta ogni voce solo dopo
> averla verificata davvero.

## A. Pre-requisiti (ambiente di sviluppo)

- [ ] Branch pulito, allineato a `main`, nessun file fuori scope.
- [ ] Nessun segreto nello staging: niente `config.json` reale, token, chat ID reali,
      `.env`, CSV generati, log, EXE/ZIP (vedi `.gitignore`).

## B. Test automatici (offline)

- [ ] `python -m py_compile main.py` → OK.
- [ ] `python -m pytest -m "not manual"` → tutti verdi (atteso: 536 passed, 2 skipped
      o più, mai fallimenti).
- [ ] Il job CI `contract` è verde (contratto CSV a 14 colonne invariato).
- [ ] Tutti i check della PR sono **completati e verdi** prima del merge.

## C. Versione e changelog

- [ ] `xtrader_bridge.__version__` aggiornato secondo semver (oggi `0.1.0`).
- [ ] Il titolo della GUI mostra la versione corretta.
- [ ] README allineato al comportamento reale e al workflow (`build.yaml`).

## D. Build EXE Windows (manuale / CI Windows)

> Non eseguibile in ambiente headless. Eseguire su Windows o tramite il workflow
> `build.yaml` (push su `main` o tag `v*`).

- [ ] Il workflow `build.yaml` completa senza errori.
- [ ] L'artifact versionato `XTrader-Signal-Bridge-Windows-v<versione>-<data>.zip`
      è presente e scaricabile.
- [ ] L'EXE interno si chiama `XTrader-Signal-Bridge.exe` (nome stabile).
- [ ] L'EXE si avvia su Windows 10/11 senza terminale nero (`--windowed`).
- [ ] L'EXE **non** contiene token o config personali.
- [ ] L'EXE salva la config in `%APPDATA%\XTraderBridge\` e la ricarica al riavvio.
- [ ] L'EXE scrive il CSV nel percorso configurato.

## E. Sicurezza

- [ ] Tutte le GitHub Action nei workflow sono fissate a SHA (test di enforcement verde).
- [ ] Nessun token Telegram compare nei log (redazione attiva).
- [ ] **`chat_id` esplicito configurato** prima dell'uso: senza, il filtro chat ammette
      tutte le chat (vedi `final_audit.md` §4 punto 6). Requisito bloccante per l'uso reale.
- [ ] DRY_RUN (default = simulazione) **agganciato al runtime (PR-21)**: verifica che in
      DRY_RUN il CSV operativo NON venga scritto (log "🧪 DRY_RUN"). Per l'uso reale,
      disattivarlo consapevolmente.
- [ ] **Attive a runtime (PR-21):** anti-duplicato + limite/minuto (`signal_dedupe`,
      stato persistito) e limite/giorno (`safety_guard`, `max_per_day`). Verifica i log
      "♻️ Duplicato"/"🚦 Limite ...".
- [ ] **Protezioni NON ancora attive a runtime** (da agganciare prima dell'uso reale):
      coda multi-segnale (`signal_queue`), conferma XTrader (`confirmation_reader`),
      multi-chat (`source_manager`). Vedi `final_audit.md` §4.

## F. Verifica funzionale manuale (Windows + GUI)

- [ ] App avviabile; START/STOP funzionano; chiusura finestra ferma il bridge.
- [ ] Salvataggio config dalla GUI funziona e persiste.
- [ ] Log leggibile; errori parser/CSV visibili; nessun token mostrato.

## G. Simulazione XTrader

- [ ] Eseguita la procedura `xtrader_simulation_test.md` con XTrader in **Modalità
      Simulazione**, stake basso, limiti chiari. Esito atteso raggiunto.

## I. Disaster recovery / resilienza (#109 · #110) — manuale Windows

Passi **manuali** non automatizzabili in CI, riferiti dalla matrice
`resilience_110_matrix.md` (voci 16-19). **Attenzione alla modalità**: in **DRY_RUN**
il CSV operativo NON viene scritto (`live_guard` → `DRY_RUN`), quindi gli scenari che
devono produrre una riga attiva (power-cut, XTrader) vanno eseguiti in **modalità REALE
con XTrader in *Modalità Simulazione*** e stake basso/limiti chiari; gli scenari di sola
rete/auto-start possono restare in DRY_RUN.

- [ ] **#110/17 — Power-cut con CSV attivo.** *(modalità REALE + XTrader in Simulazione,
      stake basso — in DRY_RUN il CSV non verrebbe scritto e lo scenario non sarebbe
      esercitato.)* Fai scrivere un segnale nel CSV, poi spegni brutalmente VM/PC (o
      `kill -9`). Riapri l'app. Atteso: CSV a **solo header** PRIMA di START (nessuna riga
      orfana); il log segnala il cleanup all'avvio. **Dedupe/daily dopo il crash sono
      best-effort**: il duplicato recente è riconosciuto e il daily count è preservato
      **solo se lo stato guard era stato persistito prima del crash**; un crash nella
      finestra stretta "write CSV riuscita → prima di `_save_guard_state`" può far
      dimenticare quel segnale (vedi `resilience_110_matrix.md` #110/10) — è un fail-safe
      accettato, non una garanzia di "exactly-once". Per un check deterministico del
      dedupe, fai prima arrivare un 2° segnale (così lo stato viene salvato) e poi togli
      la corrente.
- [ ] **#110/15 — START con CSV lockato (file-lock).** *(modalità REALE o DRY_RUN: serve
      solo che `init_csv` non possa scrivere.)* Apri il CSV in Excel/XTrader in modo
      **lockante** (o togli i permessi di scrittura), poi premi **AVVIA**. Atteso: l'avvio
      **fallisce in modo pulito** (log con l'errore di `init_csv`), lo stato resta
      **OFFLINE** e il listener NON parte (nessuna sessione "attiva" falsa). Se il lock
      arriva a runtime, il log segnala l'errore e l'auto-clear riprova (retry).
- [ ] **#110/18 — Telegram live outage / reconnect.** *(DRY_RUN va bene: non serve
      scrivere il CSV.)* Avvia il listener, stacca la rete ~5 min e invia segnali nel
      canale mentre è offline; riattacca la rete. Atteso: stato **RICONNESSIONE…** con
      backoff. Nota: a ogni riconnessione il polling usa `drop_pending_updates=True`,
      quindi **l'intero backlog accumulato offline viene SCARTATO** (non filtrato per età):
      i messaggi inviati mentre la rete era giù **non** vengono processati. Solo i
      messaggi inviati **dopo** la riconnessione (e comunque entro `max_signal_age`)
      passano.
- [ ] **#110/16 — Windows reboot + auto-start.** Configura l'app in Startup
      folder / Task Scheduler con `auto_start_listener=true`. Caso **DRY_RUN**:
      riavvia il PC → l'app parte, il listener parte da solo, il CSV è pulito.
      Caso **REALE**: riavvia → l'app parte e **chiede conferma**; senza click non
      scrive nulla.
- [ ] **#110/19 — XTrader sandbox (lettura singola).** *(modalità REALE + XTrader in
      *Modalità Simulazione*, stake basso: serve una riga reale nel CSV perché XTrader la
      legga.)* Refresh automatico attivo, CSV path reale. Fai arrivare un segnale valido:
      XTrader lo legge **una sola volta**; allo scadere del timeout il CSV torna a solo
      header; riavviando XTrader non rilegge segnali vecchi; il file non resta lockato.

## H. Rilascio

- [ ] Tag `v<versione>` creato (la release pubblica parte solo su tag).
- [ ] Note di release scritte (cosa cambia, limiti noti, avviso simulazione).
- [ ] Merge eseguito **manualmente** dal proprietario.

> Promemoria: nessuna promessa di profitto. Prima dell'uso reale, sempre simulazione,
> stake basso, limiti chiari, consapevolezza del rischio.
