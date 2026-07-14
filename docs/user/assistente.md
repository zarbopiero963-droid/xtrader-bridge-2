# Assistente di configurazione (🤖)

> Guida **utente**. L'assistente è una **chat a linguaggio naturale** che ti aiuta a **configurare** e
> a **capire** il bridge: legge lo stato, ti dice cosa manca, **spiega** qualunque pulsante/campo/
> concetto dalla documentazione reale, **prova** un messaggio col parser attivo (mostrando la riga CSV
> che uscirebbe, senza scrivere), **consulta** il dizionario (squadre/mercati/mapping), **spiega la
> salute** (7 semafori) e **perché un segnale è stato scartato**, e può proporre alcune impostazioni
> non critiche — sempre con una
> **tua conferma** prima di scrivere. Risponde nella **lingua** scelta all'avvio. È uno strumento
> **personale del proprietario**, non una chat per utenti finali.

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

## 4. Chiedigli di spiegarti qualunque cosa del bridge

L'assistente conosce la **documentazione reale** del bridge e può spiegarti **qualunque**
pulsante, campo, impostazione o concetto — parser personalizzato, contratto CSV di XTrader,
modalità, semafori di salute, sicurezza, diario eventi. Chiedi pure *«a cosa serve il campo
Timeout?»*, *«come funziona il parser personalizzato?»*, *«cosa significa modalità reale?»*.

Sa anche spiegarti **come** si fanno le azioni che lui **non può** eseguire (avviare l'ascolto
live, passare a modalità reale, impostare token/chat/CSV/parser/limiti): ti **guida passo passo**,
spiegando anche le conseguenze, ma **non le esegue lui**. Basa le risposte sulle guide reali, non
inventa.

> 🔒 **Segreti:** l'assistente **non ti chiederà mai** di incollare token, API key o chat ID nella
> chat, e **non li mostra**: ti dice soltanto **dove** inserirli nella finestra.

**Lingua.** L'assistente risponde nella **lingua scelta all'avvio** (Italiano / English / Español).
Se cambi la lingua dell'app, la nuova lingua vale dalla **successiva** riabilitazione dell'assistente.

## 5. 🧪 Prova un messaggio (senza scrivere nulla)

Incolla un messaggio del canale e chiedi *«questo va bene?»* o *«cosa uscirebbe nel CSV?»*:
l'assistente lo **prova col parser attivo** e ti dice:

- se è **riconosciuto** (sì/no) e, se no, **perché** (es. manca la quota, campo obbligatorio non
  trovato, parser non riconosce il formato);
- l'**anteprima della riga CSV** che uscirebbe — **colonne e valori** — con il **separatore decimale**
  giusto per la lingua CSV impostata (virgola per IT/ES, punto per EN);
- puoi anche incollarne **più di uno** separandoli con una riga che contiene solo `---`.

È tutto **in sola lettura**: l'assistente **non scrive** il CSV operativo, prova soltanto. Puoi usarlo
come **tester** mentre sistemi il parser, finché la riga non è quella giusta.

> ℹ️ L'anteprima è **prudente**: senza il dizionario Betfair, un parser che ricava gli ID dal
> dizionario può risultare «non pronto» qui anche se, a bridge avviato, verrebbe scritto. Non mostra
> mai «pronto» qualcosa che a runtime verrebbe scartato.

## 6. 📖 Consulta il dizionario (squadre, mercati, mapping)

Chiedi *«come è mappata la Juventus?»*, *«che mercati conosce il bridge?»*, *«cosa significa questo
alias?»*: l'assistente cerca nel **dizionario XTrader** e nei tuoi **profili di mapping** e ti spiega
**come sono mappati** — in sola lettura. Ti mostra:

- dal **dizionario XTrader**: l'alias Telegram → i valori esatti di XTrader (tipo mercato, nome
  mercato, selezione, BetType PUNTA/BANCA, handicap);
- dai tuoi **profili nomi**: squadra/alias → **nome Betfair**;
- dai tuoi **profili mercati**: la frase → mercato/selezione;
- dalle **value-map** (es. BACK → PUNTA).

Senza indicare un termine ti dà la **panoramica** («cosa conosce il bridge»: mercati, profili,
value-map). Se il dizionario non è incluso nell'installazione te lo dice, e i tuoi profili restano
comunque consultabili.

## 7. 🚦 Come sta il bridge? · 🩺 Perché è stato scartato?

Chiedi *«come sta il bridge?»*, *«cosa manca per funzionare?»*, *«perché è rosso?»*: l'assistente
legge i **7 semafori di salute** (Telegram, ultimo messaggio, parser, ultimo segnale, CSV, conferme,
modalità) e per ognuno ti dice lo **stato** e, se non è verde, **cosa fare**. Vede lo stesso stato
che trovi nella tab **🚦 Salute**.

Chiedi *«perché è stato scartato?»* / *«perché non è arrivato al CSV?»*: legge il **diario eventi** e
ti spiega il **ciclo di vita** dell'ultimo segnale (ricevuto → parsato → validato → scritto), se è
arrivato al CSV o no, più eventuali rifiuti/riconnessioni. Per il **motivo esatto** (duplicato,
troppo vecchio, parser non riconosciuto, CSV non scrivibile) combina il diario con l'**«ultimo
errore»** dei semafori. Tutto in **sola lettura**.

## 8. Proporre una modifica: tu confermi con «✅ Applica»

L'assistente può **proporre** modifiche a **poche impostazioni non critiche**:

- **tema** (chiaro/scuro), **lingua dell'app** (IT/EN/ES),
- **clear_delay** (svuotamento CSV), **confirmation_timeout** (attesa conferma XTrader),
- **max_signal_age** (scarto messaggi vecchi).

Quando propone qualcosa **non lo applica da solo**: compare un **banner** con l'anteprima
(«L'assistente propone: «‹chiave›» da «‹vecchio›» a «‹nuovo›». Applicare?») e due pulsanti
**«✅ Applica»** / **«✖ Annulla»**. La modifica viene scritta **solo se premi tu «✅ Applica»**.
\[screenshot: banner conferma\]

## 9. Cosa l'assistente NON può fare (per sicurezza)

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
