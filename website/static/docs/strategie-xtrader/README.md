# Screenshot XTrader — automazione (condizioni, azioni, strategie)

Materiale **sorgente** per le guide BetRelay, fornito dal proprietario del progetto:
103 screenshot reali dell'automazione di XTrader + il PDF `FORMULA.pdf`.

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

È la conferma visiva del contratto CSV: le colonne fra parentesi quadre sono esattamente quelle
che BetRelay scrive.

## Naming

I nomi originali (`Immagine 2026-07-06 165210.png`) sono stati normalizzati in
`NN-AAAAMMGG-HHMMSS.png`: niente spazi (URL-safe) e **ordine cronologico = ordine di lettura**,
che è anche l'ordine in cui il proprietario ha percorso i menu. La corrispondenza con i nomi
originali e gli id Drive è in `manifest.json`.

## Privacy

Verificati a campione (le 13 immagini a piena larghezza, cioè quelle che mostrano finestre intere
e non semplici dialog): **nessun dato di conto** — niente username Betfair, niente saldi, niente
nomi di strategie personali. Le condizioni e le azioni portano i nomi di default generati dal
programma (`Nuova Condizione #1`, `Nuova Azione #2`). I dati di mercato visibili (squadre,
competizioni, quote) sono palinsesto pubblico Betfair.

## Diritti

Screenshot dell'interfaccia di XTrader, prodotto di **TradingSportivo**, catturati dal
proprietario del progetto e usati qui per documentare l'integrazione con BetRelay. BetRelay è un
progetto indipendente, non affiliato a TradingSportivo.
