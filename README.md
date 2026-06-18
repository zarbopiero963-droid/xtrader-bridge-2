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
Sicurezza / Conferme XTrader*: `recognition_mode`, `require_price`, `dry_run`,
`max_per_day`, `queue_mode`, `xtrader_notification_chat_id`. Le **chat sorgente**
(`source_chats`) si modificano dal pulsante **"📡 Chat sorgenti"** (vedi
[Più chat sorgenti](#più-chat-sorgenti-multi-chat)). Le restanti (`active_parser`,
`parser_by_chat`, `confirmation_keywords`, `rejection_keywords`) si modificano ancora
**a mano** nel file (chiudi prima il bridge, poi riaprilo). Ogni chiave è comunque
**preservata** quando salvi dalla GUI, quindi non si perde.

| Chiave | Default | Valori | A cosa serve |
|---|---|---|---|
| `recognition_mode` | `NAME_ONLY` | `ID_ONLY`, `NAME_ONLY`, `BOTH` | Come XTrader riconosce il segnale. Oggi gli ID non arrivano dal messaggio Telegram, quindi `NAME_ONLY` (nomi) è il default. `ID_ONLY` richiede `MarketId`/`SelectionId`; `BOTH` entrambi. |
| `require_price` | `true` | `true`/`false` | Se `true`, un segnale senza quota valida (> 1.0) viene **scartato** (default sicuro). |
| `dry_run` | `true` | `true`/`false` | **Simulazione**: se `true`, il CSV operativo **non** viene scritto. Mettilo a `false` solo per l'uso reale, consapevolmente. |
| `max_per_day` | `200` | intero | Tetto di segnali nuovi accettati in un giorno (UTC). Oltre, i segnali in eccesso non scrivono. |
| `queue_mode` | `OVERWRITE_LAST` | `OVERWRITE_LAST`, `APPEND_ACTIVE`, `QUEUE_UNTIL_CONFIRMED` | Quanti segnali attivi tenere nel CSV. `OVERWRITE_LAST` = uno solo (sicuro). Le altre due scrivono **più righe** = più scommesse simultanee. |
| `active_parser` | `""` | nome parser | Parser Personalizzato attivo globalmente (`""` = parser hardcoded). Di norma si imposta dalla GUI. |
| `parser_by_chat` | `{}` | `{chat_id: nome_parser}` | Override del parser per singola chat. |
| `source_chats` | `[]` | lista | Più chat sorgente (vedi sotto). |
| `xtrader_notification_chat_id` | `""` | chat id | Chat **separata** su cui XTrader notifica l'esito (vedi [Conferma da XTrader](#conferma-da-xtrader)). |
| `confirmation_timeout` | `120` | secondi | Riservato: presente in config ma **non ancora collegato al runtime** (la coda usa `clear_delay`). Impostarlo oggi non ha effetto. |
| `confirmation_keywords` | `[]` | lista | Parole che indicano conferma (vuoto = default del modulo). |
| `rejection_keywords` | `[]` | lista | Parole che indicano rifiuto (vuoto = default del modulo). |

> Una `config.json` corrotta viene messa da parte come `.bak` e il bridge riparte
> dai default sicuri. Le chiavi mancanti ereditano sempre il default.

---

## Più chat sorgenti (multi-chat)

Per ricevere segnali da **più chat/canali**, usa il pulsante **"📡 Chat sorgenti"**
nella finestra principale (aggiungi/rimuovi righe, imposta nome, chat_id, attiva,
modalità PRE/LIVE, provider, e salva) — oppure, in alternativa, valorizza a mano
`source_chats` in `config.json`. È una lista di oggetti:

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
  notifiche. (`confirmation_timeout` è riservato e non ancora collegato — vedi tabella.)

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

> Prima dell'uso reale, segui la procedura **`docs/audit/xtrader_simulation_test.md`**
> con XTrader in Modalità Simulazione, stake basso e limiti chiari. Nessuna promessa
> di profitto.

---

## Formato CSV generato

Header ufficiale a **14 colonne** (vedi **[`docs/xtrader_csv_contract.md`](docs/xtrader_csv_contract.md)**):

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
"TelegramBot","","Inter v Milan","","MATCH ODDS","MATCH_ODDS","","Inter","0","1.85","","","PUNTA",""
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

## Domande frequenti

**Devo tenere il programma aperto?** Sì, deve girare in background mentre vuoi
ricevere segnali. Puoi minimizzarlo.

**Cosa succede se cade la connessione?** Il bridge si riconnette; i messaggi vecchi
accumulati durante l'avvio vengono scartati (`drop_pending_updates`).

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

## Struttura del progetto

```text
xtrader-bridge/
├── main.py             ← entrypoint (avvia la GUI)
├── xtrader_bridge/     ← pacchetto Python (parser, CSV, config, GUI, router, guardrail)
├── tests/              ← test automatici (pytest: unit, integration, safety, smoke)
├── data/               ← dizionario XTrader + parser personalizzati (data/parsers/)
├── docs/               ← contratto CSV, guida parser, audit
├── requirements.txt    ← dipendenze Python
├── README.md           ← questo file
└── .github/workflows/  ← CI + build EXE Windows
```

---

## Autore

Sviluppato su misura per l'uso con **XTrader** di
[TradingSportivo.club](https://assistenza.tradingsportivo.club/).

*XTrader Signal Bridge — ponte tra segnali Telegram e XTrader. Il merge resta
sempre manuale del proprietario.*
