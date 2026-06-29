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
| 10 | `Price` | no | quota; può essere vuota; separatore decimale → punto (vedi nota separatori) |
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

## Modalità di riconoscimento (implementate in PR-06, `recognition.py`)

XTrader riconosce un segnale in **due modi alternativi**; la modalità scelta decide
quali colonne devono essere popolate. I due set sono **mutuamente esclusivi**: se usi
un set, l'altro **può restare vuoto**.

| Modalità | Campi richiesti | Possono restare vuoti |
|---|---|---|
| `ID_ONLY` | `MarketId` + `SelectionId` | `EventName`, `MarketType`, `SelectionName`, `EventId`, `MarketName` |
| `NAME_ONLY` | `EventName` + `MarketType` + `SelectionName` | `MarketId`, `SelectionId`, `EventId`, `MarketName` |
| `BOTH` | basta che **UN** set sia completo (ID **oppure** nomi) | l'altro set |

> Allineato a `recognition.missing_fields`: in `BOTH` la riga è valida se è completo
> **almeno uno** dei due set (non servono entrambi).

Con i nomi (`NAME_ONLY`/`BOTH`), la **lingua** del CSV deve coincidere con quella della
fonte Segnali di XTrader (italiano). **Nota:** il messaggio Telegram non contiene gli ID
(`EventId`/`MarketId`/`SelectionId`); il bridge punta sulla modalità a nomi e, quando
possibile, li **arricchisce dal dizionario Betfair locale** (vedi sotto).

### Identificazione precisa dal dizionario + fallback nomi (PR-P12)

Dopo parser e mappature a nomi, il bridge prova a riempire `EventId`/`MarketId`/`SelectionId`
cercando nel **dizionario Betfair locale** la catena evento→mercato→selezione per lo **sport**
del parser (`betfair/dictionary_resolver.py`). La risoluzione è **additiva, conservativa e
fail-open**: gli ID si scrivono SOLO se il match è **univoco** a tutti i livelli; in caso di
assenza/ambiguità (o se il dizionario non è disponibile) la riga resta a **nomi**
(*fallback nomi*) e il segnale **non viene bloccato**. Così, se il dizionario conosce
l'evento, il CSV porta l'identificazione precisa; altrimenti XTrader usa i nomi.

Note operative:
- gli **ID forniti dal parser** (modalità ID/BOTH) NON vengono mai sovrascritti: se sono in
  conflitto con la tripla del dizionario, l'arricchimento si annulla del tutto (vince il
  parser); altrimenti si riempiono solo i campi ID vuoti con la tripla coerente del dizionario;
- per il comportamento "ID se trovato, **altrimenti nomi**" la modalità del parser deve essere
  **`NAME_ONLY` o `BOTH`** (con `BOTH` la riga è valida sia con la tripla ID sia coi soli nomi);
  un parser `ID_ONLY` che si affida al dizionario per gli ID resta fail-closed su un miss;
- le **selezioni** si risolvono per `runner_name` Betfair: per le selezioni-squadra coincide
  coi nomi mappati, mentre selezioni generiche con nome XTrader diverso dal runner Betfair
  possono non risolvere gli ID e restare a nomi (mai un ID errato).

## Campi sempre opzionali e gate del prezzo

`Price`, `MinPrice`, `MaxPrice`, `Points` sono **sempre facoltativi** per XTrader e
possono restare vuoti in entrambe le modalità (gli esempi reali li lasciano vuoti).

⚠️ **Differenza XTrader vs bridge sul `Price`:**

- **Per XTrader** `Price` può essere vuoto (la quota può essere indicata nell'azione
  "Piazza Scommessa su Segnali").
- **Per il bridge** la quota obbligatoria sì/no è governata da un **unico comando**: la
  casella **«Obblig.» sulla riga `Price`** del Parser Personalizzato. Se `Price` è
  obbligatorio, un segnale **senza** `Price` valido (numerico, > 1.0) viene **scartato**
  (stato `INVALID_MISSING_PRICE` / "Non pronto"). Se `Price` **non** è obbligatorio, la
  quota è opzionale e si scrive la riga col `Price` vuoto.

Nel **Parser Personalizzato**, per lasciare `Price` vuoto: lascia la riga `Price` **non
obbligatoria** (casella «Obblig.» spenta). Non esiste più un interruttore globale
`require_price`: la quota la comanda la riga `Price` di ogni parser.
`MinPrice`/`MaxPrice`/`Points` si lasciano vuoti semplicemente non configurando la loro regola.

## Regole di scrittura

- Encoding **UTF-8 con BOM** (`utf-8-sig`), come negli esempi reali.
- Tutti i valori tra doppi apici (`quoting=csv.QUOTE_ALL`).
- **Anti CSV-injection (audit B1).** `QUOTE_ALL` mette in sicurezza il *parsing*, ma non
  impedisce a un reader *formula-aware* (Excel/LibreOffice/Sheets) di interpretare una cella
  che **inizia** con `=` `+` `-` `@` come formula/comando, né i control-char iniziali
  (TAB/CR/LF). Poiché i nomi (EventName/MarketName/SelectionName/Provider) arrivano da
  Telegram (testo non fidato), in scrittura ogni cella che inizia con uno di quei caratteri
  **e non è un numero** viene prefissata con un apice singolo (`'`) — mitigazione standard.
  I **numeri** del contratto (es. `Handicap` `-1`/`+1,5`, `Price` `1.85`) **non** vengono
  toccati, così restano valori numerici validi per XTrader.
- **Separatore decimale del prezzo** (`Price`/`MinPrice`/`MaxPrice`). Il bridge normalizza il
  separatore decimale a `.`:
  - solo virgola → decimale: `1,85` → `1.85`;
  - solo punto: invariato (`1.85`);
  - **entrambi** i separatori: l'**ultimo** è il decimale e l'altro le **migliaia**, ma SOLO se il
    raggruppamento è valido (`1.234,56` → `1234.56`, `1,234.56` → `1234.56`). Un doppio separatore
    **malformato** (es. `1.2,3`, gruppo non da 3 cifre) NON viene "aggiustato": resta invalido ed è
    **scartato** (`INVALID_PRICE`), per non scrivere nel CSV un prezzo sbagliato ma plausibile.
- Header sempre presente, anche su CSV "vuoto" (solo header).
- **Righe attive e modalità coda (`queue_mode`).** Quante righe segnale possono coesistere nel
  CSV dipende dalla modalità coda configurata (vedi README → `queue_mode`/`max_active_signals`):
  - **`OVERWRITE_LAST`** (default sicuro): **una sola riga attiva** alla volta — ogni nuovo
    segnale **riscrive** il file (header + 1 riga). È il comportamento storico "one signal at a
    time";
  - **`APPEND_ACTIVE`** / **`QUEUE_UNTIL_CONFIRMED`**: **più righe attive** (multi-segnale), con
    tetto `max_active_signals` e i guardrail anti-doppia-scommessa (dedupe persistente, limite
    giornaliero, scadenza per-segnale). Il file resta sempre scritto **atomicamente** (header +
    N righe) e svuotato a solo header quando la coda si svuota.
  In tutte le modalità la scrittura è atomica e una riga non valida non viene mai scritta.

### Fallimento di scrittura e CSV-lock (audit #105 H2)

La scrittura è **atomica** (tmp + `fsync` + `os.replace`) con retry sui lock Windows. Se la
sostituzione del file **fallisce** (tipicamente perché XTrader tiene il CSV aperto in
esclusiva), il bridge:

- **non** scrive una riga parziale e **non** consuma il segnale: coda e guardrail vengono
  ripristinati (rollback), quindi il segnale resta **ritentabile** (nessuna doppia scommessa);
- **ripianifica** la scrittura con un retry a breve, così il disco converge allo stato della
  coda appena il lock si libera;
- dopo **N fallimenti consecutivi** (soglia di default 3, modulo `csv_lock_escalation`) rende
  il blocco **visibile** nella GUI come **«🔒 CSV bloccato da XTrader»** con il numero di
  tentativi, e segnala il **recupero** («✅ CSV sbloccato») appena una scrittura torna a
  riuscire. È solo un **indicatore** di stato: non altera scrittura, coda, rollback o retry.
  Il contatore è **per-sessione** (azzerato a START/STOP).

## Stato implementazione (PR-01)

- `CSV_HEADER` allineato alle **14 colonne reali** con ordine corretto. ✅
- `build_csv_row()` emette `EventId/MarketId/SelectionId` vuoti, `Handicap="0"`,
  `BetType` mappato a `PUNTA/BANCA`, `Points` vuoto. ✅
- `init_csv()`/`write_csv()` scrivono in `utf-8-sig` con `QUOTE_ALL`. ✅
- README aggiornato sul formato reale. ✅

### Rimandato (fuori scope PR-01)

- **`SelectionName` in italiano** (es. `Over 2,5 gol`, `Sì`/`No`, `Pareggio`): localizzato
  in **PR-08** (selection mapping IT). Nota storica: in PR-01 il fallback legacy poteva
  emettere stringhe inglesi come `Over 0.5 Goals`. Oggi quel fallback **non sintetizza più**
  la selezione (audit #104 A1): se l'alias non è risolto dal dizionario, `SelectionName`
  resta `""` e la riga è scartata dal riconoscimento (fail-closed), invece di una selezione
  inglese/sbagliata.
- Scrittura **atomica** (tmp + fsync + rename): **PR-05**.
- Validazione bloccante del segnale: **PR-10**; modalità riconoscimento: **PR-06**.
