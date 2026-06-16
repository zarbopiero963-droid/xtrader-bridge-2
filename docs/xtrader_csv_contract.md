# Contratto CSV XTrader — XTrader Signal Bridge

> Documento ufficiale (PR-01). Definisce il formato CSV che il bridge scrive per
> XTrader, **basato sui CSV di esempio reali forniti dal team XTrader**. È la fonte
> di verità per `CSV_HEADER` in `main.py`, per il README e per le PR successive.

## Header ufficiale (14 colonne, ordine fisso)

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
```

Esempi reali (dal team XTrader):

```text
"TOS_TENNIS_REDS","35720839","Mpetshi Perricard v Moutet","1.259176583","Match Odds","MATCH_ODDS","19544746","Giovanni Mpetshi Perricard","0","","","","BANCA",""
"XTrader","35035280","Spagna - Capo Verde","1.259018793","Esito Finale","MATCH_ODDS","22","Spagna","0","","","","PUNTA",""
```

## Colonne

| # | Colonna | Obbligatoria | Note |
|---|---|---|---|
| 1 | `Provider` | sì | sorgente del segnale (es. `PBet`, `TelegramBot`) |
| 2 | `EventId` | modalità ID | ID evento XTrader/Betfair; vuoto se assente nel segnale |
| 3 | `EventName` | modalità NAME | evento, es. `Inter v Milan` |
| 4 | `MarketId` | modalità ID | ID mercato (es. `1.259176583`); vuoto se assente |
| 5 | `MarketName` | no | etichetta leggibile del mercato (es. `Match Odds`) |
| 6 | `MarketType` | modalità NAME | codice mercato, es. `MATCH_ODDS` |
| 7 | `SelectionId` | modalità ID | ID selezione; vuoto se assente |
| 8 | `SelectionName` | modalità NAME | nome selezione (vedi nota lingua) |
| 9 | `Handicap` | sì | default `0` |
| 10 | `Price` | no | quota; può essere vuota; virgola → punto |
| 11 | `MinPrice` | no | può essere vuota |
| 12 | `MaxPrice` | no | può essere vuota |
| 13 | `BetType` | sì | **`PUNTA`** (punta/back) o **`BANCA`** (banca/lay) |
| 14 | `Points` | no | moltiplicatore stake; **vuoto** negli esempi reali (lo gestisce XTrader) |

## Valori in italiano

- **`BetType`**: il bridge scrive `PUNTA` (equivalente di back) o `BANCA` (equivalente
  di lay), come negli esempi reali. Mapping interno: `BACK → PUNTA`, `LAY → BANCA`.
- **`Points`**: lasciato vuoto (gli esempi reali non lo valorizzano).
- **`Handicap`**: `0` di default.

## Cosa NON è nel CSV

- **`Stake`**: gestito in XTrader nell'azione "Piazza Scommessa su Segnali", non nel CSV.
- **`Timestamp`**: la deduplica anti-doppia-scommessa è interna al bridge (vedi roadmap
  PR-15), non è una colonna CSV.

## Modalità di riconoscimento (formalizzate, implementate in PR-06)

| Modalità | Campi richiesti |
|---|---|
| `ID_ONLY` | `MarketId` + `SelectionId` (+ `EventId`) |
| `NAME_ONLY` | `EventName` + `MarketType` + `SelectionName` |
| `BOTH` | scrive sia ID sia nomi quando disponibili |

Con i nomi (`NAME_ONLY`/`BOTH`), la **lingua** del CSV deve coincidere con quella della
fonte Segnali di XTrader (italiano). **Nota:** il messaggio Telegram P.Bet non contiene
gli ID (`EventId`/`MarketId`/`SelectionId`), quindi oggi restano vuoti e il bridge punta
sulla modalità a nomi.

## Regole di scrittura

- Encoding **UTF-8 con BOM** (`utf-8-sig`), come negli esempi reali.
- Tutti i valori tra doppi apici (`quoting=csv.QUOTE_ALL`).
- Header sempre presente, anche su CSV "vuoto" (solo header).
- Un solo segnale attivo alla volta (riscrittura del file) finché la coda multi-segnale
  (PR-16) non sarà introdotta.

## Stato implementazione (PR-01)

- `CSV_HEADER` allineato alle **14 colonne reali** con ordine corretto. ✅
- `build_csv_row()` emette `EventId/MarketId/SelectionId` vuoti, `Handicap="0"`,
  `BetType` mappato a `PUNTA/BANCA`, `Points` vuoto. ✅
- `init_csv()`/`write_csv()` scrivono in `utf-8-sig` con `QUOTE_ALL`. ✅
- README aggiornato sul formato reale. ✅

### Rimandato (fuori scope PR-01)

- **`SelectionName` in italiano** (es. `Over 2,5 gol`, `Sì`/`No`, `Pareggio`): oggi
  `build_csv_row()` può emettere stringhe come `Over 0.5 Goals` in inglese. La
  localizzazione è prevista in **PR-08** (selection mapping IT).
- Scrittura **atomica** (tmp + fsync + rename): **PR-05**.
- Validazione bloccante del segnale: **PR-10**; modalità riconoscimento: **PR-06**.
