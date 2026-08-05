# Policy lingue del sito e delle guide — REGOLA PERMANENTE

Decisione del proprietario. **Non va persa e non va reinterpretata**: vale per il sito BetRelay,
per le guide utente, per le demo interattive e per il futuro assistente AI.

---

## 1. La regola in una riga

> **Il testo si traduce in tutte le lingue del sito. Gli screenshot no: esistono in IT, EN, ES —
> e per qualunque altra lingua si usano quelli in INGLESE.**

## 2. Perché

Il software di destinazione esiste in **tre lingue e basta**: XTrader (italiano), Betting Toolkit
(inglese, spagnolo). Se domani il sito parlasse francese, rumeno o portoghese, **non esisterebbe
un XTrader in francese** da fotografare: l'utente francese userà comunque l'interfaccia inglese.

Fabbricare screenshot in una lingua che il programma non ha significherebbe **mostrare all'utente
una schermata che non vedrà mai**. Meglio un'interfaccia in inglese con la spiegazione nella sua
lingua, che una finta interfaccia nella sua lingua.

## 3. Cosa fare in pratica

| Elemento | Regola |
|---|---|
| **Testo** (titoli, paragrafi, didascalie, FAQ, log delle demo, chatbot) | tradotto in **tutte** le lingue attive del sito |
| **Screenshot del software di destinazione** (XTrader / Betting Toolkit) | esistono in **IT, EN, ES**. Per ogni altra lingua → **EN** |
| **Screenshot di BetRelay** (l'app nostra) | esistono in **IT, EN, ES** (l'app è trilingue). Per ogni altra lingua → **EN** |
| **Screenshot di Telegram / BotFather** | mockup nostri: si generano nella lingua richiesta se serve, altrimenti **EN** |
| **Etichette dell'interfaccia citate nel testo** | si citano **verbatim nella lingua dello screenshot mostrato**, con la traduzione fra parentesi se serve. Mai tradurre un'etichetta e far credere che il programma la mostri così |

### Il punto che si sbaglia più facilmente

Se il testo francese dice *«cliquez sur Nouvelle source»* ma lo screenshot inglese mostra
**«New source»**, l'utente non trova il pulsante. La forma corretta è:

> cliquez sur **«New source»** (nouvelle source)

Cioè: **etichetta verbatim come appare a schermo**, spiegazione nella lingua dell'utente.

## 4. Fallback delle lingue

```text
lingua richiesta ∈ {it, en, es}  →  screenshot in quella lingua
qualunque altra lingua           →  screenshot in EN
screenshot mancante in quella lingua → EN (e va segnalato, non nascosto)
```

Il fallback **non è silenzioso**: se una pagina mostra screenshot in inglese a un utente francese,
lo dice con una riga tipo *«Les captures d'écran sont en anglais : le logiciel n'existe pas en
français.»* — tradotta anche quella.

## 5. Conseguenze sull'implementazione

- Gli screenshot vanno nominati con il **suffisso di lingua**, non mescolati:
  `.../it/02-....png`, `.../en/02-....png`, `.../es/02-....png`;
- il codice che sceglie l'immagine implementa il fallback del §4 in **un solo punto**, non
  sparso per le pagine;
- `catalogo.jsonl` guadagna un campo `lingua`, e la stessa schermata in tre lingue resta **una
  voce con tre file**, non tre voci scollegate — la descrizione a parole è la stessa;
- l'**assistente AI** deve conoscere questa regola: quando cita un'etichetta deve usare quella
  della lingua dello screenshot che sta mostrando, non tradurla.

## 6. Le tre sezioni per software

Il sito ha una sezione per prodotto di destinazione, perché cambia il nome del programma e la
lingua dell'interfaccia — **non** il funzionamento del bridge, che è identico.

| Sezione | Software | Lingua screenshot |
|---|---|---|
| **BetRelay per XTrader** | XTrader (Italia, TradingSportivo) | IT |
| **BetRelay for BETTINGTOOLKIT.COM** | Betting Toolkit World | EN |
| **BetRelay para BETTINGTOOLKIT.ES** | Betting Toolkit Spagna | ES |
| **BetRelay para BETTINGTOOLKIT.LAT** | Betting Toolkit America Latina | ES |

Il **contenuto tecnico è lo stesso**: contratto CSV identico, codici `MarketType` identici,
`BetType` accettato indifferentemente in tutte le versioni (conferma supporto, #3). Cambia:

- il **nome del programma** citato nel testo e negli screenshot;
- la **lingua dell'interfaccia** negli screenshot;
- la **«Lingua Palinsesto»** da impostare nella fonte segnali (rilevante solo col riconoscimento
  per nomi — con gli id la lingua non entra in gioco);
- eventuali differenze di **exchange Betfair** (id e nomi diversi fra .it, .com, .es).

⚠️ **Da non scrivere mai**: che le sezioni sono «programmi diversi». È lo stesso programma con nomi
e lingue diverse — dirlo altrimenti confonderebbe l'utente e sarebbe falso.

## 7. Non affiliazione

Ogni pagina del sito porta nel footer, **tradotto in tutte le lingue attive**:

> Progetto indipendente: BetRelay non è affiliato, associato, autorizzato né sponsorizzato da
> TradingSportivo (XTrader) né da Betting Toolkit (BETTINGTOOLKIT.COM / .ES / .LAT). XTrader,
> Betting Toolkit, Betfair, Telegram e i relativi marchi appartengono ai rispettivi proprietari e
> sono citati solo a scopo descrittivo, per indicare la compatibilità.

Serve proprio perché il sito **nomina** quei prodotti ovunque e mostra le loro schermate: senza
questa riga, una sezione intitolata «BetRelay for BETTINGTOOLKIT.COM» può leggersi come un
prodotto ufficiale del network. La menzione descrittiva di un marchio per indicare compatibilità
è legittima; lasciar credere a un'affiliazione non lo è.

Un test verifica che il disclaimer sia presente su **ogni** pagina: una pagina nuova senza
disclaimer fa fallire la suite.

## 8. Stato attuale

| | |
|---|---|
| Screenshot XTrader **IT** | ✅ 102, catalogati |
| Screenshot XTrader **EN** / **ES** | ❌ mancanti — vedi #266 |
| Screenshot BetRelay **IT** | ✅ 5 (Xvfb, `docs/assets/screenshots/linux-xvfb/`) |
| Screenshot BetRelay **EN** / **ES** | ❌ mancanti, ma **generabili da noi**: l'app è trilingue e la pipeline Xvfb esiste già (`tools/screenshots/README.md`) — basta cambiare `app_language` nella config d'esempio |
| Testo del sito | ✅ IT/EN/ES sulle pagine principali · ❌ guida bot e demo ancora solo IT |
| Footer non-affiliazione | ✅ su tutte le pagine, IT/EN/ES |
| Suffisso lingua nei percorsi screenshot | ❌ da introdurre quando arriveranno le prime immagini non-IT |
