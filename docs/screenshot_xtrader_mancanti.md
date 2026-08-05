# Screenshot XTrader che mancano — lista della spesa

Cosa serve fotografare in XTrader per completare guide e demo, **in ordine di utilità reale**.
Il proprietario ha già fornito 102 screenshot (catalogati in
`website/static/docs/strategie-xtrader/catalogo.md`); questa è la lista di ciò che **non** c'è.

Per ogni voce: **cosa manca**, **cosa sblocca** e **cosa oggi è ricostruito o simulato** al suo
posto. Le voci P1 sono quelle dove al momento c'è materiale *non verificato* sul sito: sono le
uniche che ci fanno correre un rischio di raccontare qualcosa di sbagliato.

---

## Come catturare (vale per tutte)

- **Finestra intera**, non ritagli: servono barra del titolo, barra comandi e barra di stato.
- Se possibile con **dati dentro** (una riga, un mercato, un segnale): una finestra vuota mostra
  le colonne ma non come si presentano i valori reali.
- **Prima di mandarli, controlla che non compaiano**: saldo del conto, username Betfair, dati di
  abbonamento nella barra del titolo, nomi di strategie personali. Se compaiono va bene lo stesso,
  li oscuro io — basta che tu me lo dica.
- Formato PNG, risoluzione nativa (niente foto allo schermo).

---

## P1 — servono davvero: oggi al loro posto c'è materiale ricostruito

### 1. Monitor Mercati, finestra intera con dentro qualche mercato
**Sblocca**: la scheda «Monitor Mercati» della demo `/demo/xtrader` è **ricostruita dalla
descrizione scritta del manuale**, non da uno screenshot — colonne, pulsanti e i due stati della
strategia. È l'unica parte del sito dichiaratamente non verificata, e vorrei toglierla da quello
stato. Serve anche a `docs/xtrader_integration.md` §6.

### 2. Monitor Mercati con una strategia applicata
**Sblocca**: le tre colonne finali (Strategia · Stato esecuzione · Log), il **selettore slot**
(5 slot per mercato) e l'aspetto del pulsante col nome della strategia sulla riga. Del meccanismo
degli slot ho solo la descrizione a parole.

### 3. Finestra Segnali **con dei segnali dentro**, almeno uno verde e uno rosso
**Sblocca**: lo screenshot che ho (`varie/02`) mostra la finestra **vuota**. Non ho mai visto come
appaiono davvero una riga valida e una non valida: com'è fatta l'icona, come si popolano Fonte,
Data, Sport e Inizio, e come appare una riga **già usata da una strategia** (il manuale dice che
diventa verde e si riempiono ID scommessa, Data Scommessa, Nome Strategia). La demo oggi mostra
due pallini colorati: verosimili, ma inventati nella forma.

---

## P2 — completano le guide

### 4. Dialog «Fonte Segnali» **compilata**
**Sblocca**: i miei due scatti (`varie/03`, `varie/04`) hanno i campi **vuoti**. Servono per
mostrare un percorso file e un intervallo reali, cioè com'è fatta la dialog quando è pronta a
funzionare.

> ✅ **Domanda chiusa.** Chiedevo se «Lingua Palinsesto» contasse anche col riconoscimento per ID:
> il proprietario ha confermato che **con gli id la lingua non entra in gioco**. Guida e demo sono
> già allineate. Resta solo la curiosità cosmetica se il campo scompaia dalla dialog o resti
> visibile e inerte — irrilevante per il comportamento.

### 5. Azione «Piazza Scommesse su Segnali» **compilata**
**Sblocca**: `azioni-se-vero/04` è a valori di default e i controlli dello stake sono disattivati.
Serve vederla con «Piazza su Segnali Punta» spuntato, un Provider scritto e uno stake impostato —
cioè come si presenta davvero quando funziona.

### 6. Finestra Mercato con l'**icona dei segnali** in alto a destra
**Sblocca**: il manuale dice che compare quando il mercato ha segnali e che cliccandola si apre la
finestra Segnali evidenziando i suoi. Non l'ho mai vista.

### 7. Interfacce di trading (Griglia / Ladder / Traderscopio) con la **lettera P o B** del segnale
**Sblocca**: il manuale dice che i segnali compaiono lì con **P** (punta) e **B** (banca). È il
punto in cui il segnale del bridge diventa visibile durante l'operatività.

### 8. Importazione segnali da file CSV — la dialog che chiede **metodo e lingua**
**Sblocca**: il manuale dice che all'importazione vengono richiesti i parametri di riconoscimento.
Utile per chi vuole provare il CSV del bridge una tantum, senza configurare una fonte.

### 9. Filtro Mercati con la casella **«Segnali» spuntata** e dei risultati
**Sblocca**: conferma il comportamento che ho simulato nella demo (mostra solo i mercati che hanno
un segnale). Oggi è una deduzione dall'etichetta, non un fatto osservato.

### 10. Stato Scommesse dopo un piazzamento da segnale
**Sblocca**: chiude il cerchio della guida — dal messaggio Telegram alla scommessa a mercato.
Basta una riga, con importi coperti.

---

## P3 — utili, non urgenti

11. **Guida Variabili** — la finestra che si apre dal pulsante nella condizione Formula. Il
    contenuto ce l'ho (`FORMULA.pdf` → `docs/xtrader_formule.md`), manca l'aspetto.
12. **Opzioni → pagina Ladder** — la voce *«Numero quote del book da considerare per valutare la
    tendenza del mercato»*: è il parametro da cui dipendono `ABS_TREND` e `ALS_TREND`, quindi due
    installazioni configurate diversamente danno risultati diversi a parità di formula.
13. **Opzioni Monitor → Colonne Visualizzate** — quali colonne si possono mostrare nel Monitor.
14. **Strumenti → Modalità Simulazione** — rilevante per il collaudo del bridge: è la modalità in
    cui provare la catena senza soldi veri.
15. **Crea Segnale / finestra «Nuovo Segnale»** dalla finestra Mercato o dal Monitor.
16. **Esportazione segnali** (pulsante «Esporta su file» dell'elenco segnali).
17. **Processors Mercati in esecuzione** — i miei scatti (`varie/07`-`10`) sono tutti a processor
    fermo, stato OFF.
18. **Filtri Selezioni** — il pulsante in alto a destra nel Filtro Mercati, mai aperto.
19. **Barra pulsanti della finestra principale** per intero — nei miei scatti è sempre tagliata.

---

## 🌍 Le altre versioni del network — servono per le tre sezioni del sito

Il sito avrà **una sezione per prodotto**: *BetRelay per XTrader* · *for BETTINGTOOLKIT.COM* ·
*para .ES* · *para .LAT* (vedi [`policy_lingue_sito.md`](policy_lingue_sito.md)). Ogni sezione
mostra le schermate **nella lingua di quel software**, quindi servirebbero le stesse finestre in
**inglese** e in **spagnolo**.

Le più importanti, nell'ordine:

- [ ] **Fonte Segnali** in EN e in ES — è la schermata centrale della guida di collegamento
- [ ] **Finestra Segnali** in EN e in ES
- [ ] **Filtro Mercati** in EN e in ES
- [ ] Menu principale (per le voci di menu tradotte) in EN e in ES

Confermerebbero anche una cosa che oggi diamo per buona sulla parola del supporto: che struttura
del CSV e codici `MarketType` sono **davvero identici** fra le versioni, e che cambiano solo le
etichette dell'interfaccia.

**Se non sono disponibili non è bloccante**: per la regola delle lingue, in mancanza di quelle
schermate le sezioni non-italiane usano gli screenshot **inglesi**, e se mancano anche quelli si
parte con gli italiani dichiarando che l'interfaccia mostrata è la versione IT.

> 📌 **Regola permanente da ricordare** ([`policy_lingue_sito.md`](policy_lingue_sito.md)): gli
> screenshot esistono solo in **IT/EN/ES**, perché il software esiste solo in quelle tre lingue.
> Se il sito aggiungerà francese, rumeno o altro, **il testo si traduce ma gli screenshot restano
> in inglese** — e le etichette vanno citate verbatim come appaiono a schermo.

---

## Cosa succede quando arrivano

Per ogni screenshot ricevuto:

1. entra in `website/static/docs/strategie-xtrader/<cartella>/` col naming `NN-AAAAMMGG-HHMMSS.png`
   e la riga corrispondente in `manifest.json`;
2. viene **descritto** in `catalogo.jsonl` / `catalogo.md` (finestra, controlli, «usare_per»,
   privacy) come gli altri 102;
3. le parti **ricostruite** della demo vengono riallineate al reale, e l'avviso «ricostruita dal
   manuale» sparisce dalle sezioni che non ne hanno più bisogno;
4. `docs/xtrader_integration.md` perde le relative voci dalla sezione «Limiti dichiarati».
