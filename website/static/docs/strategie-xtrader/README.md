# Screenshot XTrader — automazione (condizioni, azioni, strategie)

Materiale **sorgente** per le guide BetRelay, fornito dal proprietario del progetto:
102 screenshot reali dell'automazione di XTrader + il PDF `FORMULA.pdf` (103 file in tutto).

> ⚠️ Questi file **non sono ancora una guida**. Sono la materia prima da cui vengono scritte
> le pagine di `/documentazione`. Nessuna pagina del sito li linka al momento: ci finiranno
> quelli effettivamente usati, uno per uno, con testo nostro accanto.

## Cosa c'è

| Cartella | File | Contenuto |
|---|---|---|
| `condizioni/` | 70 (69 PNG + `FORMULA.pdf`) | dialog **Nuova Condizione**: i tipi di condizione, i criteri di selezione, i valori di riferimento, le formule |
| `azioni-se-vero/` | 21 PNG | dialog **Nuova Azione**: i tipi di azione disponibili nel ramo «se vero» |
| `azioni-se-vero-se-falso/` | 2 PNG | il ramo «se falso» |
| `varie/` | 10 PNG | finestre di contorno: **Filtro Mercati**, **Finestra Segnali**, monitor |

## Note del proprietario (dai due documenti allegati su Drive)

- *«per entrambi: azioni se vero, azioni se falso hanno le stesse azioni disponibili»* — cioè i
  due rami dell'automazione offrono lo stesso set di azioni; la cartella `azioni-se-vero-se-falso`
  serve solo a documentare il ramo «se falso», non un elenco diverso.
- *«il pulsante guida variabili all'interno di: condizione → formula, riportato nel PDF nominato
  FORMULA qui dentro stesso»* — `condizioni/FORMULA.pdf` è la guida alle variabili utilizzabili
  nelle condizioni di tipo formula.

## Lo screenshot più importante

`varie/02-20260708-170631.png` è la **Finestra Segnali** — la schermata che il manuale ufficiale
descrive solo a parole, senza immagine. Si vedono:

- l'elenco **Fonti** con le colonne reali: Nome Servizio · Nome File · Url · Ricarica
  Automaticamente · Intervallo · Escludi N.V. · Riconoscimento Sel · Ultimo Agg.;
- le due fonti predefinite **Segnali Importati** e **Segnali Creati**;
- l'elenco segnali con le colonne lette dal CSV fra parentesi quadre — `[Provider]`, `[EventId]`,
  `[MarketId]`, `[SelectionId]`, `[EventName]`, `[MarketName]`, `[SelectionName]`,
  `[MarketType]`, `[BetType]`, `[Handicap]` — accanto a quelle ricavate da XTrader (Fonte, Data,
  Sport, Inizio);
- i filtri **Solo Validi**, Provider, Nome Mercato, Marketid.

Le colonne fra parentesi quadre corrispondono a quelle che BetRelay scrive — ma la **fonte del
contratto CSV non è questo screenshot**: è `csv_writer.CSV_HEADER` nel codice, documentato in
[`docs/xtrader_csv_contract.md`](../../../../docs/xtrader_csv_contract.md) e verificato da un test
che confronta la tabella della documentazione con l'header reale. Uno screenshot mostra com'era
un giorno; se un domani divergessero, ha ragione il codice.

## Naming

I nomi originali (`Immagine 2026-07-06 165210.png`) sono stati normalizzati in
`NN-AAAAMMGG-HHMMSS.png`: niente spazi (URL-safe) e **ordine cronologico = ordine di lettura**,
che è anche l'ordine in cui il proprietario ha percorso i menu. La corrispondenza con i nomi
originali e gli id Drive è in `manifest.json`.

## Privacy — verifica esaustiva

**Tutte e 102 le immagini sono state aperte e controllate una per una** (non a campione). Nessuna
credenziale, nessun saldo, nessun token, nessun ID di conto Betfair. I dati di mercato visibili
(squadre, competizioni, quote, importi abbinati) sono palinsesto pubblico Betfair.

Due rilievi, entrambi non sensibili ma segnalati per correttezza:

| Cosa | Dove | Valutazione |
|---|---|---|
| Barra del titolo con **«Data Scadenza Abbonamento: 20/07/2026»** e **«Ultimo accesso precedente: 06/07/2026 16:50:53»** | `varie/01` | dato di abbonamento del proprietario, non una credenziale |
| Nome di strategia personale **`SIG_PREMATCH_BASE`** | `varie/10`, `azioni-se-vero-se-falso/01` e `02`, `condizioni/01`, `02`, `03`, `10`, `11`, `15`, `69` | nome scelto dal proprietario, visibile nell'elenco strategie |

Nessuno dei due impedisce la pubblicazione. Se il proprietario preferisce, si possono oscurare con
un ritaglio o una sfocatura prima di usarli in una guida pubblica.

Condizioni e azioni portano ovunque i **nomi di default generati dal programma**
(`Nuova Condizione #1`, `Nuova Azione #2`, `Nuova Regola #1`), quindi non rivelano nulla del
metodo del proprietario.

## Descrizioni

Ogni immagine ha una descrizione a parole in **`catalogo.md`** (leggibile) e **`catalogo.jsonl`**
(una riga JSON per immagine). Campi: `file`, `finestra`, `rilevanza_bridge`, `descrizione`,
`usare_per`, `privacy`.

Servono al futuro **assistente AI**: un modello non può guardare gli screenshot, ma leggendo il
catalogo sa *quale* immagine mostrare e *cosa* contiene. La guida operativa che le usa è
[`docs/xtrader_integration.md`](../../../../docs/xtrader_integration.md); il riferimento delle
formule è [`docs/xtrader_formule.md`](../../../../docs/xtrader_formule.md).

`catalogo.md` si apre con l'indice delle **13 immagini a rilevanza altissima** per il bridge: fonte segnali (`varie/02`, `03`, `04`), indice azioni e azione da segnali
(`azioni-se-vero/01`, `04`), numero esecuzioni e nodo condizioni (`condizioni/13`, `15`),
indice condizioni e criteri di selezione (`condizioni/17`, `18`), codici MarketType
(`condizioni/20`, `21`, `22`) e la guardia anti-doppione (`condizioni/42`).

## Cosa manca ancora

L'elenco degli screenshot **non ancora disponibili**, in ordine di utilità e con l'indicazione di
cosa è oggi ricostruito al loro posto, è in
[`docs/screenshot_xtrader_mancanti.md`](../../../../docs/screenshot_xtrader_mancanti.md).

## Diritti

Screenshot dell'interfaccia di XTrader, prodotto di **TradingSportivo**, catturati dal
proprietario del progetto e usati qui per documentare l'integrazione con BetRelay. BetRelay è un
progetto indipendente, non affiliato a TradingSportivo.
