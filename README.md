# XTrader Signal Bridge
> **Converte automaticamente i segnali Telegram in scommesse automatiche su XTrader**
---
## Cos'è XTrader Signal Bridge?
XTrader Signal Bridge è un programma desktop per Windows che fa da **ponte intelligente** tra i messaggi di un canale o chat Telegram e il software **XTrader** di TradingSportivo.
In pratica: ricevi un segnale su Telegram → il programma lo legge → scrive automaticamente il CSV nel formato corretto → XTrader piazza la scommessa da solo → il CSV viene svuotato per essere pronto al prossimo segnale.
**Non devi fare nulla a mano.** Tutto avviene in automatico, in pochi secondi.
---
## Come funziona — Flusso completo
``` Messaggio Telegram (canale segnali P.Bet.)          │          ▼ XTrader Signal Bridge (gira sul tuo PC)   • Riceve il messaggio via Bot API   • Analizza e riconosce i dati del segnale   • Estrae: squadre, campionato, mercato, quota          │          ▼ segnali.csv  ←── XTrader monitora questo file   (scritto nel formato esatto richiesto da XTrader)          │          ▼ XTrader legge il CSV e piazza la scommessa automatica          │          ▼ Dopo N secondi (configurabile, default 90s)          │          ▼ CSV svuotato (rimane solo l'intestazione)          │          ▼ Pronto per il prossimo segnale```
---
## Formato segnale Telegram riconosciuto
Il programma riconosce automaticamente i messaggi nel formato **P.Bet.**, ad esempio:
```P.Bet. GOL SECONDO TEMPO LIVE  
 Myanmar National League 2 Yangon City v Silver Stars FC 6 - 0 46m Tiri in Porta  15-1 Tiri Fuori  3-0Possesso Palla: 59-41
 Quota 0,5 HT Prematch: 0 81.29%```
Il bridge estrae automaticamente:
| Dato | Estratto da ||------|------------|| **Campionato** | riga con || **Squadre** | riga con || **Mercato** | prima riga del messaggio (es. GOL SECONDO TEMPO) || **Quota** | riga con || **Punteggio live** | riga con || **Minuto** | riga con |
---
## Formato CSV generato per XTrader
Il CSV viene scritto nel formato richiesto da XTrader per i segnali esterni. L'header ufficiale ha **12 colonne** (vedi `docs/xtrader_csv_contract.md`):

```csv
Provider,SelectionId,MarketId,SelectionName,MarketName,EventName,MarketType,BetType,Price,MinPrice,MaxPrice,Points
PBet,,,Inter,MATCH ODDS,Inter v Milan,MATCH_ODDS,BACK,1.85,,,1
```

Note:
- **`Stake`** non è una colonna del CSV: è gestito in XTrader nell'azione "Piazza Scommessa su Segnali".
- Non esiste una colonna `Timestamp`: la protezione anti-duplicato è interna al bridge.
- **`Points`** è il moltiplicatore dello stake (default `1`).
- XTrader può validare il segnale tramite `MarketId + SelectionId` **oppure** `EventName + MarketType + SelectionName`; usando i nomi, la lingua del CSV deve coincidere con quella della fonte Segnali di XTrader.

> **Il CSV contiene sempre un solo segnale alla volta.** Dopo il timeout viene svuotato e XTrader non rischia di ripetere scommesse vecchie.
---
## L'interfaccia grafica
Il programma si apre come una normale finestra Windows con:
- ** Bot Token** — inserisci il token del tuo bot Telegram- ** Chat ID** — inserisci l'ID del canale/chat dei segnali- ** CSV Path** — il percorso del file CSV che XTrader monitora (es. `C:\XTrader\segnali.csv`)- ** Timeout (secondi)** — dopo quanti secondi svuotare il CSV (default: 90)- ** START / STOP** — avvia o ferma il bridge- ** Log in tempo reale** — vedi ogni segnale ricevuto e processato
---
## Configurazione iniziale (una sola volta)
### Passo 1 — Crea il Bot Telegram1. Apri Telegram e cerca **@BotFather**2. Scrivi `/newbot` e segui le istruzioni3. Copia il **token** che ti viene dato (es. `123456789:AAFxxx...`)
### Passo 2 — Aggiungi il bot al canale segnali1. Vai nel canale dove ricevi i segnali P.Bet.2. Aggiungi il tuo bot come **amministratore** (almeno con permesso di lettura messaggi)
### Passo 3 — Trova il Chat ID del canaleApri nel browser (sostituendo il tuo token):```https://api.telegram.org/bot<TUOTOKEN>/getUpdates```Cerca nel risultato il numero dopo `"chat":{"id":` — quello è il tuo Chat ID (di solito negativo per i canali, es. `-1001234567890`)
### Passo 4 — Configura XTraderIn XTrader, nella sezione **Segnali**, imposta come sorgente il file CSV:```C:\XTrader\segnali.csv```e abilita il **refresh automatico** (consigliato ogni 10-15 secondi).
### Passo 5 — Avvia il Bridge1. Apri `XTrader-Signal-Bridge.exe`2. Inserisci Token, Chat ID e percorso CSV3. Clicca ** START**4. Da questo momento tutto è automatico!
---
## Sicurezza anti-scommessa doppia
Il sistema è progettato per **non rischiare mai** di piazzare due volte la stessa scommessa:
1. **Un segnale alla volta** — il CSV viene svuotato prima di scrivere un nuovo segnale2. **Timeout automatico** — anche se XTrader non legge il CSV, dopo N secondi viene comunque svuotato3. **Timestamp univoco** — ogni segnale ha un timestamp che XTrader usa per verificare i duplicati4. **Lock file** — durante la scrittura del CSV viene usato un lock per evitare scritture concorrenti
---
## Requisiti di sistema
| Requisito | Dettaglio ||-----------|-----------|| **Sistema operativo** | Windows 10 / 11 (64-bit) || **XTrader** | Versione con supporto Segnali CSV esterni || **Connessione internet** | Necessaria per ricevere i messaggi Telegram || **Bot Telegram** | Creato tramite @BotFather con token valido || **Dipendenze Python** | Già incluse nell'EXE — non serve installare nulla |
---
## Domande frequenti
**Q: Devo tenere il programma aperto tutto il tempo?**Sì, il bridge deve girare in background mentre vuoi ricevere segnali. Puoi minimizzarlo, non occupa risorse.
**Q: Cosa succede se perdo la connessione internet?**Il bridge si riconnette automaticamente. Nessun segnale va perso durante la riconnessione.
**Q: Posso usarlo con più canali Telegram?**Attualmente supporta un canale alla volta. Per più canali, contatta lo sviluppatore.
**Q: XTrader continua a fare scommesse vecchie?**No — grazie al timeout e al clear automatico del CSV, XTrader vede sempre solo il segnale più recente o nessun segnale se il timeout è scaduto.
**Q: Dove vengono salvate le impostazioni?**In un file `config.json` nella stessa cartella dell'EXE. Vengono caricate automaticamente al prossimo avvio.
---
## Struttura del progetto
```xtrader-bridge/├── main.py                    ← Codice sorgente principale├── requirements.txt           ← Dipendenze Python├── README.md                  ← Questo file└── .github/    └── workflows/        └── build.yml          ← GitHub Actions: compila l'EXE su Windows```
---
## Come compilare l'EXE (sviluppatori)
Il progetto usa **GitHub Actions** per compilare automaticamente l'EXE su Windows:
1. Fai un push sul branch `main`2. GitHub Actions avvia automaticamente la build3. Vai su **Actions → ultima run → Artifacts**4. Scarica `XTrader-Signal-Bridge-Windows.zip`5. Dentro trovi `XTrader-Signal-Bridge.exe` pronto all'uso
---
## Autore
Sviluppato su misura per l'utilizzo con **XTrader** di [TradingSportivo.club](https://assistenza.tradingsportivo.club/)
---
*XTrader Signal Bridge — Automazione scommesse sportive tramite segnali Telegram* 
