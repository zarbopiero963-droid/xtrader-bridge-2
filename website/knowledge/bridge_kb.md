# BetRelay (già XTrader Signal Bridge) — Knowledge base per il supporto

## Cos'è
BetRelay — nome commerciale del programma nato come «XTrader Signal Bridge» — è un programma desktop Windows che fa da ponte tra i messaggi di
una chat/canale Telegram e il software XTrader di TradingSportivo. Catena:
Telegram → parsing → CSV → XTrader legge → CSV pulito.
Il bridge NON piazza scommesse: scrive solo il file CSV che XTrader monitora; è XTrader
a piazzare. Di default parte in Simulazione (dry_run): riconosce i segnali ma NON scrive
il CSV operativo.

## Famiglia di software di destinazione (Betting Toolkit Network)
Il bridge è nato per XTrader (Italia, TradingSportivo), ma la stessa casa madre distribuisce
lo stesso programma per altri mercati: BETTINGTOOLKIT.COM (World), BETTINGTOOLKIT.ES (Spagna),
BETTINGTOOLKIT.LAT (America Latina). Il bridge è compatibile con tutta la famiglia: il CSV ha
lo stesso contratto a 14 colonne. Il bridge supporta le lingue IT/EN/ES: al primo avvio si
sceglie la lingua, e la lingua CSV allinea il separatore decimale (virgola per IT/ES, punto
per EN) al palinsesto del software di destinazione. Importante: nel software (XTrader/Betting
Toolkit) la LINGUA DELLA FONTE va impostata uguale a quella scelta nel bridge, perché col
riconoscimento a nomi i nomi dipendono dalla lingua del palinsesto.

## Requisiti
- Windows 10/11 a 64 bit (l'EXE include tutto, non serve Python).
- XTrader installato sulla STESSA macchina (bridge e XTrader comunicano tramite file CSV locale).
- Bot Telegram: token creato con @BotFather; bot aggiunto alla chat/canale sorgente; Chat ID
  della chat (es. -1001234567890).
- Connessione internet. Conto Betfair attivo per XTrader.
- Per il 24/7: VPS Windows (2 vCPU, 4 GB RAM, 50 GB SSD) con autologon e avvio automatico;
  se il conto è Betfair.it, preferire un VPS in Italia.

## Configurazione essenziale (tab ⚙️ Generale)
- 🔑 Bot Token: da @BotFather; salvato nel keyring di Windows (Credential Manager), non in chiaro.
- 💬 Chat ID: chat/canale sorgente dei segnali. Il bridge ascolta SOLO le chat configurate.
- 📄 CSV Path: percorso del CSV che XTrader legge (es. C:\XTrader\segnali.csv); la cartella deve
  esistere. Pulsanti «📁 Sfoglia…» e «📄 Crea CSV» (genera un CSV a solo header, con conferme
  anti-sovrascrittura).
- ⏱️ Timeout (sec): dopo quanti secondi il CSV viene svuotato (torna a solo header). Default 90.
- 🏷️ Provider: nome della fonte nella colonna Provider del CSV.
Salvare con 💾 Salva Config. Config in %APPDATA%\XTraderBridge\config.json.

## Wizard prima configurazione (🧙)
5 passi con verifiche dal vivo: 1) token + prova connessione (getMe); 2) Chat ID + messaggio di
prova; 3) parser su un messaggio reale con anteprima riga CSV; 4) verifica percorso CSV + CSV di
prova a solo header; 5) checklist finale. Non attiva mai la modalità Reale; il token non compare
mai negli esiti.

## Parser Personalizzato (🧰 Strumenti → 🧩 Parser)
Insegna al bridge a leggere il formato del TUO canale. Per ogni colonna del CSV (Provider,
EventName, MarketType, SelectionName, Price, BetType, ecc.) si definisce come estrarla:
«Inizia dopo» / «Finisce prima», valore fisso, trasformazioni, value-map. Modalità di
riconoscimento: NAME_ONLY (nomi tradotti dai dizionari), ID_ONLY (servono MarketId/SelectionId),
BOTH. «🧪 Prova messaggio» mostra anteprima e diagnostica riga-per-colonna. Il parser non inventa
dati: se un campo obbligatorio manca, nessuna riga piazzabile viene prodotta. Senza un Parser
Personalizzato attivo lo START è bloccato. Output multi-riga: MultiMarket e MultiSelection
(dutching) — un messaggio può generare un blocco di più righe, mai spezzato dai limiti.

## Dizionari e mapping (🗺️)
- Dizionario nomi squadra: traduce i nomi come li scrive il canale nel nome atteso da
  Betfair/XTrader, organizzati in profili selezionabili nel parser.
- Dizionario mercati: ritaglia il testo-mercato dal messaggio e lo mappa su Mercato/Selezione
  del catalogo.
- Mapping guidato (🌳): albero Sport → Competizione → Squadre per scrivere gli alias del canale.

## Modalità (tab 🛡️ Sicurezza)
- 🧪 Simulazione Bridge (default): NON scrive il CSV operativo.
- 🔬 Collaudo XTrader: scrive il CSV; XTrader deve essere in Modalità Simulazione. Conferma
  Sì/No; banner AMBRA persistente.
- ⚠️ Reale: scommesse vere. Richiede di DIGITARE la parola REALE; banner ROSSO persistente
  «MODALITÀ REALE ATTIVA»; conferma Sì/No a OGNI avvio del listener (anche con auto-start).
Altre protezioni: limite segnali al giorno (default 200), anti-duplicato persistente, modalità
coda (OVERWRITE_LAST un solo segnale attivo / APPEND_ACTIVE / QUEUE_UNTIL_CONFIRMED con
conferma per le modalità multi), max segnali attivi, avvio automatico opzionale (default OFF).

## CSV (contratto XTrader)
Header a 14 colonne, ordine fisso:
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,
Price,MinPrice,MaxPrice,BetType,Points.
Scrittura atomica (mai file parziali); una sola riga attiva nel design one-signal-at-a-time;
dopo il timeout il CSV torna a SOLO header; dopo un crash/blackout un CSV stantio viene
ripulito al successivo avvio. XTrader non vede mai segnali vecchi.
Formato del file: nomi colonna sulla prima riga, tutti i valori fra doppi apici, UTF-8 con BOM.
BetType: il bridge scrive PUNTA (back) / BANCA (lay); XTrader e Betting Toolkit accettano
indifferentemente PUNTA/BANCA e BACK/LAY in tutte le versioni — non c'è nulla da convertire.
Separatore decimale: il software accetta sia virgola sia punto; il bridge allinea il file alla
lingua scelta, quindi non è una causa plausibile di segnale non riconosciuto.
Points: moltiplicatore dello stake, usato solo se la strategia attiva l'opzione; lasciato vuoto.
Perché lo svuotamento è necessario: una fonte con aggiornamento automatico rilegge il file a ogni
ciclo, quindi una riga vecchia lasciata sul disco verrebbe reintrodotta dal software anche dopo
averla cancellata a mano.

## Lato XTrader: come legge i segnali
XTrader legge i segnali da un URL che serve un CSV oppure da un FILE CSV locale (è il caso del
bridge). Ogni fonte ha: nome, percorso/url, aggiornamento automatico + intervallo, esclusione
automatica dei segnali non validi, algoritmo di riconoscimento e lingua.
Riconoscimento (si sceglie nelle proprietà della fonte): per ID (MarketId + SelectionId, devono
coincidere col palinsesto Betfair della giurisdizione del conto) oppure per NOMI (EventName +
MarketType + SelectionName). Con il metodo a nomi la lingua della fonte deve corrispondere a
quella con cui il software legge il palinsesto: è la causa tipica del segnale che resta rosso.
Segnale valido = icona verde, non valido = icona rossa (evento concluso, dati incompleti o
incoerenti col palinsesto). Una strategia usa ogni segnale UNA sola volta per esecuzione.
La documentazione completa di XTrader è sul sito, pagina /documentazione (manuale PDF ufficiale
ospitato con autorizzazione dell'autore). BetRelay è un progetto indipendente, non affiliato a
TradingSportivo.

## Conferme XTrader (tab ✅)
Configurando la chat notifiche di XTrader, il bridge legge gli esiti: scommessa confermata o
rifiutata → il segnale viene rimosso subito dal CSV senza aspettare il timeout. Parole di
conferma/rifiuto personalizzabili; timeout conferma default 120s.

## Monitoraggio
- Header: stato ⬤ OFFLINE (rosso) / ⬤ ATTIVO (verde) / ⬤ RICONNESSIONE… (arancione);
  «Righe attive: N/M».
- 🚦 Salute: 7 semafori (Telegram, Ultimo messaggio, Parser, Ultimo segnale, CSV scrivibile,
  Conferme XTrader, Modalità). Dato assente = giallo onesto, mai verde.
- 📡 Stato: ultimo segnale/messaggio/CSV/errore/conferma. 📊 Dashboard: 7 contatori.
- 📋 Log: righe [HH:MM:SS] [LIVELLO] con filtro e retention; i token sono sempre redatti.

## FAQ
- Devo tenere il programma aperto? Sì, in background (minimizzabile) mentre vuoi ricevere segnali.
- Può partire da solo? Sì: auto_start_listener (tab Sicurezza); in Reale chiede prima conferma.
- Cade la connessione? Riconnessione automatica con backoff (2s→60s), stato RICONNESSIONE…;
  messaggi più vecchi di max_signal_age (default 120s) ignorati: niente scommesse vecchie.
  Errore non recuperabile (token non valido) → il bridge si ferma e mostra l'errore.
- Più canali? Sì: 🧰 Strumenti → 📡 Chat sorgenti (multi-chat, ognuna col suo parser).
- Scommesse ripetute? No: un solo segnale attivo + timeout + svuotamento.
- Non parte? Cause tipiche: token mancante, CSV Path mancante, Timeout non valido, nessuna
  chat configurata, nessun Parser Personalizzato attivo. Il motivo esatto è nel log.
- Non scrive nel CSV? In Simulazione è normale: passare a Collaudo/Reale (con i gate).
- Impostazioni dove? %APPDATA%\XTraderBridge\config.json.
- Due istanze? No: la seconda viene rifiutata all'avvio (rischio scommesse doppie).

## Assistenza
Per problemi non coperti: pagina Contatti del sito. Non condividere MAI token o dati del
conto in chat.
