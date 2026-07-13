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
   • riceve il messaggio via Bot API
   • DECIDE come instradarlo (`telegram_dispatch.decide`): scarta gli arretrati
     troppo vecchi, ignora se manca un filtro chat, manda gli ESITI della chat
     notifiche XTrader al percorso di conferma, e processa solo le chat configurate
   • lo analizza con il **Parser Personalizzato** configurato per la chat (il parser
     hardcoded P.Bet. resta solo per compatibilità/test: NON gira nel flusso live —
     una chat senza Parser Personalizzato viene ignorata)
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

**🌐 Al primo avvio** (finché non hai mai scelto una lingua) compare il **selettore
lingua del bridge**: 🇮🇹 Italiano / 🇬🇧 English / 🇪🇸 Español (#343). La scelta viene
salvata (`app_language`) e **allinea anche la lingua del CSV** (`csv_language`, separatore
decimale #342). Se chiudi senza scegliere non succede nulla: il bridge resta nel
comportamento storico (italiano) e il selettore ricompare al prossimo avvio. Promemoria:
col riconoscimento a nomi, **imposta in XTrader/Betting Toolkit la lingua della fonte
uguale a quella scelta qui** (i nomi dipendono dalla lingua del palinsesto). I nomi
dipendono anche dall'**exchange Betfair** (BF fa piccole differenze tra i nomi
dell'exchange italiano e di quello inglese, e usa ID diversi tra exchange): per questo il
**dizionario nomi e mercati è user-built** — inserisci i **nomi esatti** della tua
fonte/exchange e taggali con la loro **lingua** (colonna «Lingua»), così il filtro
lingua-fonte sceglie le voci giuste. Dalla
slice 4a la **finestra principale** è localizzata (tab, bottoni, nomi campo in EN/ES;
la lingua si applica al **riavvio**); dalla slice 4b anche lo stato «⬤ ATTIVO/RICONNESSIONE…»;
dalle slice 4c–4g le **finestre secondarie** (Provider, Profili, Chat sorgenti, Diario, Parser),
il **🧙 Wizard** (slice 4h), la finestra **🗺️ Mapping** (Dizionario nomi + mercati, slice 4i), i
**banner di modalità REALE/COLLAUDO**, il primo gruppo di **log di ciclo-vita del bridge** (avvio/
STOP/connessione/ascolto/scadenza segnale/svuotamento manuale del CSV, slice 4j), i **log delle
azioni su configurazione e CSV** (salva config/tema, salva/crea/aggiorna il percorso CSV, slice 4k)
i **log di avvio/validazione START** (i messaggi che spiegano perché il bridge non è partito:
token/chat/parser mancanti, conflitto chat notifiche, modalità reale annullata, CSV non
inizializzabile, slice 4l), i **log di esito elaborazione messaggio/segnale** (messaggio ignorato/
scartato, scrittura CSV fallita, tracciabilità Messaggio→CSV, aggiornamento CSV post-conferma/scadenza,
segnali scaduti rimossi, slice 4m) e — dalla slice 4n — i **log di resilienza** (riconnessione,
connessione persa con backoff, errore non recuperabile del listener, recovery CSV post-STOP/temporanei
orfani, slice 4n; i log di recovery con la «parola-quando», es. «CSV riportato a solo header
all'avvio», restano in italiano perché quel valore è usato anche come chiave nel codice, `== "all'avvio"`)
i **log degli strumenti Log & diagnostica** (apri cartella log, export audit modalità reale, copia
diagnostica, retention log, svuota log, toggle Debug, slice 4o), i **log di
wizard, selettore lingua e profilo/sorgenti** (apertura/fine wizard, selettore lingua rimandato,
applicazione profilo, aggiornamento sorgenti multi-chat, slice 4p), i **log dei
guardrail runtime** (stato anti-duplicato illeggibile, fallimento persistenza stato anti-duplicato/
limite giornaliero, modalità coda, slice 4q), i **log di annullo transizione
modalità** (attivazione REALE/COLLAUDO annullata, coda multi-segnale annullata, slice 4r), i **nomi
delle modalità di trading** interpolati in quei log (REALE→REAL, COLLAUDO→TEST/PRUEBA,
SIMULAZIONE→SIMULATION/SIMULACIÓN, slice 4s), la scheda **🧹 Nomi squadra**
(pannello di ripulitura dei nomi squadra noti, slice 4t), il pannello **📋 Riepilogo configurazione**
(modalità, stato dizionario, traduzioni, «Pronto?», slice 4u) e — dalla slice 4v — la **chrome** del
pannello **🌳 Mapping guidato** (titoli, label, filtro, intestazioni, bottoni, dialog «Nuovo profilo»)
sono localizzati.
Restano ancora in italiano: la finestra **🧰 Strumenti (hub)**, i **messaggi di stato dinamici** del
🌳 Mapping guidato (in arrivo nella slice 4w), i restanti **messaggi di log** dell'app e i **dialoghi modali** GUI (e i
messaggi che riportano contenuto di dominio, che restano IT per contratto) — previsti nelle prossime
slice della #343.

La finestra principale espone i campi essenziali. Si salvano con **💾 Salva Config**
(oppure all'avvio con **▶ AVVIA**) nel file `config.json` (vedi
[Dove vengono salvati i file](#dove-vengono-salvati-i-file)). Ogni campo mostra un **esempio-guida**
(placeholder) quando è vuoto; è solo un aiuto visivo e non viene salvato.

| Campo GUI | Chiave config | Default | A cosa serve |
|---|---|---|---|
| 🔑 **Bot Token** | `bot_token` | *(vuoto)* | Token del bot Telegram (@BotFather). Senza, START è bloccato. Mai mostrato nei log. Salvato nel **keyring del sistema** (Windows Credential Manager); **senza un backend keyring** ripiega sul token **in chiaro** in `config.json` con avviso nel log — vedi [Sicurezza](#sicurezza-simulazione-duplicati-e-limiti). |
| 💬 **Chat ID** | `chat_id` | *(vuoto)* | ID della chat/canale sorgente. Definisce quali messaggi vengono accettati. |
| 📄 **CSV Path** | `csv_path` | `C:\XTrader\segnali.csv` | File CSV che XTrader monitora. Obbligatorio. Puoi digitarlo, usare **«📁 Sfoglia…»** per selezionarne uno esistente, o **«📄 Crea CSV»** per generarne uno nuovo **vuoto** (solo header) nel formato XTrader; in tutti i casi alla scelta il percorso viene **salvato subito** (senza click extra su «Salva Config»). «Crea CSV» non sovrascrive un file estraneo senza conferma esplicita. |
| ⏱️ **Timeout (sec)** | `clear_delay` | `90` | Dopo quanti secondi un segnale scade e il CSV viene svuotato. Deve essere un intero > 0. |
| 🏷️ **Provider** | `provider` | `TelegramBot` | Etichetta scritta nella colonna `Provider` del CSV (vedi nota sotto). |

Pulsanti aggiuntivi:

- **🌙 / ☀️ Toggle tema** (nell'header) — commuta tra tema **scuro** (default) e **chiaro**. La
  preferenza (`theme` in `config.json`, `dark`/`light`) è **salvata subito** e riapplicata all'avvio.
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
| `recognition_mode` | `NAME_ONLY`* | `ID_ONLY`, `NAME_ONLY`, `BOTH` | Come XTrader riconosce il segnale. Gli ID non arrivano dal messaggio Telegram; il flusso del Parser Personalizzato può **arricchirli dal dizionario locale** quando trova un match univoco. **Nota (rimozione «Betfair Sync»):** l'arricchimento ID è **attualmente disattivato** (`id_resolver=None`) **sia** nel **CSV live** **sia** nell'anteprima «Prova messaggio» — entrambi restano a **nomi** finché non popoli a mano il dizionario locale e **riattivi il *seam* in entrambi i punti** (così anteprima e runtime coincidono: nessun «Pronto» in GUI su una riga che il live scarterebbe). `NAME_ONLY` (nomi), `ID_ONLY` richiede `MarketId`/`SelectionId`, `BOTH` accetta la riga con ID **oppure** nomi. **\*Default per le config NUOVE (#311-2.3):** è `NAME_ONLY` finché il **dizionario non è pienamente validato** contro un export XTrader reale (#311-2.2), poi passa **automaticamente a `BOTH`** («ID se univoci, altrimenti nomi»). Un valore malformato ricade su `NAME_ONLY` (fail-safe). Le config esistenti mantengono la loro scelta. |
| *(quota obbligatoria)* | — | — | NON è più una chiave globale: la comanda la casella **«Obblig.» sulla riga `Price`** di ogni Parser Personalizzato. `Price` obbligatorio → segnale senza quota valida (> 1.0) **scartato**; non obbligatorio → quota opzionale. |
| `dry_run` | `true` | `true`/`false` | **Simulazione**: se `true`, il CSV operativo **non** viene scritto. Mettilo a `false` solo per l'uso reale, consapevolmente. |
| `bridge_mode` | derivato da `dry_run` (config nuova: `SIMULAZIONE`) | `SIMULAZIONE`/`COLLAUDO`/`REALE` | Modalità **nominata** (#311 §3.1), derivata e coerente con `dry_run` (che resta autoritativo: incoerenza → Simulazione). `COLLAUDO` scrive il CSV col banner «XTrader in simulazione». |
| `max_per_day` | `200` | intero | Tetto di segnali nuovi accettati in un giorno (**ora locale** del sistema: reset a **mezzanotte locale**, ora legale gestita dal SO). Oltre, i segnali in eccesso non scrivono. |
| `queue_mode` | `OVERWRITE_LAST` | `OVERWRITE_LAST`, `APPEND_ACTIVE`, `QUEUE_UNTIL_CONFIRMED` | Quanti segnali attivi tenere nel CSV. `OVERWRITE_LAST` = uno solo (sicuro). Le altre due scrivono **più righe** = più scommesse simultanee. Attivare una modalità multi-riga dalla GUI chiede una **conferma**. |
| `max_active_signals` | `2` | intero ≥ 1 | **Tetto di righe/scommesse attive** simultanee nelle modalità multi-riga (#136 p5): un nuovo segnale oltre il tetto viene **bloccato** (ritentabile quando una riga scade/è confermata). Default basso (2). Ininfluente in `OVERWRITE_LAST` (sempre 1 riga). La GUI mostra un indicatore **"Righe attive: N/M"**. |
| `active_parser` | `""` | nome parser | Parser Personalizzato attivo **globalmente**. Di norma si imposta dalla GUI. **`""` (vuoto) = nessun parser custom globale.** Una chat con un parser **dedicato** in `parser_by_chat` funziona comunque; una chat **senza** né `active_parser` né voce in `parser_by_chat` viene **IGNORATA** in live (il parser hardcoded P.Bet **non** gira live, vedi nota sotto). |
| `parser_by_chat` | `{}` | `{chat_id: nome_parser}` | Override del parser (singolo) per singola chat. Modificabile dal pulsante **"📡 Chat sorgenti"** (colonna Parser di ogni sorgente). Contiene **solo** le sorgenti **attive** (una sorgente disattivata non autorizza la sua chat). |
| `parser_list_by_chat` | `{}` | `{chat_id: [nome_parser, ...]}` | **PR-2 (router multi-parser):** più parser per una chat, valutati **in ordine**; scattano **TUTTI** quelli le cui condizioni combaciano (una riga CSV per parser che scatta, deduplicata per-riga). Ha **precedenza** su `parser_by_chat` (che resta sincronizzato al **primo** nome per autorizzazione/retro-compat). Vuoto = singolo/globale come prima. Gestito dall'editor **"📡 Chat sorgenti"** (colonna Parser → editor a lista ordinata). |
| `parser_by_chat_disabled` | `{}` | `{chat_id: nome_parser}` | Gestito dall'editor **"📡 Chat sorgenti"**: parcheggia la scelta parser (singola) delle sorgenti **disattivate** così, riabilitandole, non si perde (non autorizza né influisce sul routing/avvio — la chat resta esclusa finché disattivata). |
| `parser_list_by_chat_disabled` | `{}` | `{chat_id: [nome_parser, ...]}` | Come sopra ma per la **lista multi-parser** (PR-2) parcheggiata delle sorgenti disattivate. |
| `source_chats` | `[]` | lista | Più chat sorgente (vedi sotto). |
| `xtrader_notification_chat_id` | `""` | chat id | Chat **separata** su cui XTrader notifica l'esito (vedi [Conferma da XTrader](#conferma-da-xtrader)). |
| `confirmation_timeout` | `120` | secondi | **In `QUEUE_UNTIL_CONFIRMED`**: per quanti secondi un segnale resta in attesa della conferma XTrader prima di scadere (timeout per-segnale della coda). Nelle altre modalità coda non si applica: vale `clear_delay`. |
| `max_signal_age` | `120` | secondi | Un messaggio Telegram più vecchio di così viene **ignorato** all'arrivo (anti-segnale-stantio: evita che gli arretrati rifetchati dopo una disconnessione diventino scommesse vecchie). Il valore **effettivo non supera la vita della riga CSV per la modalità coda attiva** — `confirmation_timeout` in `QUEUE_UNTIL_CONFIRMED`, altrimenti `clear_delay`: un segnale già più vecchio della sua durata sul CSV è trattato come stantio. È inoltre **limitato alla finestra di deduplica** (300s): un messaggio troppo vecchio per essere riconosciuto come duplicato viene trattato come stantio, così una ridelivery dopo una riconnessione non può diventare una scommessa doppia. Di conseguenza, in `QUEUE_UNTIL_CONFIRMED` con `confirmation_timeout` **> 300s**, un messaggio più vecchio di 300s è comunque scartato (trade-off deliberato a favore della sicurezza anti-doppia-scommessa). `0` = filtro disattivato. Le **conferme XTrader** (chat notifiche) **non** sono soggette a questo filtro. |
| `auto_start_listener` | `false` | `true`/`false` | Se `true`, all'apertura l'app **avvia da sola** il listener — ma solo se token e **almeno una chat sorgente ATTIVA** sono configurati (sorgenti tutte disattivate = niente avvio automatico); in **modalità reale** chiede conferma prima di partire. Un valore malformato (typo) vale come `false` anche al **salvataggio** (fail-closed). Default `false`: il bridge parte solo con **AVVIA**. Attivabile dalla tab *Sicurezza*. |
| `confirmation_keywords` | `[]` | lista | Parole che indicano conferma (vuoto = default del modulo). Dalla GUI: stringa separata da virgola. |
| `rejection_keywords` | `[]` | lista | Parole che indicano rifiuto (vuoto = default del modulo). Dalla GUI: stringa separata da virgola. |
| `log_retention_days` | `0` | `0`/`5`/`15`/`30`… | Giorni di conservazione dei log: oltre il limite i file `bridge-AAAA-MM-GG.log` più vecchi vengono **cancellati** all'avvio del bridge (e quando cambi l'opzione). `0` = "Mai" (conserva tutto). Dalla tab *Log*: tendina **Conserva** + pulsante **🧹 Svuota log**. |
| `debug_log` | `false` | `true`/`false` | Modalità **Debug**: log dettagliato del percorso (avvio/stop, salvataggi, messaggio in ingresso, stadi del segnale) + warning, per capire "cosa è rotto". Attivabile dalla tab *Log* (checkbox **🐞 Debug**). |
| `debug_message_payload` | `false` | `true`/`false` | **Privacy dei log.** Se `false` (default) il **testo** dei messaggi Telegram **non** viene scritto in chiaro nei log: solo impronta (`sha256` a 12 cifre) + lunghezza + **prima riga troncata**. Se `true`, logga il **payload completo** (debug consapevole). Attivabile dalla tab *Sicurezza* (checkbox **🕵️**). I token restano comunque sempre redatti. |
| `providers` | `[]` | lista di nomi | **Anagrafica Provider**: nomi riutilizzabili nella colonna `Provider` del Parser Personalizzato (menu a tendina). Si gestisce dal pulsante **➕ Provider** nel costruttore; evita errori di battitura sul Provider (che deve combaciare col filtro dell'azione XTrader). |
| `csv_language` | `"IT"` | `IT`/`EN`/`ES` | **Lingua del CSV (#342)**: governa il **separatore decimale** scritto nel file (`Price`/`MinPrice`/`MaxPrice`/`Points`/`Handicap`): `IT`/`ES` = **virgola** («1,85»), `EN` = **punto**. Nota (#343): dall'update «decimali intelligenti» XTrader/Betting Toolkit accetta **entrambi** i separatori su tutte le lingue, quindi la scelta è belt-and-suspenders, non più critica. Valore malformato → `IT` (fail-closed). Si imposta col **selettore lingua al primo avvio** (o nel `config.json`). |
| `app_language` | `""` | `""`/`IT`/`EN`/`ES` | **Lingua dell'applicazione (#343)**: scelta col **selettore al primo avvio** (🌐 IT/EN/ES). `""` = mai scelta → il selettore ricompare al prossimo avvio (nel frattempo il bridge resta nel comportamento storico IT). Alla scelta viene **allineata anche `csv_language`**, MA una `csv_language` **personalizzata a mano** (diversa dal default `IT` e dalla lingua scelta) viene **preservata** — su XTrader senza l'update «decimali intelligenti» un cambio di separatore a sorpresa può far rifiutare il CSV. Con **auto-start attivo** il selettore **non compare** (niente finestra modale sopra un avvio non presidiato): la lingua si imposta qui in `config.json`. Valore malformato → `""` (fail-closed). Dalla slice 4a governa anche la lingua della finestra principale (applicata al riavvio). |
| `source_language` | `""` | `""`/`IT`/`EN`/`ES` | **Lingua della FONTE per il riconoscimento a nomi (#3 slice 5a)**: dichiara in che lingua sono i nomi (evento/mercato/selezione) nel palinsesto della tua fonte — col riconoscimento **a nomi** i nomi dipendono dalla lingua (conferma supporto Betting Toolkit). `""` = **non dichiarata** → comportamento storico **agnostico** alla lingua (nessun cambio di matching). Override **per-parser** via il campo `source_language` del Parser Personalizzato (vince sul globale). Valore malformato → `""` (fail-closed). Dalla **slice 5b** la lingua-fonte **filtra davvero** la mappatura nomi: le righe di dizionario con colonna `language` uguale alla lingua-fonte hanno priorità (le agnostiche restano valide), **identico su live e anteprima**. Dalla **slice 5c** lo stesso filtro-lingua vale anche per il **Dizionario mercati** (le voci mercato hanno una colonna `language`; voce della lingua esatta prioritaria sull'agnostica, altra lingua scartata, typo fail-closed). Le colonne **«Lingua»** per riga si impostano nel **Dizionario nomi** e nel **Dizionario mercati** (🧰 Strumenti → 🗺️ Mapping) o nel `config.json`; la lingua-fonte globale/per-parser resta in `config.json` (`source_language`). |

> Una `config.json` corrotta viene messa da parte come `.bak` e il bridge riparte
> dai default sicuri. Le chiavi mancanti ereditano sempre il default.

### 📖 Dizionario (consultazione, sola lettura)

> **Nota (rimozione «Betfair Sync»).** La vecchia funzione **🔵 Betfair Sync** — login a
> Betfair, download del catalogo e costruzione automatica del dizionario — **è stata rimossa**:
> il bridge non contatta più Betfair, non fa login e non fa auto-sync. Il **dizionario locale**
> (`betfair_dictionary.db`, SQLite in `%APPDATA%\XTraderBridge`, sempre solo sul PC) resta come
> substrato ma va **popolato a mano** dall'utente con i propri campi personalizzati. Di
> conseguenza il flusso CSV **live non arricchisce più** gli ID (EventId/MarketId/SelectionId)
> dal dizionario: la riga resta a **nomi** (il *seam* di arricchimento è pronto e riattivabile
> quando il dizionario custom sarà popolato).
>
> **Come si popola oggi.** Non esiste (ancora) una procedura di import/seed integrata nella GUI:
> finché non verrà aggiunta, un **DB pre-popolato è di fatto un prerequisito** per l'arricchimento
> ID. Senza dizionario popolato il bridge funziona comunque **a nomi** (`recognition_mode`
> `NAME_ONLY`, il default per le config nuove): consulta/ripulisci i nomi già presenti dalle
> schede «📖 Dizionario» e «🧹 Nomi squadra». La definizione dello schema custom e del suo
> import è lavoro dell'utente/futuro, fuori dallo scope di questa rimozione.

Dalla finestra **"🧰 Strumenti" → scheda "📖 Dizionario"** puoi **consultare** il dizionario
locale (Sport → Competizioni → Eventi → Mercati → Selezioni). Scegli il **Livello** e il
**Sport**, spunta **"Solo attivi"**, **cerca** per nome o ID e premi **"🔄 Aggiorna"**. È una
vista **di sola lettura**: non modifica il dizionario, non piazza scommesse e non fa rete. Se
un altro strumento tiene occupato il DB in quel momento, la riga conteggi mostra **"⏳
Dizionario in aggiornamento…"** e la GUI **non si blocca**: attendi e premi di nuovo **"🔄
Aggiorna"**.

---

## Più chat sorgenti (multi-chat)

Per ricevere segnali da **più chat/canali**, usa il pulsante **"📡 Chat sorgenti"**
nella finestra principale: aggiungi/rimuovi righe e imposta per ciascuna nome,
chat_id, attiva, modalità PRE/LIVE, provider e — colonna **Parser** — **uno o più** Parser
Personalizzati per quella chat. Il pulsante nella colonna Parser apre un **editor a lista
ordinata**: con **un** parser il comportamento è quello di sempre (`parser_by_chat`); con
**più** parser (PR-2, router multi-parser, `parser_list_by_chat`) il messaggio è passato a
**ciascuno in ordine** e scattano **TUTTI quelli le cui condizioni combaciano** — una riga CSV
per parser che scatta, deduplicata per-riga (nessuna doppia scommessa accidentale). Insieme alle
**[Condizioni di gate](#parser-personalizzato)** è la soluzione a «un mercato/lato diverso a
seconda dello scenario, sulla stessa chat». In alternativa valorizza a mano `source_chats` in
`config.json`. È una lista di oggetti:

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
- **`enabled` malformato** (né un sì né un no riconoscibili — es. il typo `"flase"`) →
  la sorgente è considerata **disattivata** (fail-closed: un typo non può riattivare
  una chat che credevi spenta) e all'avvio compare un **avviso nel log eventi**.
  Valori riconosciuti: `true/false`, `si/no`, `on/off`, `1/0`.
- **`chat_id` duplicato** tra due sorgenti = errore bloccante all'avvio (il Provider
  sarebbe ambiguo). **Nome** duplicato = solo avviso.
- Le chat in `source_chats` attive sono **ammesse** in aggiunta a `chat_id`/
  `parser_by_chat`. Una sorgente disattivata resta esclusa.

---

## Parser Personalizzato

Oltre al parser integrato per il formato **P.Bet.**, puoi definire dalla GUI **come**
estrarre ogni colonna del CSV da un messaggio, **senza toccare il codice**. Apri
**🧩 Parser Personalizzato**.

> **⛔ Serve un parser per avviare (#311-1.3).** Il parser automatico P.Bet è disattivato
> nel percorso live: **senza almeno un Parser Personalizzato configurato** (globale o
> per-chat) il pulsante **AVVIA viene bloccato** con il messaggio «Configura almeno un
> Parser Personalizzato prima di avviare» — prima era solo un avviso e il listener
> partiva "ATTIVO" ignorando però ogni segnale in silenzio.

In breve, ogni colonna ha una **regola** con:

- **"Inizia dopo"** / **"Finisce prima"**: i delimitatori di testo (tolleranti agli
  spazi) che racchiudono il valore;
- **valore fisso** (alternativo all'estrazione);
- **trasformazione** opzionale (es. somma-gol → linea Over);
- **value-map** opzionale (traduce alias come `GG`/`OVER 2.5` nei valori XTrader, e
  `BACK`/`LAY` in `PUNTA`/`BANCA`);
- **obbligatorio**: se vuoto, il parser è **"Non pronto"** → **nessuna** riga CSV.

Il parser può anche dichiarare **Condizioni di gate** (sezione **«Condizioni di gate»**):
il parser **scatta solo se** il messaggio le soddisfa — righe **«contiene» / «NON contiene»**
un testo, combinate in modo **TUTTE (E)** o **una qualsiasi (O)**. Il confronto è senza
maiuscole e tollerante agli spazi; **nessuna condizione = nessun filtro** (comportamento
invariato). Serve a far agire un parser **solo sui messaggi pertinenti** (es. «un mercato/lato
diverso a seconda dello scenario»). Il match è **per sottostringa** (non parola intera): usa testi
**distintivi** (es. `@punta`, `⚽ 0 - 1`) per evitare che un testo breve come `BACK` scatti dentro
parole più lunghe. Dettagli: [`docs/custom_parser.md`](docs/custom_parser.md) §3ter.

Ogni parser può anche dichiarare uno **Sport** (tendina accanto a «Modalità»):
**Calcio / Tennis / Basket / Rugby Union** oppure **«(non specificato)»** = agnostico.
Lo Sport non cambia le colonne del CSV: indica a quale sport appartiene il segnale e
servirà a restringere la risoluzione degli ID Betfair allo sport giusto. È salvato nel
file del parser (campo `sport`); i parser creati prima di questa funzione restano
agnostici. Poiché il parser attivo è **per profilo**, cambiando profilo cambia anche lo
Sport del parser usato.

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

0. **Istanza singola (#311)** — il bridge può girare in **una sola istanza** alla volta:
   un secondo avvio (doppio click per errore, o avvio manuale con l'auto-start già
   partito) mostra l'avviso **«XTrader Bridge è già in esecuzione»** ed esce subito,
   senza avviare listener né toccare il CSV dell'istanza attiva. Due istanze avrebbero
   contatori/dedupe/coda separati in memoria → **rischio doppia scommessa**. Il lock è
   un mutex di sistema su Windows (si libera da solo anche dopo un crash o un kill:
   nessun blocco orfano al riavvio).

0-bis. **🧙 Wizard di prima configurazione (#311 §3.4)** — bottone accanto a «🧰
   Strumenti»: 5 step guidati (token + test getMe · Chat ID + messaggio di prova ·
   parser sul messaggio reale con verdetto/anteprima · csv_path + scrittura CSV di
   prova a solo header · checklist finale). Il wizard NON attiva mai la modalità
   Reale e il token non compare mai nei log; il salvataggio finale passa dai gate
   esistenti.
0. **Pannello «🚦 Salute» (#311 §3.3)** — scheda di monitoraggio a semafori: Telegram ·
   ultimo messaggio · parser attivo · ultimo segnale (col motivo) · CSV scrivibile
   (sonda non invasiva: mai un lock sul file) · conferme XTrader · modalità corrente.
   Dato assente = giallo onesto, mai verde per default.
1. **Modalità bridge (#311 §3.1)** — tendina «🚦 Modalità bridge» nella tab *Sicurezza*,
   tre stati nominati sopra `dry_run` (che resta la fonte del percorso di scrittura):
   **🧪 Simulazione Bridge** (`dry_run=true`, il CSV operativo NON viene scritto),
   **🔬 Collaudo XTrader** (scrive il CSV con banner permanente «XTrader deve essere in
   Modalità Simulazione»; conferma sì/no all'attivazione), **⚠️ Reale** (scommesse vere;
   richiede SEMPRE la frase di conferma, anche arrivando dal Collaudo). Una config
   incoerente (es. `bridge_mode:"REALE"` con `dry_run:true`) ricade in Simulazione
   (fail-closed). Storico: **Simulazione (`dry_run`)** — di default `true`: i segnali vengono riconosciuti
   ma il CSV operativo **non** viene scritto. Il log lo dichiara
   (`🧪 DRY_RUN attivo`). Per l'uso reale togli la spunta *Simulazione* nella tab
   *Sicurezza* (`dry_run=false`).
   - **Attivazione "frictionful" (audit #105 P2).** Passare da simulazione a **REALE**
     richiede una **doppia conferma**: oltre alla spunta, devi **digitare** la parola
     `REALE` in una finestra di conferma. Se annulli, il bridge resta in simulazione.
     La stessa conferma scatta anche **caricando un profilo** che porta `dry_run:false`
     (il caricamento profilo non bypassa il gate): se annulli, resti in simulazione.
   - **Banner rosso persistente** in alto finché sei in modalità reale; l'attivazione
     viene **tracciata** nel log come evento `REAL_MODE_ENABLED`.
   - **Esporta audit reale** (pulsante 🧾 nella tab *Stato*): salva in un file le righe
     `REAL_MODE_ENABLED` estratte dai log giornalieri.
   - La modalità reale, una volta confermata e salvata, **resta** tra i riavvii (la
     conferma serve solo all'attivazione). Per questo, **ogni avvio del listener in
     modalità reale** — sia **AVVIA** manuale sia avvio automatico — chiede una
     **conferma Sì/No** prima di partire (un `dry_run:false` già salvato non ripassa
     dal gate con la parola `REALE`).
2. **Filtro chat obbligatorio** — il bridge non parte senza almeno una chat/sorgente
   configurata, così non accetta segnali da chat arbitrarie. Se le sorgenti esistono ma
   sono **tutte disattivate**, l'avvio **automatico** non parte (fail-closed) e lo START
   manuale avvisa nel log che nessun segnale verrà processato.
3. **Un segnale alla volta** — con `queue_mode=OVERWRITE_LAST` il CSV contiene un
   solo segnale attivo; il timeout lo svuota.
   - **Modalità multi-segnale "frictionful" (audit #105 P2).** Attivare `APPEND_ACTIVE`
     o `QUEUE_UNTIL_CONFIRMED` (più righe/scommesse insieme) richiede una **conferma**,
     anche quando la modalità arriva da un **profilo caricato** (se rifiuti, resti a
     `OVERWRITE_LAST`). Un **tetto** `max_active_signals` (default **2**) **blocca** i segnali oltre N righe
     attive (ritentabili quando una si libera), e un indicatore **"Righe attive: N/M"** in
     alto mostra quante scommesse sono attive ora.
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
9. **CSV bloccato — escalation visibile (audit #105 H2).** Se XTrader tiene il file CSV
   **lockato** e le scritture falliscono **più volte di fila**, oltre al retry automatico
   il bridge lo rende evidente: dopo alcuni tentativi mostra lo stato **«🔒 CSV bloccato da
   XTrader»** (con il numero di tentativi) e, appena una scrittura torna a riuscire, segnala
   il **recupero**. Nessuna riga viene scritta due volte: è solo un avviso, il retry e il
   rollback restano invariati.

> 🔑 **Dove sta il Bot Token (e perché).** Per impostazione predefinita il token viene
> salvato nel **keyring del sistema operativo** (su Windows il **Credential Manager**
> nativo) tramite la libreria `keyring`: in `%APPDATA%\XTraderBridge\config.json` la
> chiave `bot_token` resta **vuota** e il segreto **non** è in chiaro su disco (audit
> #105 P1). Un campo interno `bot_token_storage` (`keyring`/`plaintext`/`none`) registra
> dove sta il token, così cancellarlo è definitivo (niente "resurrezioni" al riavvio). In
> memoria, a runtime, il token viene riletto dal keyring così il bridge funziona come prima.
>
> **Fallback.** Se sul sistema non c'è un backend keyring utilizzabile (es. una build
> senza `keyring`, o Linux senza Secret Service), il bridge **ripiega** sul vecchio
> comportamento — token in chiaro nel `config.json` — scrivendo un **avviso** nel log
> (nessun crash). In ogni caso il file **non** è nel repository (è in `.gitignore`),
> **non** finisce nei log (redazione attiva) e **non** è incluso nell'EXE/artifact.
>
> **Config corrotta e token (issue #199).** Se il `config.json` è **illeggibile** (JSON
> rotto), all'avvio viene messo da parte come `.bak` e il bridge riparte dai default con la
> chiave `bot_token` vuota e il sentinel perso. In quel caso il token nel keyring **NON
> viene cancellato** al primo salvataggio: il campo vuoto è il residuo della corruzione, non
> un azzeramento voluto, quindi il bridge **preserva** la credenziale (la rilegge dal keyring
> e la reidrata). Per **cancellare davvero** il token, svuota il campo *Bot Token* e salva
> quando il config è di nuovo integro (un clear deliberato resta definitivo, come prima).
>
> **Keyring illeggibile all'avvio (issue #140).** Se il keyring di sistema è
> **temporaneamente illeggibile** quando l'app si apre (outage transitorio del Credential
> Manager / Secret Service), il token non viene riletto e il campo *Bot Token* appare
> **vuoto** pur esistendo la credenziale. Anche qui il bridge **non cancella** il token al
> salvataggio successivo: il campo vuoto è il residuo di un caricamento incompleto, non un
> azzeramento voluto. Appena il keyring torna leggibile, al primo **Salva** o **AVVIA** il
> campo *Bot Token* viene **risincronizzato** automaticamente con la credenziale reidratata,
> così non serve reinserire il token e un salvataggio successivo non lo scambia per un clear.
> Un clear **deliberato** (campo svuotato a mano a keyring leggibile) resta definitivo.
>
> Conseguenze pratiche: proteggi comunque il tuo profilo Windows e **non condividere**
> `config.json`; se il token trapela, **rigeneralo** da @BotFather (`/revoke`). Una
> config vecchia con il token in chiaro viene **migrata** nel keyring al primo
> salvataggio (la chiave su disco torna vuota).

> Prima dell'uso reale, segui la procedura **`docs/audit/xtrader_simulation_test.md`**
> con XTrader in Modalità Simulazione, stake basso e limiti chiari. Nessuna promessa
> di profitto.

> 🧰 **Per chi sviluppa — hook pre-commit anti-segreti (opzionale).** Oltre al check CI
> *Forbidden Files* (che blocca config reali/`.env`/CSV generati/EXE e fa lo *scan dei
> segreti* — token Telegram, chiavi private PEM, AWS key id), puoi attivare lo stesso
> scan **prima di ogni commit** in locale:
> ```bash
> git config core.hooksPath .githooks
> ```
> L'hook usa `tools/secret_scan.py` (scanner **cross-platform**, la stessa fonte di pattern
> del CI; `tools/secret_scan.sh` resta come wrapper di compatibilità) e blocca il commit se un
> file in staging contiene un segreto noto — stampando **solo il path**, mai il valore.

---

## Formato CSV generato

Header ufficiale a **14 colonne** (vedi **[`docs/xtrader_csv_contract.md`](docs/xtrader_csv_contract.md)**):

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
"TelegramBot","","Inter v Milan","","Over/Under 2,5 gol","OVER_UNDER_25","","Over 2,5 goal","0","1,85","","","PUNTA",""
```

Note:

- **`BetType`**: sono validi indifferentemente **`PUNTA`/`BANCA`** (italiano) e **`BACK`/`LAY`**
  (inglese) — accettati su tutte le versioni Betting Toolkit/XTrader (conferma supporto, epica
  multilingua #3). Il bridge **scrive sempre il valore canonico italiano** `PUNTA`/`BANCA`
  (universalmente accettato), quindi un `BACK`/`LAY` in ingresso viene normalizzato a
  `PUNTA`/`BANCA`. I termini spagnoli (`FAVOR`/`CONTRA`) **non** sono ancora supportati: un lato
  sconosciuto è rifiutato (fail-closed, mai indovinare il lato).
- **`Stake`** **non** è una colonna del CSV: lo stake è gestito in XTrader.
- **Non esiste** una colonna `Timestamp`: la deduplica è interna al bridge.
- **`Points`** è lasciato vuoto; **`Handicap`** vale `0`.
- **Separatore decimale — lingua CSV (#342)**: il formato dei decimali **scritti nel file**
  (`Price`/`MinPrice`/`MaxPrice`/`Points`/`Handicap`) segue la config **`csv_language`**
  (`IT`/`EN`/`ES`, default **`IT`**): con `IT`/`ES` la **virgola** («1,85» — come richiede
  XTrader ITA attuale), con `EN` il **punto**. Internamente il bridge resta canonico col punto
  e normalizza l'input così: quota con la **virgola** → convertita (`1,85` → `1.85`); col punto →
  invariata. Con **entrambi** i separatori l'ultimo è il decimale e l'altro le migliaia,
  ma **solo** se il raggruppamento è valido (`1.234,56` → `1234.56`); un doppio separatore
  **malformato** (es. `1.2,3`) **non** viene "aggiustato": il segnale è **scartato**
  (`INVALID_PRICE`), per non scrivere un prezzo sbagliato ma plausibile.
- Encoding **UTF-8 con BOM**, tutti i valori tra virgolette (`QUOTE_ALL`).
- XTrader valida con `MarketId + SelectionId` **oppure** `EventName + MarketType +
  SelectionName`. Usando i nomi, la lingua del CSV deve coincidere con quella della
  fonte Segnali di XTrader. Gli ID non arrivano dal messaggio Telegram: con il parser
  legacy (`build_csv_row`) restano vuoti. Il flusso del Parser Personalizzato **può**
  arricchirli dal **dizionario locale**, ma dopo la rimozione di «Betfair Sync»
  l'arricchimento è **disattivato nel CSV live** (`id_resolver=None`): le righe restano a
  **nomi** (*fallback*, `recognition_mode=NAME_ONLY`) finché non popoli il dizionario a mano
  e riattivi il *seam*. Dettagli in
  [`docs/xtrader_csv_contract.md`](docs/xtrader_csv_contract.md).

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
| Diario eventi | `%APPDATA%\XTraderBridge\event_journal.jsonl` | Storico strutturato «cosa ha fatto» (vedi sotto) |
| Parser Personalizzati | `data\parsers\<nome>.json` | Definizioni dei parser |

> Al primo avvio, un vecchio `config.json` accanto all'EXE viene **migrato**
> automaticamente nella nuova posizione (l'originale non viene cancellato).
> Su Linux/macOS (dev/CI) si usa `~/.config/XTraderBridge/`.

> 📒 **Diario eventi (`event_journal.jsonl`).** Un registro **append-only** strutturato
> (una riga = un evento JSON) che ricostruisce «cosa ha fatto» il bridge, utile dopo un
> crash/riavvio: avvio/arresto (`START`/`STOP`), segnale ricevuto/validato/scritto
> (`SIGNAL_RECEIVED`/`SIGNAL_VALIDATED`/`CSV_WRITTEN`), esito XTrader
> (`XTRADER_CONFIRMED`/`XTRADER_REJECTED`), riconnessioni (`RECONNECT`) e pulizia del CSV
> all'avvio/stop (`CRASH_RECOVERY_CSV_CLEARED`/`CSV_CLEARED`). È **diagnostico e
> best-effort**: non rallenta né blocca mai il trading, i **token sono redatti** (nessun
> segreto), e lo storico è **limitato** (potato agli ultimi ~5000 eventi all'avvio).
>
> **Consultarlo** senza aprire il `.jsonl` a mano — CLI **read-only**:
> ```bash
> python -m xtrader_bridge.journal_view            # tutti gli eventi, ordinati cronologicamente (per ts)
> python -m xtrader_bridge.journal_view --last 20  # solo gli ultimi 20
> python -m xtrader_bridge.journal_view --type CSV_WRITTEN --type CSV_CLEARED
> python -m xtrader_bridge.journal_view --json     # output JSON (per script)
> ```
> Filtri combinabili: `--type` (ripetibile), `--last N`, `--since`/`--until` (epoch),
> `--path` (file alternativo). Non modifica **mai** il diario e non mostra segreti.
>
> Chi preferisce la GUI trova la stessa vista nella scheda **«📒 Diario»** dell'hub
> **🧰 Strumenti**: tabella degli ultimi N eventi (`ts` leggibile · tipo · dati redatti),
> filtro per tipo, **🔄 Aggiorna** e **📂 Apri cartella**. Anche la scheda è **read-only**
> (riusa la stessa logica della CLI): non scrive né de-redige mai il diario.

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
l'attesa lo stato mostra **RICONNESSIONE…**, poi torna **ATTIVO**. **Solo alla prima
connessione riuscita** della sessione i messaggi accumulati mentre il bridge era spento
vengono **scartati** (`drop_pending_updates`, così non si parte processando segnali vecchi);
se il primissimo tentativo fallisce, lo scarto avviene comunque al primo tentativo che va a
buon fine. Sulle **riconnessioni dopo una connessione già riuscita**, invece, il backlog
**non** viene buttato: un segnale arrivato durante un blip di rete di pochi secondi viene
**recuperato** (con una riga di log «🔄 Riconnesso…»), non perso per sempre. La protezione anti-arretrati resta comunque attiva
**a prescindere** da come avviene la riconnessione: un messaggio Telegram
**più vecchio di `max_signal_age` secondi** (default 120s, comunque non oltre la vita
della riga CSV per la modalità coda attiva — `confirmation_timeout` in
`QUEUE_UNTIL_CONFIRMED`, altrimenti `clear_delay`) viene **ignorato** all'arrivo: così,
se la rete è mancata a lungo, gli
arretrati rifetchati non diventano scommesse vecchie. Simmetricamente, un messaggio con
**timestamp nel futuro** rispetto all'orologio del PC (clock non sincronizzato) è tollerato
solo entro **60 secondi** (trattato come "adesso"); oltre viene **ignorato** come l'anti-arretrati,
perché uno scarto d'orologio grande renderebbe inaffidabile il filtro (un backlog vecchio, con il
PC indietro, sembrerebbe "fresco"). Le **conferme XTrader** dalla
chat notifiche, invece, **non** vengono filtrate per età: un esito ritardato deve
comunque rimuovere il segnale attivo. Un errore **non** recuperabile (es. **token non valido**)
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

1. **Manuale**: **Actions → «Build XTrader Signal Bridge EXE» → «Run workflow»** (scegli il
   branch). Oppure **automatico** su un **tag `v*`** (release). *Non* parte più a ogni push
   su `main`: eviti di consumare inutilmente la quota storage artifact di GitHub. I **test su
   Windows** girano nel workflow dedicato `windows-tests.yml` — **non più a ogni push/PR**
   (`windows-latest` conta 2× i minuti Actions), ma su **push in `main`/`master`**, quando una
   **label di collaudo** è presente sulla PR (`ci-full` o le label di review finale
   `final-fable-review`/`final-fugu-review`) — e, finché la label resta, **a ogni push
   successivo**, così si collauda sempre l'ultimo commit — o via **Run workflow** manuale: solo
   la **compilazione dell'EXE** è manuale/tag.
2. Actions esegue i test (bloccanti), poi compila l'EXE.
3. **Actions → la run → Artifacts**.
4. Scarica `XTrader-Signal-Bridge-Windows-v<versione>-<data>.zip`.
5. Dentro trovi `XTrader-Signal-Bridge.exe` pronto all'uso.

In locale (dev): `python main.py` avvia la GUI; `python -m pytest -q -m "not manual"`
esegue la suite offline.

**Pulizia storage artifact.** Ogni build carica un EXE (~18 MB) come artifact, con retention
**7 giorni**. Per svuotare subito il backlog **senza CLI**: Actions → *Pulizia artifact vecchi*
→ **Run workflow** (input `max_age_days=0` = elimina **tutti** gli artifact; usa il
`GITHUB_TOKEN`, niente PAT). Un run **settimanale** fa comunque pulizia automatica. Gli EXE di
**release** restano nelle **Releases** (storage separato, non-scadente).

**Build personale e sicura.** La pipeline produce **solo** l'EXE personale del bridge
(nessun secondo eseguibile «amministrativo»). L'EXE **non include segreti né certificati**: il
token del bot e la config restano **fuori** dall'eseguibile, nella cartella utente
(`%APPDATA%\XTraderBridge`); il token del bot vive nel keyring/OS. Un gate automatico
(`tests/safety/test_build_exe_safety.py`) verifica a ogni PR che la build non impacchetti
`.env`/chiavi/certificati/`config.json`/DB/token (nel bundle è ammesso solo il dizionario
ufficiale) e che i test girino prima della compilazione.

### Build EXE Nuitka (anteprima, in valutazione)

È in corso il passaggio dell'EXE ufficiale da **PyInstaller** a **Nuitka** (compilatore C:
avvio più rapido, meno falsi positivi antivirus). In questa fase **additiva** la build
PyInstaller sopra **resta quella di release**; in parallelo c'è un workflow di **anteprima**
Nuitka per validare il binario su Windows reale **prima** di ritirare PyInstaller:

- **Actions → «Build XTrader Signal Bridge EXE (Nuitka, anteprima)» → «Run workflow»** (solo
  manuale: **non** parte sui tag e **non** crea Release, così non collide con la release
  PyInstaller).
- Produce l'artifact `XTrader-Signal-Bridge-Nuitka-Windows-v<versione>-<data>` con dentro lo
  stesso `XTrader-Signal-Bridge.exe`.
- **Smoke test consigliato** dopo il download: avvia l'EXE, verifica che la GUI parta, che il
  dizionario (`data/dizionario_xtrader.csv`) sia leggibile (lookup alias→XTrader funzionante)
  e che un segnale di prova generi il CSV atteso.

Lo **stesso gate di sicurezza** copre anche la forma Nuitka (EXE singolo personale, solo il
dizionario nel bundle, nessun segreto, test prima della build). Il **lockfile riproducibile**
per Nuitka e il **ritiro di PyInstaller** arriveranno in slice successive, dopo la validazione
manuale su Windows.

---

## Dependency lockfile / build EXE riproducibile (A7)

Per rendere la build Windows dell'EXE **riproducibile e verificabile**, le dipendenze
sono espresse come file sorgente `.in` (vincoli "morbidi" top-level) da cui si genera un
**lockfile completo con hash** sulla stessa piattaforma della build.

| File | Cos'è | Si modifica a mano? |
|---|---|---|
| `requirements.in` | **sorgente unica** delle dipendenze **runtime** top-level (FLOOR `>=`, con la motivazione di sicurezza) | sì |
| `requirements-build.in` | tutto ciò che la **build Windows** installa: `-r requirements-dev.txt` (runtime + `pytest`, single-source) + `pyinstaller` (release) + `nuitka` (anteprima) + `httpx` | sì |
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
3. Apri la run → **pagina della run → Summary**: lo step *"Pubblica il lock nel Job Summary"*
   stampa il `requirements-build.lock` rigenerato in un **blocco copiabile** (è solo versioni +
   hash, nessun segreto). **Copia** l'intero blocco.
4. Incollalo nel file **`requirements-build.lock`** nella root del repo e **committalo**.

> 🛟 **Consegna quota-immune (nessun artifact):** il lock si recupera **solo dalla Summary**, non
> da un artifact. Così la generazione/validazione del lock **non dipende dalla quota storage
> artifact** (che prima faceva fallire l'`upload-artifact` con `Failed to CreateArtifact:
> Artifact storage quota has been hit` e teneva rosso il check anche con un lock corretto). Il
> check ora è verde/rosso solo in base alla **correttezza** del lock (git-diff anti-stantio +
> validazione `--require-hashes`).
>
> **Fine-riga:** incolla pure il blocco così com'è — il gate anti-stantio usa
> `git diff --ignore-cr-at-eol`, quindi il lock incollato dalla Summary (LF, come normalizza il
> browser) combacia con la rigenerazione su Windows (CRLF): conta solo il **contenuto**
> (versioni/hash). Una volta committato, il lock vive **in git** (fonte di verità permanente):
> nessun "storico" da recuperare dagli artifact.

### Effetto sulla build

`build.yaml` rileva automaticamente il lock:

- se **`requirements-build.lock` è presente** → installa **solo** da lì con
  `python -m pip install --require-hashes -r requirements-build.lock` (riproducibile);
- se **assente** → install legacy (`requirements-dev.txt` + `pyinstaller httpx`), così la
  build non si rompe finché il lock non è stato committato.

`build-nuitka.yaml` (build EXE **anteprima** Nuitka) usa lo **stesso** lock unificato, con un
controllo in più: installa `--require-hashes` **solo se il lock contiene già `nuitka`**
(cioè è stato rigenerato dopo l'aggiunta a `requirements-build.in`); altrimenti ripiega su un
install legacy con **`nuitka` pinnato** a una versione esatta (build funzionante, nessun drift)
finché non rigeneri e committi il lock.

> ℹ️ **Aggiungere `nuitka` al lock** (fatto in `requirements-build.in`) rende il
> `requirements-build.lock` committato **stantio**: il check *Generate Windows Lockfile* resta
> **rosso** finché non lo rigeneri su Windows e lo ricommitti (segui *Come (ri)generare il
> lockfile* qui sopra: la run pubblica il lock corretto nel **Job Summary**, da cui lo copi e
> lo committi). È il segnale atteso, non un errore.

La compilazione dell'EXE con **PyInstaller** resta invariata.

---

## Review e audit AI (GitHub Actions)

Sei workflow opzionali usano modelli AI come **filtro tecnico aggiuntivo**. Due
reviewer **automatici** (**GPT-5.5** con `OPENAI_API_KEY`, **GLM 5.2** con
`OPENROUTER_API_KEY`) commentano ogni push della PR analizzando **solo il range
appena pushato**; due reviewer **forti** (**Claude Fable 5** con
`ANTHROPIC_API_KEY`, **Fugu Ultra** con `OPENROUTER_API_KEY`) — più costosi —
partono automaticamente **solo su push che toccano file core del bridge**
(`main.py`, `xtrader_bridge/**`, dipendenze) analizzando il push-range, **oppure**
quando viene aggiunta una label (`final-fable-review` / `final-fugu-review`) per
rivedere l'intera PR come cancello pre-merge; su push che toccano solo
workflow/docs/test non spendono; due **audit full-repo** (GPT-5.5 /
Claude Fable 5), avviabili **solo a mano** da *Actions → Run workflow*,
scansionano il repository in sola lettura producendo un report scaricabile.
Tutto diff-only/read-only: niente checkout, nessuna esecuzione del codice della
PR; nessuno modifica codice, apre PR, approva o merge — il merge resta manuale.
I reviewer sono opzionali: ognuno gira solo se il **suo** secret è presente,
altrimenti viene saltato senza far fallire la PR. Dettagli, invarianti di
sicurezza e valori consigliati: **`docs/ai_audit_workflows.md`**.

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
└── .github/workflows/      ← CI + build EXE Windows + lockfile + review/audit AI
```

---

## Autore

Sviluppato su misura per l'uso con **XTrader** di
[TradingSportivo.club](https://assistenza.tradingsportivo.club/).

*XTrader Signal Bridge — ponte tra segnali Telegram e XTrader. Il merge resta
sempre manuale del proprietario.*
