# XTrader Signal Bridge

> **Ponte automatico tra i segnali Telegram e XTrader: legge i messaggi di una
> chat/canale, scrive il CSV nel formato esatto richiesto da XTrader e lo svuota
> dopo il timeout — così XTrader può piazzare le scommesse da solo.**

---

## Indice

- [Cos'è](#cosè)
- [Come funziona — flusso completo](#come-funziona--flusso-completo)
- [Guida rapida (5 passi)](#guida-rapida-5-passi)
- [Configurazione dalla GUI](#configurazione-dalla-gui)
- [Configurazione avanzata (`config.json`)](#configurazione-avanzata-configjson)
- [Più chat sorgenti (multi-chat)](#più-chat-sorgenti-multi-chat)
- [Parser Personalizzato](#parser-personalizzato)
- [Conferma da XTrader](#conferma-da-xtrader)
- [Sicurezza: simulazione, duplicati e limiti](#sicurezza-simulazione-duplicati-e-limiti)
- [Formato CSV generato](#formato-csv-generato)
- [Dove vengono salvati i file](#dove-vengono-salvati-i-file)
- [Avvio automatico con Windows](#avvio-automatico-con-windows)
- [Domande frequenti](#domande-frequenti)
- [Build dell'EXE (sviluppatori)](#build-dellexe-sviluppatori)
- [Struttura del progetto](#struttura-del-progetto)

---

## Cos'è

XTrader Signal Bridge è un programma desktop (Windows) che fa da **ponte** tra i
messaggi di una chat/canale Telegram e il software **XTrader** di TradingSportivo.

Catena di funzionamento:

```text
Telegram corretto → parsing corretto → CSV corretto → XTrader legge → CSV pulito
```

Il bridge **non piazza scommesse da solo**: si limita a scrivere il CSV che XTrader
monitora. È XTrader a piazzare la scommessa. Per sicurezza, di default il bridge
parte in **modalità simulazione** (`dry_run`), in cui riconosce i segnali ma **non**
scrive il CSV operativo (vedi [Sicurezza](#sicurezza-simulazione-duplicati-e-limiti)).

---

## Come funziona — flusso completo

```text
Messaggio Telegram (chat/canale segnali)
        │
        ▼
XTrader Signal Bridge (gira sul tuo PC)
   • riceve il messaggio via Bot API (solo dalle chat configurate)
   • lo analizza: parser hardcoded P.Bet. o Parser Personalizzato
   • estrae i campi e li traduce nei valori XTrader (dizionario)
   • valida (quota, mercato, tipo scommessa)
        │
        ▼
segnali.csv  ←── XTrader monitora questo file (14 colonne, formato XTrader)
        │
        ▼
XTrader legge il CSV e piazza la scommessa (se non è in simulazione)
        │
        ▼
dopo N secondi (timeout configurabile, default 90s) il CSV viene svuotato
        │
        ▼
CSV con solo l'header → pronto per il prossimo segnale
```

> **Recupero dopo crash/blackout:** il CSV viene riportato a **solo header** anche
> allo STOP/chiusura dell'app **e all'avvio** dell'app. Così, se il PC si spegne di
> colpo mentre nel CSV c'è una riga attiva (il timer di auto-clear non può girare),
> alla riapertura dell'app — prima ancora di premere AVVIA — il segnale orfano della
> sessione morta viene rimosso e XTrader non lo rilegge.

---

## Guida rapida (5 passi)

### Passo 1 — Crea il bot Telegram
1. Apri Telegram e cerca **@BotFather**.
2. Scrivi `/newbot` e segui le istruzioni.
3. Copia il **token** (es. `123456789:AAFxxx...`).

### Passo 2 — Aggiungi il bot alla chat dei segnali
Aggiungi il bot come **amministratore** (basta il permesso di lettura dei messaggi)
nella chat/canale dove arrivano i segnali.

### Passo 3 — Trova il Chat ID
Apri nel browser (sostituendo il tuo token):

```text
https://api.telegram.org/bot<TUO_TOKEN>/getUpdates
```

Cerca il numero dopo `"chat":{"id":` — è il tuo Chat ID (per i canali è negativo,
es. `-1001234567890`).

### Passo 4 — Configura XTrader
In XTrader, nella sezione **Segnali**, imposta come sorgente lo stesso file CSV
(es. `C:\XTrader\segnali.csv`) e abilita il **refresh automatico** (consigliato
ogni 10–15 secondi). Per il collaudo, tieni XTrader in **Modalità Simulazione**.

### Passo 5 — Avvia il bridge
1. Apri `XTrader-Signal-Bridge.exe`.
2. Inserisci **Bot Token**, **Chat ID** e **CSV Path**.
3. Clicca **💾 Salva Config**, poi **▶ AVVIA**.

> ⚠️ Il bridge **non parte** se non hai configurato almeno una chat/sorgente
> (Chat ID, parser per-chat o una sorgente multi-chat): senza, accetterebbe segnali
> da qualsiasi chat. È una protezione voluta.
>
> 🧪 Di default il bridge è in **simulazione** (`dry_run=true`): riconosce i
> segnali ma **non** scrive il CSV. Per l'uso reale vedi
> [Sicurezza](#sicurezza-simulazione-duplicati-e-limiti).

---

## Configurazione dalla GUI

La finestra principale espone i campi essenziali. Si salvano con **💾 Salva Config**
(oppure all'avvio con **▶ AVVIA**) nel file `config.json` (vedi
[Dove vengono salvati i file](#dove-vengono-salvati-i-file)).

| Campo GUI | Chiave config | Default | A cosa serve |
|---|---|---|---|
| 🔑 **Bot Token** | `bot_token` | *(vuoto)* | Token del bot Telegram (@BotFather). Senza, START è bloccato. Mai mostrato nei log. |
| 💬 **Chat ID** | `chat_id` | *(vuoto)* | ID della chat/canale sorgente. Definisce quali messaggi vengono accettati. |
| 📄 **CSV Path** | `csv_path` | `C:\XTrader\segnali.csv` | File CSV che XTrader monitora. Obbligatorio. |
| ⏱️ **Timeout (sec)** | `clear_delay` | `90` | Dopo quanti secondi un segnale scade e il CSV viene svuotato. Deve essere un intero > 0. |
| 🏷️ **Provider** | `provider` | `TelegramBot` | Etichetta scritta nella colonna `Provider` del CSV (vedi nota sotto). |

Pulsanti aggiuntivi:

- **🗑️ Svuota CSV ora** — riporta subito il CSV al solo header.
- **🧩 Parser Personalizzato** — apre il costruttore di parser (vedi
  [Parser Personalizzato](#parser-personalizzato)).

> **Nota sul Provider:** per una **chat sorgente multi-chat** il Provider può essere
> deciso dalla sorgente (esplicito, oppure derivato dalla modalità: `PRE → TG_PRE`,
> `LIVE → TG_LIVE`) e in quel caso **ha la precedenza** sul Provider globale e su un
> eventuale valore fisso del parser custom. Per le chat senza sorgente vale il
> Provider globale qui sopra. Vedi [Più chat sorgenti](#più-chat-sorgenti-multi-chat).

---

## Configurazione avanzata (`config.json`)

Queste impostazioni vivono in `config.json` (`%APPDATA%\XTraderBridge\config.json`).
**Diverse sono ora modificabili anche dalla GUI**, nelle tab *Riconoscimento /
Sicurezza / Conferme XTrader*: `recognition_mode`, `dry_run`,
`max_per_day`, `queue_mode`, `xtrader_notification_chat_id`, `confirmation_timeout`,
`confirmation_keywords`, `rejection_keywords`. La **quota obbligatoria** sì/no NON è
più un interruttore globale: la comanda la casella **«Obblig.» sulla riga `Price`** di
ogni Parser Personalizzato. Le **chat sorgente**
(`source_chats`) **e** l'override parser per chat (`parser_by_chat`) si modificano dal
pulsante **"📡 Chat sorgenti"** (vedi [Più chat sorgenti](#più-chat-sorgenti-multi-chat)).
Nella tab *Conferme XTrader* le parole chiave si scrivono **separate da virgola**
(es. `piazzata, ok, matchata`); il campo vuoto lascia i default del modulo. La sola
chiave `active_parser` si imposta di norma dalla GUI del Parser Personalizzato. Ogni
chiave è comunque **preservata** quando salvi dalla GUI, quindi non si perde.

| Chiave | Default | Valori | A cosa serve |
|---|---|---|---|
| `recognition_mode` | `NAME_ONLY` | `ID_ONLY`, `NAME_ONLY`, `BOTH` | Come XTrader riconosce il segnale. Oggi gli ID non arrivano dal messaggio Telegram, quindi `NAME_ONLY` (nomi) è il default. `ID_ONLY` richiede `MarketId`/`SelectionId`; `BOTH` entrambi. |
| *(quota obbligatoria)* | — | — | NON è più una chiave globale: la comanda la casella **«Obblig.» sulla riga `Price`** di ogni Parser Personalizzato. `Price` obbligatorio → segnale senza quota valida (> 1.0) **scartato**; non obbligatorio → quota opzionale. |
| `dry_run` | `true` | `true`/`false` | **Simulazione**: se `true`, il CSV operativo **non** viene scritto. Mettilo a `false` solo per l'uso reale, consapevolmente. |
| `max_per_day` | `200` | intero | Tetto di segnali nuovi accettati in un giorno (UTC). Oltre, i segnali in eccesso non scrivono. |
| `queue_mode` | `OVERWRITE_LAST` | `OVERWRITE_LAST`, `APPEND_ACTIVE`, `QUEUE_UNTIL_CONFIRMED` | Quanti segnali attivi tenere nel CSV. `OVERWRITE_LAST` = uno solo (sicuro). Le altre due scrivono **più righe** = più scommesse simultanee. |
| `active_parser` | `""` | nome parser | Parser Personalizzato attivo **globalmente**. Di norma si imposta dalla GUI. **`""` (vuoto) = nessun parser custom globale.** Una chat con un parser **dedicato** in `parser_by_chat` funziona comunque; una chat **senza** né `active_parser` né voce in `parser_by_chat` viene **IGNORATA** in live (il parser hardcoded P.Bet **non** gira live, vedi nota sotto). |
| `parser_by_chat` | `{}` | `{chat_id: nome_parser}` | Override del parser per singola chat. Modificabile dal pulsante **"📡 Chat sorgenti"** (colonna Parser di ogni sorgente). |
| `source_chats` | `[]` | lista | Più chat sorgente (vedi sotto). |
| `xtrader_notification_chat_id` | `""` | chat id | Chat **separata** su cui XTrader notifica l'esito (vedi [Conferma da XTrader](#conferma-da-xtrader)). |
| `confirmation_timeout` | `120` | secondi | **In `QUEUE_UNTIL_CONFIRMED`**: per quanti secondi un segnale resta in attesa della conferma XTrader prima di scadere (timeout per-segnale della coda). Nelle altre modalità coda non si applica: vale `clear_delay`. |
| `max_signal_age` | `120` | secondi | Un messaggio Telegram più vecchio di così viene **ignorato** all'arrivo (anti-segnale-stantio: evita che gli arretrati rifetchati dopo una disconnessione diventino scommesse vecchie). `0` = filtro disattivato. |
| `auto_start_listener` | `false` | `true`/`false` | Se `true`, all'apertura l'app **avvia da sola** il listener — ma solo se token e chat sono configurati; in **modalità reale** chiede conferma prima di partire. Default `false`: il bridge parte solo con **AVVIA**. Attivabile dalla tab *Sicurezza*. |
| `confirmation_keywords` | `[]` | lista | Parole che indicano conferma (vuoto = default del modulo). Dalla GUI: stringa separata da virgola. |
| `rejection_keywords` | `[]` | lista | Parole che indicano rifiuto (vuoto = default del modulo). Dalla GUI: stringa separata da virgola. |
| `log_retention_days` | `0` | `0`/`5`/`15`/`30`… | Giorni di conservazione dei log: oltre il limite i file `bridge-AAAA-MM-GG.log` più vecchi vengono **cancellati** all'avvio del bridge (e quando cambi l'opzione). `0` = "Mai" (conserva tutto). Dalla tab *Log*: tendina **Conserva** + pulsante **🧹 Svuota log**. |
| `debug_log` | `false` | `true`/`false` | Modalità **Debug**: log dettagliato del percorso (avvio/stop, salvataggi, messaggio in ingresso, stadi del segnale) + warning, per capire "cosa è rotto". Attivabile dalla tab *Log* (checkbox **🐞 Debug**). |
| `debug_message_payload` | `false` | `true`/`false` | **Privacy dei log.** Se `false` (default) il **testo** dei messaggi Telegram **non** viene scritto in chiaro nei log: solo impronta (`sha256` a 12 cifre) + lunghezza + **prima riga troncata**. Se `true`, logga il **payload completo** (debug consapevole). Attivabile dalla tab *Sicurezza* (checkbox **🕵️**). I token restano comunque sempre redatti. |
| `providers` | `[]` | lista di nomi | **Anagrafica Provider**: nomi riutilizzabili nella colonna `Provider` del Parser Personalizzato (menu a tendina). Si gestisce dal pulsante **➕ Provider** nel costruttore; evita errori di battitura sul Provider (che deve combaciare col filtro dell'azione XTrader). |

> Una `config.json` corrotta viene messa da parte come `.bak` e il bridge riparte
> dai default sicuri. Le chiavi mancanti ereditano sempre il default.

---

## Più chat sorgenti (multi-chat)

Per ricevere segnali da **più chat/canali**, usa il pulsante **"📡 Chat sorgenti"**
nella finestra principale: aggiungi/rimuovi righe e imposta per ciascuna nome,
chat_id, attiva, modalità PRE/LIVE, provider e — colonna **Parser** — un Parser
Personalizzato dedicato per quella chat (salvato in `parser_by_chat`). In alternativa
valorizza a mano `source_chats` in `config.json`. È una lista di oggetti:

```json
{
  "source_chats": [
    { "name": "Canale PRE",  "chat_id": "-1001111111111", "enabled": true,  "mode": "PRE",  "provider": "" },
    { "name": "Canale LIVE", "chat_id": "-1002222222222", "enabled": true,  "mode": "LIVE", "provider": "" },
    { "name": "Vecchio",     "chat_id": "-1003333333333", "enabled": false, "mode": "PRE",  "provider": "TG_VIP" }
  ]
}
```

Regole:

- **`mode`** ∈ `PRE` / `LIVE`. Determina il Provider di default: `PRE → TG_PRE`,
  `LIVE → TG_LIVE`.
- **`provider`** esplicito (se valorizzato) **vince** sulla modalità ed è testo
  libero: puoi crearne quanti vuoi (es. `TG_VIP`, `TG_GOLD`).
- **`enabled: false`** → la sorgente è **ignorata** (deny-list): quella chat non
  scrive, anche se compare altrove.
- **`chat_id` duplicato** tra due sorgenti = errore bloccante all'avvio (il Provider
  sarebbe ambiguo). **Nome** duplicato = solo avviso.
- Le chat in `source_chats` attive sono **ammesse** in aggiunta a `chat_id`/
  `parser_by_chat`. Una sorgente disattivata resta esclusa.

---

## Parser Personalizzato

Oltre al parser integrato per il formato **P.Bet.**, puoi definire dalla GUI **come**
estrarre ogni colonna del CSV da un messaggio, **senza toccare il codice**. Apri
**🧩 Parser Personalizzato**.

In breve, ogni colonna ha una **regola** con:

- **"Inizia dopo"** / **"Finisce prima"**: i delimitatori di testo (tolleranti agli
  spazi) che racchiudono il valore;
- **valore fisso** (alternativo all'estrazione);
- **trasformazione** opzionale (es. somma-gol → linea Over);
- **value-map** opzionale (traduce alias come `GG`/`OVER 2.5` nei valori XTrader, e
  `BACK`/`LAY` in `PUNTA`/`BANCA`);
- **obbligatorio**: se vuoto, il parser è **"Non pronto"** → **nessuna** riga CSV.

Quando un Parser Personalizzato è attivo per una chat è **autoritativo** (niente
fallback all'hardcoded). I parser si salvano/condividono come file in
`data/parsers/<nome>.json`. Guida completa: **[`docs/custom_parser.md`](docs/custom_parser.md)**.

> ⚠️ **Il parser integrato P.Bet è solo per compatibilità/test, NON è attivo nel live.** Nel
> percorso live (`signal_router`, CP-09b), se per una chat **non** c'è un Parser
> Personalizzato attivo, il messaggio viene **ignorato** (nessuna riga CSV) — il parser
> hardcoded `parse_message` **non** entra in gioco. Resta nel repo (e nei test) solo per
> retro-compatibilità: **per processare segnali live serve sempre un Parser Personalizzato
> attivo** sulla chat sorgente.

---

## Conferma da XTrader

Se XTrader può **notificare l'esito** del piazzamento su una chat Telegram, il bridge
può leggerla e togliere dal CSV il segnale confermato/rifiutato.

- Imposta `xtrader_notification_chat_id` su una chat **diversa** dalle sorgenti
  (se coincide con una sorgente, l'avvio viene bloccato per evitare di scambiare un
  segnale per una conferma).
- Su **CONFIRMED** o **REJECTED** il segnale viene rimosso dalla coda e dal CSV.
- Una notifica non associabile o ambigua viene solo loggata; la conferma **non**
  genera mai una nuova scommessa.
- `confirmation_keywords`, `rejection_keywords` regolano l'interpretazione delle
  notifiche; `confirmation_timeout` è il timeout del segnale in `QUEUE_UNTIL_CONFIRMED`
  (vedi tabella della configurazione avanzata).
- La **chat-notifiche** (`xtrader_notification_chat_id`), `confirmation_keywords` e
  `rejection_keywords` sono lette dalla **config viva**: modificarle e salvarle ha effetto
  **subito**, senza Stop/Start (come il routing). Restano invece legati alla sessione — e
  richiedono un riavvio — i parametri di **esecuzione** (`dry_run`, limiti, `csv_path`,
  token), per non far scattare per sbaglio una scommessa reale o un CSV stantio a metà
  sessione.

---

## Sicurezza: simulazione, duplicati e limiti

Tutte queste protezioni sono **attive a runtime**:

1. **Simulazione (`dry_run`)** — di default `true`: i segnali vengono riconosciuti
   ma il CSV operativo **non** viene scritto. Il log lo dichiara
   (`🧪 DRY_RUN attivo`). Per l'uso reale metti `dry_run=false`: il log mostrerà
   `⚠️ Modalità REALE`.
2. **Filtro chat obbligatorio** — il bridge non parte senza almeno una chat/sorgente
   configurata, così non accetta segnali da chat arbitrarie.
3. **Un segnale alla volta** — con `queue_mode=OVERWRITE_LAST` il CSV contiene un
   solo segnale attivo; il timeout lo svuota.
4. **Anti-duplicato** — lo stesso messaggio ravvicinato non viene riscritto. Lo
   stato persiste in `dedupe_state.json`, quindi i duplicati recenti restano
   riconosciuti anche dopo un riavvio.
5. **Limite al minuto e al giorno** — oltre soglia i segnali in eccesso non scrivono
   (`max_per_day` per il giorno).
6. **Scrittura atomica** — il CSV si scrive su file temporaneo e poi `rename`, così
   XTrader non legge mai un file parziale; l'header è sempre presente.
7. **Nessun token nei log** — i segreti sono redatti sia a schermo sia su file.
8. **Privacy del contenuto messaggi** — di default il **testo** dei messaggi Telegram
   **non** viene scritto in chiaro nei log: solo impronta (`sha256`) + lunghezza + prima
   riga troncata, abbastanza per diagnosticare senza conservare il contenuto di canali
   privati. Per il debug puoi attivare `debug_message_payload` (tab *Sicurezza*) e loggare
   il payload completo — è una scelta consapevole.

> 🔑 **Dove sta il Bot Token (e perché).** Il token è salvato **in chiaro** in
> `%APPDATA%\XTraderBridge\config.json`, nel profilo del **tuo** utente Windows. È una
> scelta consapevole (tradeoff accettato, audit A6): nessun "vault"/cifratura, ma il
> file **non** è nel repository (è in `.gitignore`), **non** finisce nei log (redazione
> attiva) e **non** è incluso nell'EXE/artifact. Conseguenze pratiche: proteggi il tuo
> profilo Windows e **non condividere** `config.json`; se il token trapela, **rigeneralo**
> da @BotFather (`/revoke`).

> Prima dell'uso reale, segui la procedura **`docs/audit/xtrader_simulation_test.md`**
> con XTrader in Modalità Simulazione, stake basso e limiti chiari. Nessuna promessa
> di profitto.

---

## Formato CSV generato

Header ufficiale a **14 colonne** (vedi **[`docs/xtrader_csv_contract.md`](docs/xtrader_csv_contract.md)**):

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
"TelegramBot","","Inter v Milan","","Over/Under 2,5 gol","OVER_UNDER_25","","Over 2,5 goal","0","1.85","","","PUNTA",""
```

Note:

- **`BetType`** è in italiano: **`PUNTA`** (back) o **`BANCA`** (lay).
- **`Stake`** **non** è una colonna del CSV: lo stake è gestito in XTrader.
- **Non esiste** una colonna `Timestamp`: la deduplica è interna al bridge.
- **`Points`** è lasciato vuoto; **`Handicap`** vale `0`.
- Encoding **UTF-8 con BOM**, tutti i valori tra virgolette (`QUOTE_ALL`).
- XTrader valida con `MarketId + SelectionId` **oppure** `EventName + MarketType +
  SelectionName`. Usando i nomi, la lingua del CSV deve coincidere con quella della
  fonte Segnali di XTrader. Gli ID non arrivano dal messaggio Telegram, quindi oggi
  restano vuoti (`recognition_mode=NAME_ONLY`).

---

## Dove vengono salvati i file

Su Windows tutto vive nella cartella utente persistente (sopravvive a spostamenti e
aggiornamenti dell'EXE):

| File | Percorso | Contenuto |
|---|---|---|
| Configurazione | `%APPDATA%\XTraderBridge\config.json` | Tutte le impostazioni |
| Log giornalieri | `%APPDATA%\XTraderBridge\logs\bridge-AAAA-MM-GG.log` | Storico (senza token) |
| Stato anti-duplicato | `%APPDATA%\XTraderBridge\dedupe_state.json` | Hash dei segnali recenti |
| Stato limite giornaliero | `%APPDATA%\XTraderBridge\daily_state.json` | Contatori del giorno |
| Parser Personalizzati | `data\parsers\<nome>.json` | Definizioni dei parser |

> Al primo avvio, un vecchio `config.json` accanto all'EXE viene **migrato**
> automaticamente nella nuova posizione (l'originale non viene cancellato).
> Su Linux/macOS (dev/CI) si usa `~/.config/XTraderBridge/`.

---

## Avvio automatico con Windows

Vuoi che il bridge **riparta da solo dopo un riavvio del PC** (es. dopo un blackout)?
Il bridge **non** si registra da solo all'avvio di Windows (scelta voluta: niente
modifiche di sistema a sorpresa). Lo configuri **a mano** in pochi secondi, con uno
dei due metodi qui sotto. Poi, per far partire **anche l'ascolto** senza premere
AVVIA, abbina l'opzione **`auto_start_listener`** (tab *Sicurezza*).

> ⚠️ **Sicurezza — auto-start e modalità reale:** in **modalità reale** (DRY_RUN
> disattivato) l'avvio automatico del listener chiede **sempre una conferma**
> (finestra Sì/No) a **ogni** apertura, prima di iniziare a scrivere segnali. Quindi
> in modalità reale **non è davvero "non presidiato"**: dopo un riavvio del PC l'app
> si apre, ma resta **in attesa che qualcuno confermi** — non riparte a scrivere da
> sola. Importante: il bridge **non sa** se XTrader è in simulazione; la conferma
> dipende dal **suo** DRY_RUN, non da quello di XTrader. L'unico avvio davvero
> automatico (senza conferma) è con **DRY_RUN del bridge attivo** — ma in quel caso il
> bridge **non scrive il CSV** (è il test del solo bridge). Per scrivere davvero —
> anche solo per alimentare il **simulatore di XTrader** — serve DRY_RUN off, e quindi
> la conferma compare a ogni avvio. Un recupero reale **completamente automatico**
> richiederebbe di rimuovere di proposito quella guardia. Per le prove tieni comunque
> **XTrader in simulazione**.

### Metodo 1 — Cartella «Esecuzione automatica» (semplice)
1. Premi `Win + R`, scrivi `shell:startup` e premi Invio: si apre la cartella di avvio.
2. Trascina lì un **collegamento** all'eseguibile del bridge (`XTrader-Signal-Bridge.exe`,
   lo stesso che scarichi/compili — vedi [Build dell'EXE](#build-dellexe-sviluppatori)):
   tasto destro sull'EXE → *Crea collegamento* → sposta il collegamento nella cartella.
3. Al prossimo **accesso** a Windows (il **login** del tuo utente, non la sola
   accensione: se il PC riavvia e resta alla schermata di login, l'app parte **dopo**
   che fai login) l'app si apre da sola. La configurazione viene letta
   da `%APPDATA%\XTraderBridge\config.json` (vedi
   [Dove vengono salvati i file](#dove-vengono-salvati-i-file)), quindi token, chat e
   impostazioni sono già a posto: **non devi reinserire il token**.

### Metodo 2 — Utilità di pianificazione (più robusto)
Utile se vuoi che parta **all'accesso** anche in scenari in cui la cartella Startup
non basta.
1. Apri **Utilità di pianificazione** (*Task Scheduler*).
2. *Crea attività di base…* → nome a piacere (es. «XTrader Bridge»).
3. **Attivazione**: «**All'accesso**». **Non** usare «All'avvio del computer»: il
   bridge è un'app con interfaccia, ha bisogno di una **sessione utente interattiva**
   per mostrare la finestra (e la conferma in modalità reale) e per leggere le
   impostazioni del **tuo** profilo (`%APPDATA%`); avviato prima del login non
   avrebbe GUI né il profilo giusto.
4. **Azione**: «Avvia programma» → seleziona `XTrader-Signal-Bridge.exe`.
5. Fine. Opzionale: nelle proprietà dell'attività spunta «Esegui con i privilegi più
   elevati» solo se necessario.

### Far partire anche l'ascolto da solo
Dopo che l'app si apre (uno dei due metodi sopra), attiva **`auto_start_listener`**
nella tab *Sicurezza*: all'apertura il bridge **avvia il listener** senza premere
AVVIA — ma solo se **token e chat** sono configurati, e in **modalità reale** chiede
**conferma** (vedi sopra). Di default è disattivato.

> Nota: questa guida non è verificata automaticamente in CI (riguarda passi di
> Windows). I percorsi/menu possono variare leggermente tra le versioni di Windows.

---

## Domande frequenti

**Devo tenere il programma aperto?** Sì, deve girare in background mentre vuoi
ricevere segnali. Puoi minimizzarlo.

**Può partire da solo all'apertura?** Sì, attivando `auto_start_listener` (tab
*Sicurezza*): all'apertura il bridge avvia il listener senza premere AVVIA, ma solo
se token e chat sono configurati. In **modalità reale** chiede prima conferma, così
non inizia a scommettere da solo per sbaglio. Di default è disattivato.

**Cosa succede se cade la connessione?** Il listener **si riconnette da solo** con
attese crescenti (backoff: 2s, 4s, 8s… fino a 60s) finché resta avviato; durante
l'attesa lo stato mostra **RICONNESSIONE…**, poi torna **ATTIVO**. All'avvio i
messaggi accumulati mentre era offline vengono **scartati** (`drop_pending_updates`).
Inoltre, **a prescindere** da come avviene la riconnessione, un messaggio Telegram
**più vecchio di `max_signal_age` secondi** (default 120s) viene **ignorato**
all'arrivo: così, se la rete è mancata a lungo, gli arretrati rifetchati non
diventano scommesse vecchie. Un errore **non** recuperabile (es. **token non valido**)
non viene ritentato all'infinito: il bridge si ferma e mostra l'errore. Lo STOP
manuale interrompe subito, senza riconnessioni.

**Posso usare più canali?** Sì, con `source_chats` (vedi
[Più chat sorgenti](#più-chat-sorgenti-multi-chat)).

**XTrader rischia di ripetere scommesse vecchie?** No: con un solo segnale attivo +
timeout + svuotamento, XTrader vede sempre solo il segnale più recente o nessuno.

**Perché il bridge non parte?** Probabili cause: manca il Bot Token, manca il CSV
Path, il Timeout non è un numero > 0, oppure non hai configurato nessuna chat/sorgente.
Il motivo esatto compare nel log.

**Perché non scrive niente nel CSV?** Se sei in `dry_run` (default), è normale: è la
simulazione. Per scrivere davvero metti `dry_run=false`.

**Dove sono le impostazioni?** In `%APPDATA%\XTraderBridge\config.json` (vedi
[Dove vengono salvati i file](#dove-vengono-salvati-i-file)).

---

## Build dell'EXE (sviluppatori)

La compilazione avviene via **GitHub Actions** su Windows:

1. Push sul branch `main` (oppure un tag `v*` per una release).
2. Actions esegue i test, poi compila l'EXE.
3. **Actions → ultima run → Artifacts**.
4. Scarica `XTrader-Signal-Bridge-Windows-v<versione>-<data>.zip`.
5. Dentro trovi `XTrader-Signal-Bridge.exe` pronto all'uso.

In locale (dev): `python main.py` avvia la GUI; `python -m pytest -q -m "not manual"`
esegue la suite offline.

---

## Dependency lockfile / build EXE riproducibile (A7)

Per rendere la build Windows dell'EXE **riproducibile e verificabile**, le dipendenze
sono espresse come file sorgente `.in` (vincoli "morbidi" top-level) da cui si genera un
**lockfile completo con hash** sulla stessa piattaforma della build.

| File | Cos'è | Si modifica a mano? |
|---|---|---|
| `requirements.in` | **sorgente unica** delle dipendenze **runtime** top-level (FLOOR `>=`, con la motivazione di sicurezza) | sì |
| `requirements-build.in` | tutto ciò che la **build Windows** installa: `-r requirements-dev.txt` (runtime + `pytest`, single-source) + `pyinstaller` + `httpx` | sì |
| `requirements-build.lock` | **lockfile completo con hash** (versioni esatte di TUTTE le transitive) generato su **Windows + Python 3.11** | **NO** — si rigenera dal workflow |
| `requirements.txt` | install "soft" della CI di test/dev: ora **richiama `requirements.in`** (`-r requirements.in`), quindi una dipendenza runtime ha **un solo posto** dove cambiare ed è la stessa sorgente del lock (niente drift) | sì |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest` (test) | sì |

> ⚠️ Il lockfile **non va generato da Linux**: gli hash e le wheel devono corrispondere a
> quelli che la build Windows installa davvero. Per questo si genera in CI su Windows.

### Garanzie del workflow di generazione

Il job *Generate Windows Lockfile* (su `windows-latest` + Python 3.11):

- usa una **versione ESATTA** di `pip-tools` (pinnata nel workflow) → stesso `.in` →
  stesso lock (output deterministico);
- **fallisce se il lock committato è stantio** rispetto ai `.in` (rigenera e confronta:
  un lock che non corrisponde più va rigenerato e ricommittato);
- **valida** il lock con `pip install --require-hashes` in un **venv pulito** (isolato
  dalle dipendenze del generatore), così un lock incompleto non passa per poi rompere la
  build "pulita".

### Verifica manuale del lock committato (prima di una release)

Quando avvii il workflow **a mano** (*Actions → "Generate Windows Lockfile" → Run
workflow*) puoi spuntare l'opzione **"Collauda il requirements-build.lock committato"**
(input `verify_committed_lock`): un primo step testa il lock **già committato così com'è**
— lo stesso file che `build.yaml` installerà — in un venv pulito con `--require-hashes` +
test, **prima** di rigenerarlo. Serve a scoprire on-demand un eventuale "API drift" di una
dipendenza pinnata **prima di pubblicare una release**.

> ⚠️ Lascia l'opzione **OFF** (default) quando avvii il workflow per **rigenerare** un lock
> rotto o stantio: con l'opzione attiva, il collaudo del vecchio lock fallirebbe e
> impedirebbe la generazione/upload del nuovo lock — cioè proprio l'artifact che ti serve
> per sistemarlo. Sulle PR lo step è sempre saltato (lì basta la validazione del lock
> rigenerato).

### Come (ri)generare il lockfile

1. Modifica `requirements.in` e/o `requirements-build.in` se cambi le dipendenze.
2. Vai su **Actions → "Generate Windows Lockfile" → Run workflow** (oppure si avvia da
   solo in una PR che tocca quei file). Gira su `windows-latest` + Python 3.11, esegue
   `pip-compile --generate-hashes` e **valida** il lock con `pip install --require-hashes`.
3. Apri la run → **Artifacts** → scarica `requirements-build-lock-windows-py311`
   (contiene `requirements-build.lock`).
4. **Committa** `requirements-build.lock` nel repository (root).

### Effetto sulla build

`build.yaml` rileva automaticamente il lock:

- se **`requirements-build.lock` è presente** → installa **solo** da lì con
  `python -m pip install --require-hashes -r requirements-build.lock` (riproducibile);
- se **assente** → install legacy (`requirements-dev.txt` + `pyinstaller httpx`), così la
  build non si rompe finché il lock non è stato committato.

La compilazione dell'EXE con **PyInstaller** resta invariata.

---

## Struttura del progetto

```text
xtrader-bridge/
├── main.py                 ← entrypoint (avvia la GUI)
├── xtrader_bridge/         ← pacchetto Python (parser, CSV, config, GUI, router, guardrail)
├── tests/                  ← test automatici (pytest: unit, integration, safety, smoke)
├── data/                   ← dizionario XTrader + parser personalizzati (data/parsers/)
├── docs/                   ← contratto CSV, guida parser, audit
├── requirements.in         ← dipendenze runtime top-level (sorgente del lock)
├── requirements-build.in   ← dipendenze build EXE (sorgente del lock di build)
├── requirements-build.lock ← lockfile con hash (generato su Windows; va committato)
├── requirements.txt        ← dipendenze Python (install "soft")
├── README.md               ← questo file
└── .github/workflows/      ← CI + build EXE Windows + Generate Windows Lockfile
```

---

## Autore

Sviluppato su misura per l'uso con **XTrader** di
[TradingSportivo.club](https://assistenza.tradingsportivo.club/).

*XTrader Signal Bridge — ponte tra segnali Telegram e XTrader. Il merge resta
sempre manuale del proprietario.*
