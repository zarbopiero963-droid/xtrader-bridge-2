# Formule XTrader — riferimento delle variabili

Riferimento della condizione **«Formula»** di XTrader (screenshot `condizioni/67`), cioè della
finestra che si apre dal pulsante **«Guida Variabili»**. Ricavato dal PDF fornito dal proprietario
(`website/static/docs/strategie-xtrader/condizioni/FORMULA.pdf`, articolo del servizio assistenza
TradingSportivo aggiornato al 17/06/2026) e riscritto qui in forma consultabile.

> Serve all'**assistente AI**: quando l'utente chiede qualcosa che nessuna condizione predefinita
> copre, la risposta è quasi sempre una formula — e le variabili vanno scritte con la sintassi
> esatta, altrimenti la condizione non compila.
>
> **Diritti**: il PDF è materiale di TradingSportivo. Questo file è una **riscrittura di
> riferimento tecnico**, non una ristampa.

---

## Come funziona

Una formula può essere usata in due modi:

- **come condizione** — se contiene un operatore di confronto, il risultato è vero/falso:
  `M.V > 10000` è vera quando il volume del mercato supera 10 000 €;
- **come valore** — senza operatore di confronto, il risultato è un numero: `M.LIQ/10`.

**Confronto fra stringhe**: si usa l'operatore `LIKE`, la stringa fra apici singoli, `*` come
jolly.

```text
M.NAME LIKE '*OVER*'      contiene OVER
M.NAME LIKE 'PARIS*'      inizia per PARIS
M.NAME LIKE '*MADRID'     finisce per MADRID
```

---

## Come si indica una selezione

Le variabili di **mercato** iniziano per `M.`, quelle di **selezione** per `R.` seguito
dall'ordinamento e dal numero d'ordine.

| Sintassi | Selezione indicata |
|---|---|
| `R.1` | prima selezione **in ordine Betfair** |
| `R.B1` | prima in ordine di **quote disponibili per puntare** (B = BACK) |
| `R.L1` | prima in ordine di **quote disponibili per bancare** (L = LAY) |
| `R.V1` | prima in ordine di **volumi scambiati decrescenti** |

Il numero è l'indice: `R.2` è la seconda in ordine Betfair, `R.V3` la terza per volume.

---

## Variabili di mercato (`M.`)

| Variabile | Significato |
|---|---|
| `M.NAME` | nome del mercato |
| `M.EVENT` | nome dell'evento |
| `M.COMPETITION` | nome della competizione |
| `M.STATUS` | stato del mercato |
| `M.V` | volume del mercato |
| `M.BBP` / `M.LBP` | percentuale book punta / banca |
| `M.N` | numero selezioni |
| `M.NA` / `M.NNA` | numero selezioni attive / non attive |
| `M.NWINNERS` | numero di selezioni vincenti previste |
| `M.WINNERINDEX1…4` | indice della selezione vincente (mercati PLACE con più piazzati); vuoto se non trovato |
| `M.LIQ` | liquidità del mercato calcolata sul book ai vari livelli |
| `M.BETDELAY` | ritardo di piazzamento, in secondi |
| `M.CASHOUT` | valore di cash out disponibile |
| `M.BET_IN_PROGRESS` | `true` se c'è una scommessa in corso di piazzamento sul mercato |
| `M.RACEL_METERS` / `M.RACEL_MILES` | lunghezza della gara |
| `M.RACESTATUS` | stato della corsa (`DORMANT`, `OFF`, `FINISHED`, `ABANDONED`, … ; `DATA_UNAVAILABLE` se manca il dato) |
| `M.BASKET_PERIOD` | periodo di gioco basket (`1HE` = fine primo tempo, `ET` = supplementari, …) |
| `M.TENNIS_CURRENTSET` | set attuale |
| `M.BASKET_HOME_PTS`, `M.BASKET_HOME_1Q…4Q` | punti casa, totali e per quarto |
| `M.BASKET_AWAY_PTS`, `M.BASKET_AWAY_1Q…4Q` | punti ospite, totali e per quarto |

---

## Variabili di selezione (`R.<sel>.`)

### Quote e importi del book

| Variabile | Significato |
|---|---|
| `R.1.NAME` | nome della selezione |
| `R.1.V` | volume scambiato sulla selezione |
| `R.1.BABP` | migliore quota disponibile per **puntare** (Best Available Back Price) |
| `R.1.BALP` | migliore quota disponibile per **bancare** (Best Available Lay Price) |
| `R.1.BABS` | importo disponibile alla migliore quota punta (Back Stake) |
| `R.1.BALS` | importo disponibile alla migliore quota banca (Lay Stake) |
| `R.1.BP1` `BP2` `BP3` | 1ª, 2ª, 3ª quota punta del book — `BP1` ≡ `BABP` |
| `R.1.LP1` `LP2` `LP3` | 1ª, 2ª, 3ª quota banca del book — `LP1` ≡ `BALP` |
| `R.1.TAB` / `R.1.TAL` | totale disponibile per puntare / per bancare |
| `R.1.LTP` | ultima quota scambiata |
| `R.1.MINEXPRICE` / `R.1.MAXEXPRICE` | quota minima / massima scambiata |
| `R.1.MAXVOLPRICE` | quota con il massimo volume scambiato |
| `R.1.MAXVOLMATCHED` | volume scambiato a quella quota |
| `R.1.LTPVARPERC` | variazione percentuale dell'ultima quota scambiata |
| `R.1.LTPVARTICKS` | stessa variazione, misurata in **tick** |
| `R.1.WOM` | Weight Of Money (formula impostata nelle opzioni del programma) |

### Tendenza del book

`R.1.ABS_TREND` — somma dei primi **N** importi disponibili per **puntare**.
`R.1.ALS_TREND` — idem per **bancare**.

`N` **non** è fisso: è il valore impostato in `Opzioni` → pagina `Ladder` → *«Numero quote del book
da considerare per valutare la tendenza del mercato»*. Due installazioni con impostazioni diverse
danno risultati diversi a parità di formula — da tenere presente prima di condividere una strategia.

### Le proprie scommesse sulla selezione

| Variabile | Significato |
|---|---|
| `R.1.PL` | profitto / perdita sulla selezione |
| `R.1.EXSUMB` / `R.1.EXSUML` | somma degli stake **eseguiti o parzialmente eseguiti** in punta / in banca |
| `R.1.REMSUMB` / `R.1.REMSUML` | somma degli stake **non eseguiti** in punta / in banca |
| `R.1.BCP` / `R.1.LCP` | quota di carico medio delle proprie scommesse punta / banca |
| `R.1.CASHOUT` | importo di cash out possibile sulla selezione |

---

## Valori memorizzati e valori predefiniti

I **Valori Memorizzati** (scritti dall'azione «Imposta / Modifica Valore Memorizzato», screenshot
`azioni-se-vero/21`) si richiamano col nome fra parentesi quadre, con un prefisso che indica il
livello:

| Sintassi | Livello |
|---|---|
| `M.[NOME]` | mercato |
| `R.1.[NOME]` | selezione |
| `S.[NOME]` | strategia |
| `A.[NOME]` | applicazione (visibile a tutte le strategie) |

I **Valori Predefiniti** della strategia (screenshot `condizioni/10`, `condizioni/11`) si
richiamano con `PV[NOME]`. **Il nome è case sensitive.**

---

## Parametri di applicazione

| Variabile | Significato |
|---|---|
| `A.NOW` | data e ora attuali in formato stringa, es. `#01/03/2025 12:05:54#`. Confrontabile: `A.NOW > '02/01/2022'` |
| `A.SIMULATIONMODE` | **vero se XTrader è in modalità simulazione** |

> `A.SIMULATIONMODE` è la variabile più interessante per chi collega BetRelay: permette di scrivere
> regole che si comportano diversamente in simulazione e in reale — per esempio una regola di
> collaudo attiva **solo** in simulazione. Da suggerire a chi sta testando la catena.

---

## Errori tipici da segnalare all'utente

- **Nome del valore predefinito con maiuscole diverse** → `PV[nome]` non trova `PV[NOME]`.
- **Stringa senza apici singoli** o `LIKE` sostituito da `=` → il confronto testuale non funziona.
- **Selezione indicata con l'ordinamento sbagliato** → `R.1` (ordine Betfair) e `R.B1` (ordine
  quote punta) sono selezioni **diverse**; su un mercato dove il favorito non è il primo in ordine
  Betfair la formula punta all'esito sbagliato. È l'errore più insidioso perché non dà errore: dà
  il risultato giusto sulla selezione sbagliata.
- **`ABS_TREND` / `ALS_TREND` confrontati fra installazioni diverse** → dipendono da un'opzione
  locale (vedi sopra).
