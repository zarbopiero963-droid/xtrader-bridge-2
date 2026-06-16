# Contratto CSV XTrader — XTrader Signal Bridge

> Documento ufficiale (PR-01). Definisce il formato CSV che il bridge scrive per
> XTrader. È la fonte di verità per `CSV_HEADER` in `main.py`, per il README e per
> tutte le PR successive (parser, validazione, csv writer).

## Header ufficiale (12 colonne, ordine fisso)

```
Provider,SelectionId,MarketId,SelectionName,MarketName,EventName,MarketType,BetType,Price,MinPrice,MaxPrice,Points
```

## Colonne

| # | Colonna | Obbligatoria | Note |
|---|---|---|---|
| 1 | `Provider` | sì | sorgente del segnale (es. `PBet`, `TelegramBot`) |
| 2 | `SelectionId` | dipende dalla modalità | ID selezione XTrader (modalità ID) |
| 3 | `MarketId` | dipende dalla modalità | ID mercato XTrader (modalità ID) |
| 4 | `SelectionName` | dipende dalla modalità | nome selezione (modalità NAME), in italiano |
| 5 | `MarketName` | no | etichetta leggibile del mercato |
| 6 | `EventName` | dipende dalla modalità | evento, es. `Inter v Milan` (modalità NAME) |
| 7 | `MarketType` | dipende dalla modalità | codice mercato, es. `MATCH_ODDS` (modalità NAME) |
| 8 | `BetType` | sì | solo `BACK` o `LAY` |
| 9 | `Price` | no | quota; può essere vuota; virgola → punto |
| 10 | `MinPrice` | no | può essere vuota |
| 11 | `MaxPrice` | no | può essere vuota |
| 12 | `Points` | sì | moltiplicatore stake; default `1` |

## Cosa NON è nel CSV

- **`Stake`**: gestito in XTrader nell'azione "Piazza Scommessa su Segnali", non nel CSV.
- **`Timestamp`**: la deduplica anti-doppia-scommessa è interna al bridge (vedi roadmap PR-15), non una colonna CSV.

## Modalità di riconoscimento (formalizzate, implementate in PR-06)

| Modalità | Campi richiesti |
|---|---|
| `ID_ONLY` | `MarketId` + `SelectionId` |
| `NAME_ONLY` | `EventName` + `MarketType` + `SelectionName` |
| `BOTH` | scrive sia ID sia nomi quando disponibili |

Con i nomi (`NAME_ONLY`/`BOTH`), la **lingua** del CSV deve coincidere con quella
impostata nella fonte Segnali di XTrader (italiano).

## Regole di scrittura

- Header sempre presente, anche su CSV "vuoto" (solo header).
- Un solo segnale attivo alla volta (riscrittura del file) — finché la coda
  multi-segnale (PR-16) non sarà introdotta.
- Tutti i valori vanno scritti tra doppi apici (`quoting=QUOTE_ALL`) — comportamento
  della scrittura atomica introdotto in PR-05.
- `Points` ha default `"1"`; la configurabilità è prevista in una PR GUI dedicata (PR-13).

## Stato implementazione (PR-01)

- `CSV_HEADER` in `main.py` allineato a 12 colonne con `Points` in coda. ✅
- `build_csv_row()` emette `Points = "1"`. ✅
- README aggiornato; rimosso l'esempio con `Stake`/`Timestamp`. ✅
- Validazione bloccante, modalità di riconoscimento e scrittura atomica: PR successive
  (PR-05, PR-06, PR-10).
