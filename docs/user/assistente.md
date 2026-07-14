# Assistente di configurazione (🤖)

> Guida **utente**. L'assistente è una **chat a linguaggio naturale** che ti aiuta a **configurare**
> il bridge: legge lo stato, ti dice cosa manca, e può proporre alcune impostazioni non critiche —
> sempre con una **tua conferma** prima di scrivere. È uno strumento **personale del proprietario**,
> non una chat per utenti finali.

> 📸 *Gli screenshot verranno aggiunti in `docs/assets/screenshots/`. I «\[screenshot: …\]» indicano dove.*

## Dove si trova

Nella finestra principale, tabview di **monitoraggio**, tab **«🤖 Assistente»**. \[screenshot: tab assistente\]

## 1. Salva la API key Anthropic

L'assistente parla con un modello Anthropic, quindi serve una **API key**. Incollala nel campo
mascherato **«API key Anthropic:»** e premi **«💾 Salva chiave»**: viene salvata **solo nel keyring
del sistema** (mai in `config.json`, nei log o nella cronologia); il campo si svuota subito.

## 2. Abilita / Stop

- **«▶ Abilita»** avvia la chat. L'indicatore diventa **🟢 Assistente ATTIVO** e il campo di input si
  abilita. Senza API key salvata vedrai invece **🔴 Assistente in ERRORE** con il motivo, e
  l'assistente resta spento.
- **«⏹ Stop»** (o la chiusura della finestra) ferma l'assistente.
- A riposo lo stato è **⚪ Assistente OFFLINE**.

Scrivi nel campo **«scrivi un ordine di configurazione…»** e premi **«Invia»** (o `Invio`). Le righe
appaiono come **«🧑 Tu: …»** e **«🤖 Assistente: …»**. La conversazione è salvata **sempre redatta**
su disco (token/chat/API key non compaiono mai in chiaro).

## 3. Guida alla prima configurazione

Chiedi all'assistente *«cosa manca per partire?»*: ti elenca i **requisiti dello START** (token,
chat, parser attivo, CSV) come **configurato sì/no** — **senza mai mostrare** i valori di token o
chat — più la modalità (informativa: lo START gira anche in Simulazione). Poi ti guida:

- per le **impostazioni non critiche** te le **propone** (vedi sotto);
- per i **campi critici** (token, chat, percorso CSV, parser, modalità) ti **spiega** come compilarli
  nei campi della finestra o ti indirizza al pulsante **«🧙 Wizard prima configurazione»** — non li
  compila lui.

## 4. Proporre una modifica: tu confermi con «✅ Applica»

L'assistente può **proporre** modifiche a **poche impostazioni non critiche**:

- **tema** (chiaro/scuro), **lingua dell'app** (IT/EN/ES),
- **clear_delay** (svuotamento CSV), **confirmation_timeout** (attesa conferma XTrader),
- **max_signal_age** (scarto messaggi vecchi).

Quando propone qualcosa **non lo applica da solo**: compare un **banner** con l'anteprima
(«L'assistente propone: «‹chiave›» da «‹vecchio›» a «‹nuovo›». Applicare?») e due pulsanti
**«✅ Applica»** / **«✖ Annulla»**. La modifica viene scritta **solo se premi tu «✅ Applica»**.
\[screenshot: banner conferma\]

## 5. Cosa l'assistente NON può fare (per sicurezza)

Anche se glielo chiedi esplicitamente, l'assistente **non può**:

- piazzare scommesse, comunicare con XTrader/Betfair, avviare l'ascolto **live** o la **modalità
  reale**, scrivere il **CSV operativo**;
- modificare il **bot token**, il **filtro chat** (chat sorgente/notifiche), il **percorso CSV**, la
  **modalità**, i **limiti sulle scommesse** o il **parser attivo**;
- rivelare segreti (token, API key, chat ID), usare il web o eseguire comandi.

Queste azioni sono **bloccate dal bridge a prescindere**. Abilitare la chat **non** avvia mai
l'ascolto live né la modalità reale.

## In breve

L'assistente **legge** e **consiglia**, **propone** solo impostazioni non critiche, e **tu**
confermi ogni scrittura. Per la configurazione vera e propria dei campi critici usa i campi della
finestra e il **[Wizard](getting_started.md#3-verifica-con-il--wizard-prima-configurazione)**.
