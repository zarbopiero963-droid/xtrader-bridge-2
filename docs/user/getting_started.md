# Primi passi — configurare XTrader Signal Bridge

> Guida **utente**. XTrader Signal Bridge legge i segnali dalle chat Telegram che scegli, li
> trasforma in una riga CSV nel formato di XTrader e la scrive nel file che XTrader legge. Di
> default parte in **Simulazione** (non scrive scommesse reali): è il modo sicuro per provare tutto.

> 📸 *Gli screenshot di questa guida verranno aggiunti in `docs/assets/screenshots/` (catturati su
> Windows). I riferimenti «\[screenshot: …\]» qui sotto indicano dove andranno.*

## 1. Al primo avvio: scegli la lingua

Alla **prima apertura** compare la finestra **«🌐 Scegli la lingua del bridge»** con un pulsante per
lingua (**Italiano / English / Español**). La scelta imposta la lingua dell'app e allinea il
separatore decimale del CSV. Se chiudi senza scegliere, resta l'italiano e la finestra ricompare al
prossimo avvio. \[screenshot: selettore lingua\]

## 2. Compila i campi essenziali (tab **⚙️ Generale**)

Nella finestra principale, nella tabview di configurazione, apri **⚙️ Generale** e compila:

| Campo | A cosa serve |
|---|---|
| **🔑 Bot Token** | Il token del bot Telegram (da **@BotFather**). Senza, **AVVIA** è bloccato. È un segreto: viene salvato nel **keyring del sistema** (Windows Credential Manager). Solo se **non** è disponibile alcun keyring, ripiega sul token in chiaro in `config.json` con un **avviso** nel log. |
| **💬 Chat ID** | L'ID della chat/canale **sorgente** dei segnali (es. `-1001234567890`). Definisce **quali** messaggi vengono accettati. |
| **📄 CSV Path** | Il percorso del file CSV che **XTrader legge** (es. `C:\XTrader\segnali.csv`). La cartella deve esistere. |
| **⏱️ Timeout** | Dopo quanti secondi il CSV viene **svuotato** (torna a solo header) dopo un segnale. |

Salva con **💾 Salva Config**.

## 3. Verifica con il **🧙 Wizard prima configurazione**

Dalla barra **🧰 Strumenti** apri **«🧙 Wizard prima configurazione»**: ti guida in **5 passi** e
verifica *dal vivo* che tutto sia a posto, senza attivare nulla di pericoloso:

1. **Token + connessione** — controlla il token chiamando Telegram (`getMe`). Il token non compare
   mai nei messaggi/errori.
2. **Chat ID + messaggio di prova** — invii un messaggio di prova nella chat sorgente e premi
   «Controlla ora»: il wizard conferma che è arrivato da quella chat.
3. **Parser su un messaggio reale** — incolli un segnale reale del canale: il wizard mostra
   l'anteprima della riga CSV che verrebbe scritta.
4. **CSV** — verifica il percorso e, su tua richiesta, scrive un CSV **di prova a solo header** (non
   sovrascrive mai un file con una riga attiva).
5. **Checklist finale** — riepilogo prima di partire. **Il wizard non attiva mai la modalità reale.**

\[screenshot: wizard 5 passi\]

## 4. Avvia in **Simulazione** (sicuro)

Premi **▶ AVVIA**: il bridge inizia ad ascoltare la chat sorgente. In **Simulazione** (default) il
**CSV operativo non viene scritto** — puoi verificare tutto il flusso senza rischi. La tab
**🚦 Salute** mostra 7 semafori (Telegram, messaggio, parser, CSV, modalità…): usa quelli per capire
cosa manca. **■ STOP** ferma l'ascolto; **🗑️ Svuota CSV ora** riporta il CSV a solo header.

> Per lo START servono **token**, **chat**, **un Parser Personalizzato attivo** e un **CSV
> utilizzabile**. Se manca il parser, lo START è bloccato (semaforo parser rosso).

## 5. Passare a modalità reale (solo quando sei sicuro)

Il passaggio a **Collaudo/Reale** avviene **solo** dalla tab **🛡️ Sicurezza**, con i suoi **gate di
conferma** (una frase da digitare). In modalità reale un **banner rosso «MODALITÀ REALE ATTIVA»**
resta visibile in alto. Finché non lo fai tu, esplicitamente, resti in Simulazione.

## E se non sai da dove iniziare?

Usa l'**assistente di configurazione** (tab **🤖 Assistente**): chiedigli *«cosa manca per
partire?»* e ti dice quali requisiti sono a posto e quali no, e ti guida a compilarli. Vedi
**[Assistente di configurazione](assistente.md)**.

## Dove finiscono i file

Config e cronologia stanno nella cartella dati utente (`%APPDATA%\XTraderBridge` su Windows). La
**API key** dell'assistente sta **solo nel keyring** (se il keyring non è disponibile, **non** viene
salvata). Il **bot token** sta nel keyring, con l'eccezione del fallback in chiaro sopra descritto se
manca un keyring. Il CSV operativo sta dove indichi in **CSV Path**.

> 🔒 **Se il token finisce in chiaro** (fallback senza keyring): tratta `config.json` come un file
> **riservato** — non condividerlo, non allegarlo a segnalazioni/diagnostica, e preferisci una
> cartella **non** sincronizzata su cloud (OneDrive/Drive). La soluzione migliore resta avere un
> backend keyring disponibile, così il token non tocca mai il disco in chiaro.
