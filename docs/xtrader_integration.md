# Collegare BetRelay a XTrader — guida di riferimento

> **Ambito.** Questo documento copre **il lato bridge**: come far leggere a XTrader il CSV che
> BetRelay scrive, e quali strumenti di XTrader servono perché quel segnale diventi una scommessa.
> **Non insegna a costruire strategie di trading**: le condizioni e le azioni sono descritte come
> *vocabolario disponibile*, non come consigli su cosa giocare. La strategia resta una scelta
> dell'utente.
>
> **Destinatari**: chi scrive le guide utente, e l'**assistente AI** che dovrà accompagnare
> l'utente nella configurazione. Per l'assistente valgono le stesse invarianti dell'assistente
> in-app (`AGENTS.md` → «Config assistant safety»): è **sola lettura**, non piazza scommesse, non
> avvia il listener, non tocca il CSV operativo.

**Fonti.** Manuale ufficiale XTrader (capitoli *Segnali*, *Azione Piazza Scommessa su Segnali*),
risposte del supporto Betting Toolkit registrate nella issue #3, e i 102 screenshot reali in
`website/static/docs/strategie-xtrader/`, ognuno descritto in `catalogo.md` / `catalogo.jsonl`.

---

## 1. Il quadro d'insieme

```text
Telegram → BetRelay (parser) → segnali.csv → XTrader (fonte) → strategia → Betfair
                                    ↑                                          │
                                    └──── CSV svuotato dopo il timeout ────────┘
```

BetRelay **non scommette**. Scrive una riga in un file CSV. XTrader legge quel file come «fonte di
segnali», valida la riga contro il palinsesto Betfair, e **solo se una strategia lo prevede** piazza
la scommessa. Ogni anello è ispezionabile separatamente — ed è così che si diagnostica un problema.

---

## 2. Creare la fonte dei segnali in XTrader

**Dove**: menu `Funzioni` → `Segnali`, oppure il tasto **F11**.
*(screenshot: `varie/01` per il menu, `varie/02` per la finestra Segnali)*

La finestra Segnali è divisa in due: sopra le **fonti**, sotto i **segnali** che ne derivano.
Esistono due fonti predefinite non modificabili — *Segnali Importati* e *Segnali Creati* — che non
c'entrano con il bridge: servono per l'import manuale da CSV e per i segnali creati a mano dentro
XTrader.

Con il comando **nuova fonte** si apre la dialog **«Fonte Segnali»**
*(screenshot: `varie/03` e `varie/04` — il manuale ufficiale NON mostra questa finestra)*:

| Campo | Cosa metterci per BetRelay |
|---|---|
| **Nome Servizio** | un nome qualsiasi, es. `BetRelay` |
| **URL** / **Nome File** | scegliere **Nome File** e puntare al file indicato in «📄 CSV Path» nel bridge |
| **Aggiorna automaticamente ogni** | spuntare, e impostare un intervallo (formato `hh:mm:ss`) |
| **Escludi automaticamente segnali non validati** | facoltativo: tiene pulito l'elenco |
| **Riconoscimento selezioni** | `MarketId, SelectionId` **oppure** `EventName,MarketType,SelectionName` |
| **Lingua Palinsesto** | `IT`, `EN` o `ES` — vedi §4 |

> **Il percorso deve essere lo stesso da entrambe le parti.** Il campo «Nome File» qui e il campo
> «📄 CSV Path» nel bridge devono puntare **allo stesso file**. È l'errore di configurazione più
> comune, e non dà nessun messaggio d'errore: semplicemente non arriva mai niente.

### Ogni quanto aggiornare

L'intervallo di refresh va scelto **in relazione al `clear_delay` del bridge** (il timeout dopo il
quale BetRelay riporta il CSV a sola intestazione, default 90 s). Se il refresh è più lento del
timeout, XTrader può non vedere mai il segnale: la riga compare e sparisce fra un controllo e
l'altro. Regola pratica: **intervallo di refresh ben più corto del timeout del bridge**.

### Perché il CSV viene svuotato (e perché non è un dettaglio)

Il manuale è esplicito: *«l'eliminazione di un segnale può risultare inutile se un aggiornamento
automatico successivo dei segnali da parte di una fonte reintroduce i segnali precedentemente
eliminati»*. Cioè: **la fonte rilegge il file a ogni ciclo**. Se BetRelay lasciasse la riga vecchia
sul disco, XTrader la rimetterebbe in lista anche dopo che l'utente l'ha cancellata a mano.

Lo svuotamento a sola intestazione dopo il timeout non è una precauzione del bridge: è ciò che
rende sicuro l'accoppiamento. Vale la pena dirlo all'utente, perché è controintuitivo — «ma il mio
segnale è sparito!» è il comportamento **corretto**.

---

## 3. Riconoscimento: per id o per nomi

Si sceglie nelle proprietà della fonte, e ogni segnale **eredita** il metodo della sua fonte
(modificabile poi sul singolo segnale).

**Per id** — `MarketId` + `SelectionId`. Individua la selezione in modo univoco, ma gli id devono
coincidere con il palinsesto Betfair **della giurisdizione del conto**. Il supporto ha segnalato
che Betfair usa **id diversi fra exchange** (IT vs UK): è la difficoltà principale di questo metodo.
Con questo metodo **la lingua non entra in gioco**: non si confronta nessun nome, quindi
«Lingua Palinsesto» è irrilevante (confermato dal proprietario).

**Per nomi** — `EventName` + `MarketType` + `SelectionName`. Non dipende dagli id, ma i nomi devono
essere **nella stessa lingua** con cui XTrader legge il palinsesto (§4), e devono corrispondere
esattamente a come Betfair li scrive.

Le colonne del metodo scelto devono essere **presenti e popolate**. Quando un segnale viene
validato, XTrader **completa da solo** i dati mancanti (per esempio gli id, se il riconoscimento è
avvenuto per nomi).

**Esito visibile**: icona **verde** = segnale valido, icona **rossa** = non valido. Un segnale
resta rosso se l'evento è concluso, se i dati sono incompleti, o se sono incoerenti col palinsesto.
Nell'elenco si può filtrare per «Solo Validi» ed eliminare in blocco i non validi.

---

## 4. La lingua: cosa conta davvero e cosa no

Qui si concentrano i malintesi, quindi va detto con precisione.

**Il separatore decimale NON è un problema.** Risposta del supporto (#3): *«attualmente è
indifferente»* — XTrader accetta sia la virgola sia il punto. L'impostazione lingua CSV di BetRelay
serve ad allineare il file a quello che l'utente vede a schermo, **non** a farlo leggere. Se i
decimali «sembrano sbagliati», il segnale funziona lo stesso.

**Il `BetType` NON è un problema.** Sempre dal supporto: *«valgono indifferentemente BACK, LAY,
PUNTA, BANCA su tutte le versioni»*. BetRelay scrive `PUNTA`/`BANCA`; non c'è niente da convertire
per gli utenti Betting Toolkit non italiani. *(I termini spagnoli `FAVOR`/`CONTRA` non sono ancora
previsti: il bridge li rifiuta fail-closed.)*

**La lingua conta SOLO per il riconoscimento a nomi — con gli id non entra in gioco**
(confermato dal proprietario). Ha senso: col metodo per id non si confronta nessun nome, quindi
non c'è niente da tradurre. Chi ha problemi ricorrenti di lingua e dispone di id affidabili può
usare il metodo per id proprio per aggirare del tutto la questione.

Sul metodo a nomi, invece, la lingua conta parecchio. Il campo «Lingua
Palinsesto» della fonte (`IT`/`EN`/`ES`, screenshot `varie/04`) decide in che lingua XTrader cerca
nomi di evento, mercato e selezione. Se il CSV dice `Il Pareggio` e la fonte è impostata su `EN`,
il segnale resta **rosso** — e l'utente non capisce perché. Le tre lingue coincidono esattamente
con quelle di BetRelay (`csv_language` / `source_language`, epica #3).

E c'è un livello in più che non dipende dal software: **Betfair stesso traduce diversamente fra
exchange**. Un nome corretto su Betfair.it può non esserlo su Betfair.com. Quando il matching a
nomi fallisce e la lingua è giusta, la causa è quasi sempre questa.

---

## 5. Il CSV visto dal lato XTrader

Nell'elenco segnali le colonne fra **parentesi quadre** sono quelle **lette dal file**; le altre le
ricava XTrader (screenshot `varie/02`).

| Lette dal CSV | Ricavate da XTrader |
|---|---|
| `[Provider]` `[EventId]` `[EventName]` `[MarketId]` `[MarketName]` `[SelectionName]` `[SelectionId]` `[MarketType]` `[Handicap]` `[BetType]` | Fonte · Data · Sport · Inizio · ID scommessa · Data Scommessa · Nome Strategia |

Le 14 colonne che BetRelay scrive e il loro significato stanno in
[`docs/xtrader_csv_contract.md`](xtrader_csv_contract.md). Da ricordare qui:

- **`Provider`** — l'azione di piazzamento può filtrare per provider (confronto **non**
  case-sensitive). Tenerlo **stabile**: cambiarlo è anche il trucco documentato per far riusare
  un segnale già giocato.
- **`Price`** — usata solo se la strategia attiva «Usa quota segnale se indicata».
- **`MinPrice` / `MaxPrice`** — condizioni di validità: se la quota richiesta è fuori range la
  scommessa **non parte**, a meno che la strategia non spunti «Ignora limite quote».
- **`Points`** — moltiplicatore dello stake, usato **solo** se la strategia attiva l'opzione
  relativa. BetRelay lo lascia vuoto.
- **`MarketType`** — i codici ammessi sono quelli del palinsesto Betfair, identici in tutte le
  versioni del software. L'elenco completo con le etichette italiane è negli screenshot
  `condizioni/20`, `21`, `22`, `23`, `24` (da `ALT_TOTAL_GOALS` a `YOUNG_PLAYER`, inclusi
  `MATCH_ODDS` = Esito Finale, la famiglia `OVER_UNDER_xx`, e la variante italiana
  `CORRECT_SCORE_IT`).

---

## 6. Scegliere i mercati: Filtro Mercati e Processors

**Filtro Mercati** (`Funzioni` → `Filtro Mercati`, **F3**) — screenshot `varie/05`, `varie/06`.
Seleziona su quali mercati lavorare per nazione, competizione, tipo di mercato, orario di inizio,
stato in gioco, liquidità minima. **La casella «Segnali» filtra i soli mercati che hanno un
segnale**: è il modo di isolare esattamente i mercati arrivati da BetRelay. I filtri si salvano e
si richiamano per nome.

**Processors Mercati** (`Funzioni` → `Processors Mercati`, **ALT+MAIUSC+M**) — screenshot
`varie/07`, `varie/08`, `varie/09`, `varie/10`. Un processor applica **automaticamente** una
strategia ai mercati che rientrano in un filtro salvato, a cadenza. Parametri: Tipo Evento, Filtro
Mercati, Frequenza di aggiornamento, «Mercati che iniziano in», la Strategia da applicare, la
durata dell'intervallo di riferimento e il **numero massimo di applicazioni** in quell'intervallo.
La scheda **Log** dice cosa ha fatto: è la prima cosa da guardare quando «la strategia non parte».

> **Nota di sicurezza da dare sempre.** «Numero massimo applicazioni nell'intervallo di
> riferimento» è un freno: senza un valore sensato un processor può applicare la strategia a
> moltissimi mercati in una volta.

---

## 7. Dal segnale alla scommessa: l'azione «Piazza Scommesse su Segnali»

Struttura dell'automazione (screenshot `azioni-se-vero-se-falso/01`):

```text
Strategia
└── Regola                      ← quando e quante volte
    ├── Condizioni [AND/OR]     ← se
    ├── azioni se vero          ← allora
    └── azioni se falso         ← altrimenti
```

L'azione che consuma i segnali è **«Piazza Scommesse su Segnali»** (screenshot
`azioni-se-vero/04`). I suoi campi, e a quale colonna del CSV corrispondono:

| Campo dell'azione | Effetto |
|---|---|
| **Usa quota segnale se indicata** | usa `Price` invece della quota impostata nell'azione |
| **Solo segnali mai utilizzati** | salta i segnali che risultano già giocati |
| **Modula lo Stake con dato Points** | moltiplica lo stake per `Points` |
| **Provider** | filtra per la colonna `Provider` (non case-sensitive); vuoto = nessun filtro |
| **Piazza su Segnali Punta / Banca** | quali `BetType` accettare: `PUNTA` e/o `BANCA` |
| **Ignora limiti quote punta / banca** | bypassa `MinPrice`/`MaxPrice` |
| **Tag** | etichetta le scommesse generate (serve per cancellarle selettivamente) |

**Regola del manuale**: *ad ogni esecuzione di una strategia ciascun segnale può essere utilizzato
una sola volta*. Per riusarlo servono: una nuova esecuzione, un `Provider` diverso, o un'altra
strategia. Quando un segnale viene giocato, nell'elenco compaiono **ID scommessa**, **data** e
**nome strategia**, e la riga si colora di **verde**; si azzerano editando il segnale.

---

## 8. Le tre reti anti-doppione (metterle tutte)

Il rischio numero uno di una catena automatica è piazzare due volte lo stesso segnale. Ci sono tre
protezioni **indipendenti**, e vanno usate insieme:

1. **Lato bridge** — un solo segnale attivo nel CSV, deduplica persistente, svuotamento a timeout.
2. **Lato regola** — scheda «Numero Esecuzioni» (screenshot `condizioni/13`): `Numero esecuzioni`
   e `Attesa dopo esecuzione`. Diffidare di «Numero esecuzioni illimitato».
3. **Lato mercato** — condizione **«Conta scommesse»** (screenshot `condizioni/42`) messa in AND:
   *nessuna scommessa già presente su quella selezione*. Più la condizione **«Scommessa In
   Piazzamento»** negata (screenshot `condizioni/45`), che copre la finestra in cui un ordine è
   già partito ma non ancora confermato.

E l'opzione **«Solo segnali mai utilizzati»** dell'azione, che è una quarta rete sul segnale.

---

## 9. Guardie che conviene mettere prima di piazzare

Non sono consigli di trading: sono controlli di **sanità tecnica** del mercato, che evitano ordini
destinati a restare appesi.

| Condizione | Screenshot | Perché |
|---|---|---|
| **Stato del Mercato = APERTO** | `condizioni/28` | un mercato sospeso non accetta scommesse |
| **Stato Selezione = ACTIVE** | `condizioni/29` | la selezione può essere stata rimossa dopo la scrittura del segnale |
| **Mercato NON in gioco** | `condizioni/30` | un segnale pre-match giocato a partita iniziata trova quote tutt'altre |
| **Liquidità Disponibile** ≥ soglia | `condizioni/33` | senza denaro sul lato giusto l'ordine resta non abbinato |
| **Profitto / Perdita Conto** (Oggi) | `condizioni/44` | stop loss giornaliero: il paracadute di ogni automatismo |
| **Saldo Conto Betfair** | `condizioni/47` | non piazzare sotto una soglia di cassa |

---

## 10. Verifica end-to-end (in sicurezza)

1. **BetRelay in 🧪 Simulazione**: il CSV operativo non viene nemmeno scritto. Serve a verificare
   che il messaggio Telegram venga riconosciuto e che la riga generata sia quella attesa
   («🧪 Prova messaggio» del parser).
2. **BetRelay in 🔬 Collaudo** + **XTrader in modalità simulazione**: il CSV viene scritto davvero.
   Aprire la finestra Segnali e verificare che compaia **una riga verde**. Se è rossa, la causa è
   in §3/§4.
3. Applicare la strategia e controllare che nel segnale compaiano **ID scommessa** e **nome
   strategia** (riga verde nell'elenco).
4. Attendere il timeout e verificare che il CSV torni a **sola intestazione** e che il bridge lo
   segnali nel log.
5. Solo dopo, e solo se tutto quanto sopra è verificato, valutare la modalità **⚠️ Reale** — che
   nel bridge richiede di digitare la parola `REALE`, mostra un banner rosso persistente e chiede
   conferma a ogni avvio.

---

## 11. Diagnosi: sintomo → dove guardare

| Sintomo | Causa tipica |
|---|---|
| In XTrader non arriva **niente** | percorso file diverso fra i due programmi; oppure BetRelay è in Simulazione (non scrive); oppure la fonte non ha il refresh automatico attivo |
| Il segnale c'è ma è **rosso** | riconoscimento per nomi con **lingua** sbagliata (§4); nomi non coincidenti col palinsesto; evento già concluso; con riconoscimento per id, id di un altro exchange |
| Segnale **verde**, ma nessuna scommessa | la strategia non è applicata a quel mercato (controllare il **Log** del processor); una condizione in AND non è soddisfatta; `MinPrice`/`MaxPrice` fuori range senza «Ignora limite quote»; filtro **Provider** che non combacia |
| Scommessa **non abbinata** | quota del segnale non più disponibile; liquidità insufficiente (`condizioni/33`); spread largo (`condizioni/25`) |
| Il segnale **sparisce** dopo poco | comportamento **corretto**: è lo svuotamento a timeout (§2) |
| Un segnale cancellato **ritorna** | comportamento **atteso**: la fonte con auto-refresh rilegge il file (§2) |
| **Doppia** scommessa | mancano le reti del §8 |

---

## 12. Per l'assistente AI: cosa può e cosa non deve

**Può**: spiegare i campi di ogni finestra citando lo screenshot del catalogo; guidare passo passo
la creazione della fonte; tradurre un'intenzione dell'utente nei nomi esatti di condizioni e azioni;
diagnosticare con la tabella del §11; ricordare le reti anti-doppione e le guardie.

**Non deve**: piazzare scommesse o parlare con XTrader/Betfair; avviare il listener o la modalità
reale; scrivere il CSV operativo; dare consigli di scommessa, pronostici o selezioni da giocare;
indebolire il filtro `chat_id`; mostrare o chiedere token, chat ID, credenziali.

**Deve dire quando non sa**: il catalogo copre le finestre fotografate, non tutto XTrader. Se la
risposta non è nel catalogo, nel manuale o in queste pagine, l'assistente lo dice e rimanda alla
documentazione ufficiale invece di inventare un percorso di menu.

### Dove cercare

| Domanda | Fonte |
|---|---|
| «dov'è il pulsante X?» | `catalogo.md` — campo *finestra* e *descrizione* |
| «cosa ci metto in questo campo?» | questo documento, §2–§7 |
| «quali condizioni esistono?» | `condizioni/17` (indice completo) |
| «quali azioni esistono?» | `azioni-se-vero/01` (indice completo) |
| «che valore posso mettere in MarketType?» | `condizioni/20`–`24` |
| «come scrivo una formula?» | [`xtrader_formule.md`](xtrader_formule.md) |
| «com'è fatto il CSV?» | [`xtrader_csv_contract.md`](xtrader_csv_contract.md) |
| «perché non funziona?» | §11 |

---

## Limiti dichiarati

- **Nessun passo di questa guida è stato eseguito su XTrader reale** in questo ambiente: è ricavata
  dal manuale ufficiale, dalle risposte del supporto e dagli screenshot del proprietario. Va
  verificata sul campo prima di pubblicarla come guida utente.
- Il catalogo copre **le finestre fotografate**. L'elenco completo di ciò che manca, con priorità
  e con l'indicazione di cosa oggi è ricostruito al suo posto, sta in
  [`screenshot_xtrader_mancanti.md`](screenshot_xtrader_mancanti.md).
- La dialog «Fonte Segnali» degli screenshot è quella della versione italiana alla data di cattura
  (08/07/2026): le altre versioni Betting Toolkit potrebbero avere etichette tradotte diversamente.
