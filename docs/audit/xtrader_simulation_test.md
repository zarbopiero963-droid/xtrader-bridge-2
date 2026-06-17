# Test end-to-end in simulazione — XTrader Signal Bridge

> PR-20 (PHASE 9). Procedura **manuale** per verificare la catena completa
> Telegram → bridge → CSV → XTrader → conferma, con XTrader in **Modalità
> Simulazione**. Questi passi NON sono eseguibili in ambiente headless: vanno
> svolti dal proprietario su Windows. Stake basso, limiti chiari, nessuna
> promessa di profitto.

## 0. Premesse di sicurezza

> **DRY_RUN ora è agganciato (PR-21).** In DRY_RUN il bridge riconosce il segnale ma
> **NON scrive** il CSV operativo (lo dichiara nel log). Resta comunque buona prassi
> tenere XTrader in **Modalità Simulazione** durante il collaudo.

- XTrader in **Modalità Simulazione** (mai reale durante il collaudo).
- Bridge in **DRY_RUN** in config: con PR-21 questo **sopprime davvero** la scrittura.
  Passare a modalità reale solo consapevolmente, con stake minimo.
- Usare un bot Telegram e una chat **di test**, non quelli di produzione.

> **Cosa è agganciato al runtime oggi** (vedi `final_audit.md` §4). **Attivi:** filtro
> chat (solo con `chat_id` configurato), parsing+validazione, **anti-duplicato +
> limite/minuto + limite/giorno + DRY_RUN** (PR-21), **coda multi-segnale** (PR-22),
> **conferma XTrader** (PR-23), scrittura/svuotamento CSV. **NON ancora agganciato**
> (logica pura testata): **multi-chat** provider/mode — passi marcati `TODO(wiring)`.

## 1. Setup

1. Avvia l'EXE (o `python main.py` in dev).
2. Configura: token bot di test, `chat_id` della chat sorgente di test, percorso
   CSV concordato con XTrader, timeout di auto-clear.
3. Verifica che la config sia salvata in `%APPDATA%\XTraderBridge\config.json`.
4. In XTrader: configura la fonte "Segnali" a leggere lo stesso CSV, lingua
   **italiana** (per il match NAME_ONLY), Modalità Simulazione.

## 2. Caso A — segnale valido (happy path)

> **Nota DRY_RUN (PR-21).** Il test di scrittura+XTrader (A1) va eseguito con **DRY_RUN
> disattivato** (`dry_run=false`); lo smoke A2 verifica che con DRY_RUN attivo il CSV
> **non** venga scritto — ora è davvero agganciato.

### A1 — scrittura + lettura XTrader (DRY_RUN OFF, XTrader in Simulazione)
1. Avvia il bridge (START). Verifica nel log "⚠️ Modalità REALE".
2. Invia nella chat di test un messaggio P.Bet. valido, oppure coerente col Parser
   Personalizzato attivo.
3. **Atteso nel bridge:** segnale riconosciuto, validato, scritto nel CSV.
4. **Atteso nel CSV:** header a 14 colonne + **una** riga; `BetType` PUNTA/BANCA;
   `Handicap`=0; `Points` vuoto; encoding `utf-8-sig`.
5. **Atteso in XTrader:** la fonte Segnali legge il CSV; segnale valido (verde) secondo
   `MarketId+SelectionId` o `EventName+MarketType+SelectionName`.

### A2 — smoke DRY_RUN (ora attivo, PR-21)
1. Con `dry_run` attivo (default), avvia: il log mostra "🧪 DRY_RUN attivo". Invia un
   segnale valido.
2. **Atteso:** log "🧪 DRY_RUN: segnale riconosciuto ma CSV NON scritto"; il CSV operativo
   resta **invariato** (nessuna riga). L'ultimo segnale è comunque mostrato in GUI.

## 3. Caso B — segnale invalido (deve essere scartato)

1. Invia un messaggio senza quota / con quota ≤ 1.0 / senza squadre.
2. **Atteso:** nessuna riga scritta; motivo dello scarto a log; CSV invariato.

## 4. Caso C — chat non autorizzata (deve essere ignorata)

> **Pre-requisito:** in config deve esserci un `chat_id` esplicito (o un override
> `parser_by_chat`). Con config vuota il filtro ammette **tutte** le chat (vedi
> `final_audit.md` §4 punto 6) e questo caso non è valido.

1. Con un `chat_id` configurato, invia un messaggio da una chat **diversa**.
2. **Atteso:** messaggio ignorato; nessuna scrittura; log coerente.

## 5. Caso D — svuotamento (auto-clear)

1. Dopo un segnale valido, attendi il timeout configurato.
2. **Atteso:** il CSV viene svuotato lasciando **solo l'header** (nessun vecchio
   segnale residuo).

## 6. Caso E — duplicati e raffica (ora attivo, PR-21)

> Eseguire con **DRY_RUN OFF** per osservare la soppressione della scrittura
> (`live_guard` aggancia dedup + limite/minuto + limite/giorno a `app._process`).

1. Invia due volte lo **stesso** messaggio ravvicinato.
2. **Atteso:** il secondo è riconosciuto come duplicato — log "♻️ Duplicato ignorato";
   **nessuna seconda riga** scritta.
3. Invia molti segnali in poco tempo.
4. **Atteso:** oltre il limite/minuto → log "🚦 Limite al minuto raggiunto"; oltre
   `max_per_day` → log "🚦 Limite giornaliero raggiunto". I segnali in eccesso non scrivono.

## 7. Caso F — conferma XTrader (ora attivo, PR-23)

> Richiede `xtrader_notification_chat_id` configurato (chat **separata** dalle sorgenti).

1. Con XTrader configurato per notificare l'esito su quella chat, lascia che XTrader
   elabori un segnale attivo in simulazione e invii la notifica.
2. **Atteso:** il bridge interpreta la notifica; su **CONFIRMED** o **REJECTED** rimuove
   il segnale dalla coda → la sua riga sparisce dal CSV (log "✅ XTrader: segnale
   confermato/rifiutato → rimosso dal CSV"). Una notifica non associata (UNMATCHED) o
   senza esito chiaro (UNKNOWN) è solo loggata, **nessuna** riga toccata. La conferma
   **non** genera una nuova scommessa. (Il TIMEOUT senza conferma è coperto dalla
   scadenza per-segnale della coda.)

## 8. Caso G — riavvio

1. Riavvia il bridge e l'EXE.
2. **Atteso:** la config persiste; nessun thread/polling incoerente dopo STOP/chiusura.
   Con PR-21 lo stato anti-duplicato è persistito in `%APPDATA%\XTraderBridge\
   dedupe_state.json`, quindi un duplicato recente resta riconosciuto anche dopo il riavvio.

## 9. Esito

- [ ] Casi **attivi** con esito atteso: A1, A2, B, C (con `chat_id`), D, E, F
      (con `xtrader_notification_chat_id`), G.
- [ ] Multi-chat provider/mode resta `TODO(wiring)` (PR-24): non ancora verificabile.
- [ ] Nessun token nei log; nessun CSV corrotto/parziale; header sempre presente.
- [ ] Registrare versione testata, data, ambiente (Windows/XTrader) e note.

> Se un caso fallisce, NON passare alla modalità reale: annota il comportamento,
> apri un'issue e correggi prima di rilasciare.
