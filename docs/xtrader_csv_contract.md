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
| 9 | `Handicap` | sì | default `0`; se valorizzato, numero finito con `\|Handicap\| ≤ 1000` (vedi sotto) |
| 10 | `Price` | no | quota; può essere vuota; separatore decimale secondo `csv_language` (vedi nota) |
| 11 | `MinPrice` | no | può essere vuota |
| 12 | `MaxPrice` | no | può essere vuota |
| 13 | `BetType` | sì | **`PUNTA`** (punta/back) o **`BANCA`** (banca/lay) |
| 14 | `Points` | no | moltiplicatore stake, **solo se la strategia lo richiede** (vedi sotto); se valorizzato, numero finito con `0 < Points ≤ 100`; **vuoto** negli esempi reali |

## Valori in italiano

- **`BetType`**: il bridge scrive sempre il valore **canonico italiano** `PUNTA` (equivalente di
  back) o `BANCA` (equivalente di lay), come negli esempi reali. In **ingresso** sono validi
  indifferentemente `PUNTA`/`BANCA`/`BACK`/`LAY` (accettati su tutte le versioni BT/XT — conferma
  supporto, epica multilingua #3); mapping interno: `BACK → PUNTA`, `LAY → BANCA` (l'output resta
  canonico e universale). I termini spagnoli `FAVOR`/`CONTRA` non sono ancora supportati e vengono
  **rifiutati fail-closed** (`INVALID_BETTYPE`): un lato ignoto non viene mai indovinato.
- **`Points`**: lasciato vuoto (gli esempi reali non lo valorizzano). Anche se valorizzato,
  XTrader lo usa **solo** se nella strategia è spuntata l'opzione «Modula lo Stake con dato
  Points del segnale se disponibile» — altrimenti la colonna viene ignorata (vedi «Lato
  XTrader»).
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

> **Default per le config NUOVE — gate #311-2.3 su #311-2.2.** Il default del `recognition_mode`
> per una config nuova è `NAME_ONLY` **finché il dizionario Betfair non è pienamente validato**
> contro un export XTrader reale (**ogni** riga con `Fonte="Export XTrader"` — whitelist fail-closed:
> una `Fonte` vuota/assente/typo NON conta come validata); quando lo è, passa
> **automaticamente a `BOTH`**. Motivo: con `BOTH` il bridge **accetta** un segnale sugli ID risolti
> dal dizionario; affidarsi a ID di un dizionario non verificato rischierebbe, su un match errato, di
> scrivere `MarketId`/`SelectionId` sbagliati → in modalità REALE una scommessa sul mercato/selezione
> errato. Le **config esistenti** mantengono la loro scelta esplicita; un valore malformato ricade su
> `NAME_ONLY` (fail-safe, invariante A10).

Con i nomi (`NAME_ONLY`/`BOTH`), la **lingua dei nomi scritti** nel CSV deve coincidere con
quella della fonte Segnali di XTrader (italiano) — è la config **`source_language`**, da non
confondere con `csv_language`, che governa **solo** il separatore decimale (vedi «Lato XTrader»).
**Nota:** il messaggio Telegram non contiene gli ID
(`EventId`/`MarketId`/`SelectionId`); il bridge punta sulla modalità a nomi e, quando
possibile, **potrebbe arricchirli dal dizionario Betfair locale** — meccanismo descritto qui
sotto ma **oggi disattivato**, quindi in pratica **le righe restano a nomi** (vedi l'avvertenza
nella sezione seguente).

### Identificazione precisa dal dizionario + fallback nomi (PR-P12)

> ⚠️ **Meccanismo OGGI STACCATO — questa sezione descrive il contratto, non il comportamento
> corrente.** Dopo la rimozione di «Betfair Sync» l'arricchimento ID è **disattivato** sia nel
> **CSV live** (`App._process` in `app.py` passa `id_resolver=None`) sia nell'**anteprima**
> «Prova messaggio» (`App._preview_id_resolver_factory`)
> (invariante «anteprima = runtime»: nessun «Pronto» in GUI su una riga che il live scarterebbe).
> In pratica **le righe restano a nomi**: gli ID non vengono riempiti finché non popoli a mano il
> dizionario locale e non riattivi il *seam* in **entrambi** i punti. Vedi README →
> `recognition_mode`.

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
  obbligatorio, un segnale **senza** `Price` valido (numerico, **> 1.0 e ≤ 1000.0**)
  viene **scartato** (stato `INVALID_MISSING_PRICE` / "Non pronto"). Se `Price` **non**
  è obbligatorio, la quota è opzionale e si scrive la riga col `Price` vuoto.

  Il **tetto ≤ 1000.0** (B1 audit #114) è il massimo delle quote decimali Betfair: una
  quota sopra 1000 non è reale — tipicamente un misparse del separatore migliaia
  (es. «1.000.000») — e viene **scartata** (stato `INVALID_PRICE`, fail-closed) invece
  di raggiungere XTrader come scommessa con quota folle.

Nel **Parser Personalizzato**, per lasciare `Price` vuoto: lascia la riga `Price` **non
obbligatoria** (casella «Obblig.» spenta). Non esiste più un interruttore globale
`require_price`: la quota la comanda la riga `Price` di ogni parser.
`MinPrice`/`MaxPrice`/`Points` si lasciano vuoti semplicemente non configurando la loro regola.

**Se valorizzati** da un Parser Personalizzato, questi campi facoltativi vengono comunque
validati prima di dichiarare la riga piazzabile (il percorso hardcoded li lascia vuoti, ma
un parser custom può estrarre testo arbitrario):

- **`MinPrice`/`MaxPrice`**: oltre a essere quote valide singolarmente (numeriche,
  **> 1.0 e ≤ 1000.0**, stesso tetto di `Price`),
  devono essere **coerenti** — l'intervallo non può essere invertito (`MinPrice > MaxPrice`)
  né escludere la quota selezionata (`MinPrice > Price` o `MaxPrice < Price`). I bordi sono
  inclusivi (`MinPrice == Price`/`MaxPrice == Price` sono validi). Un intervallo incoerente
  viene scartato (stato `INVALID_PRICE_BOUNDS`, fail-closed): XTrader non potrebbe usarlo.
- **`Points`** (moltiplicatore stake): se valorizzato deve essere un numero **finito** con
  **`0 < Points ≤ 100`**; testo non numerico, negativo, zero o oltre il tetto viene scartato
  (stato `INVALID_POINTS`). `Points` non viene normalizzato a "1": resta com'è (vuoto di
  default).
- **`Handicap`**: se valorizzato deve essere un numero **finito** con **`|Handicap| ≤ 1000`**
  (stato `INVALID_HANDICAP`). Il tetto è sul **valore assoluto** — «-1,5» asiatico è legittimo
  quanto «+1,5» — e 1000 copre ogni linea Betfair reale, comprese quelle grandi dei mercati a
  punti/run. Il default del contratto resta `0`.
- **Finitezza, non solo tetto (`#194` B5, fail-closed).** I due tetti sopra sono preceduti da un
  controllo di **finitezza esplicito**, e non è ridondanza. La regex del contratto accetta solo
  cifre ASCII e un separatore, quindi `inf` non può entrare per via *testuale* («inf», «1e400»
  sono respinti) — ma una stringa di **sole cifre** abbastanza lunga sì: `float("9"·400)` è
  `inf`. E l'infinito supera i confronti nel verso sbagliato (`inf <= 0.0` è `False`), perciò il
  vecchio controllo «Points deve essere > 0» rispondeva **valido** all'infinito, e un `Points`
  infinito raggiungeva il CSV — dove XTrader lo usa come moltiplicatore dello **stake**.
- **Cifre ASCII soltanto (`#318` L2-1, fail-closed).** Tutti i campi numerici del contratto
  (`Handicap`, `Price`, `MinPrice`, `MaxPrice`, `Points`) sono validati con `[0-9]` — **solo
  cifre ASCII**. Un valore scritto con cifre Unicode non-ASCII (arabo-indiane «١٩», devanagari
  «१९», fullwidth «１９») viene **scartato** come non numerico, anche se `float()` di Python
  saprebbe interpretarlo: XTrader legge solo numeri ASCII, quindi un valore non-ASCII non deve
  mai raggiungere il CSV.

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
  **Gli spazi iniziali non contano (P3-cw1 #166).** Excel, LibreOffice e Sheets *ignorano* gli
  spazi in testa quando decidono se una cella è una formula: « =1+1» viene valutata come
  «=1+1». La decisione si prende quindi sul valore **spogliato** (`strip()`) — lo stesso su cui
  si è sempre deciso se fosse un numero — mentre ciò che finisce nel file resta il valore
  **originale**, solo preceduto dall'apice: il contenuto non viene mai riscritto. Il controllo
  dei control-char iniziali resta invece sul primo carattere *grezzo*, perché TAB/CR/LF **sono**
  spazio bianco e `strip()` li nasconderebbe.
  **I control-char *interni* non vengono neutralizzati**, ed è deliberato: dentro un campo
  quotato un a-capo è CSV valido per RFC-4180 e un parser conforme lo rilegge come un solo
  campo (verificato con un round-trip scrittura→rilettura nei test). Resta fuori dalla garanzia
  il caso di un reader non conforme.
- **Separatore decimale — lingua CSV (#342/#343).** Il formato scritto nel file è governato
  dalla config **`csv_language`** (`IT`/`EN`/`ES`, default **`IT`**, allineata dal **selettore
  lingua al primo avvio**, #343): con `IT`/`ES` le colonne decimali (`Price`, `MinPrice`,
  `MaxPrice`, `Points`, `Handicap`) escono con la **virgola** («1,85», «-0,5»); con `EN` col
  **punto**. Le versioni precedenti di XTrader ITA **richiedevano** la virgola; dall'update
  «decimali intelligenti» (confermato dal supporto, #343) XTrader/Betting Toolkit **accetta
  sia il punto `.` sia la virgola `,` su tutte le colonne decimali, `Handicap` compreso, per
  tutte le lingue** —
  la scelta per-lingua resta come belt-and-suspenders, non è più un requisito critico.
  Valore mancante/malformato → `IT` (fail-closed). Le colonne **testuali** (`SelectionName`
  «Over 2.5 Goals», `MarketName`…) non vengono **mai** toccate.
- **Normalizzazione interna del prezzo** (`Price`/`MinPrice`/`MaxPrice`). A monte della scrittura
  il bridge resta **canonico col punto** (validatori/dedup invariati) e normalizza l'input così:
  - solo virgola → decimale: `1,85` → `1.85`;
  - solo punto: invariato (`1.85`);
  - **entrambi** i separatori: l'**ultimo** è il decimale e l'altro le **migliaia**, ma SOLO se il
    raggruppamento è valido (`1.234,56` → `1234.56`, `1,234.56` → `1234.56`). Un doppio separatore
    **malformato** (es. `1.2,3`, gruppo non da 3 cifre) NON viene "aggiustato": resta invalido ed è
    **scartato** (`INVALID_PRICE`), per non scrivere nel CSV un prezzo sbagliato ma plausibile.
  La localizzazione alla lingua avviene **solo** al momento della scrittura del file
  (`csv_writer`): un valore non numerico non viene mai "aggiustato" in scrittura.
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
- **Blocco multi-riga e tetto (#192, auto-raise).** Un singolo messaggio Telegram che genera **più
  righe** (MultiMarket/MultiSelection) è trattato come **un unico blocco/istruzione coerente**: le
  sue righe restano attive **insieme**. In `APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED` il tetto
  `max_active_signals` **non spezza** il blocco di un singolo messaggio — se il messaggio ha più
  righe dello spazio libero, il tetto viene **auto-alzato** per quel messaggio (tutte le righe
  entrano) invece di scriverne solo alcune e troncare le altre in silenzio. Il tetto continua a
  limitare l'accumulo **tra messaggi distinti**. Un **nuovo segnale bloccato dal tetto** (#259 C2)
  **non riscrive** il CSV se non è scaduto nulla: il contenuto attivo su disco è già identico e
  riscriverlo farebbe solo riconsumare il file a XTrader. Il CSV viene invece **riscritto** con le
  sole righe attive correnti quando il disco va riallineato: se nel frattempo **sono scadute**
  righe (una coda sovra-riempita dall'auto-raise può scadere restando piena), oppure se il CSV è
  **sospetto stantio** perché una riscrittura precedente (post-conferma o post-scadenza) è fallita
  e il suo retry breve non è ancora riuscito — così né una riga scaduta né una già confermata
  restano su disco.
  In `OVERWRITE_LAST` (default) il blocco riscritto è
  l'**istruzione corrente**: le righe nuove del messaggio **più** le righe duplicate che sono
  **ancora attive con la stessa provenienza** (riconosciute per chiave memorizzata al piazzamento,
  non ricalcolata), con i **valori del messaggio corrente**. Il CSV viene riscritto **solo se il
  blocco differisce — per contenuto — dalle righe già attive**: un messaggio che si espande da `A` a
  `A+B` **non perde** `A`; un duplicato **scaduto** **non** viene rivissuto (il clear-timeout resta
  garantito dall'auto-svuotamento); due regole che danno la **stessa riga** non la scrivono due
  volte; uno shrink `A+B→A` **rimuove** `B`; un reinvio **identico** — anche solo con le righe
  **riordinate** (`A+B` vs `B+A`) — **non** riscrive il CSV (XTrader non riconsuma) e un blocco
  vuoto **non** svuota il CSV.

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

## Lato XTrader — risposte del supporto (ticket, luglio 2026)

> **Fonte:** risposte del supporto XTrader al proprietario, raccolte a **luglio 2026**.
> Descrivono il comportamento del **lettore** (XTrader), che il bridge non può verificare
> coi propri test: qui sono registrate perché la prossima domanda su lingue, ID o `Points`
> abbia una risposta nel repository invece che in un ticket. Dove un punto è già implementato
> e documentato sopra, questa sezione **rimanda** invece di ripetere.

### Come XTrader consuma il CSV

- **Le automazioni scaricabili dalla community NON funzionano con i Segnali.** Per usare un CSV
  di segnali serve una strategia con l'azione dedicata **«Piazza Scommessa su Segnali»** — la
  stessa che porta lo `Stake` (vedi «Cosa NON è nel CSV»). Un'automazione generica scaricata
  non leggerà il file.
- **`Points` è un moltiplicatore dello stake, ma solo su richiesta.** XTrader applica la colonna
  **soltanto** se nella strategia è spuntata l'opzione **«Modula lo Stake con dato Points del
  segnale se disponibile»**; senza quella spunta la colonna è inerte. Il bridge la lascia vuota
  di default e la scrive solo se un Parser Personalizzato la valorizza (numero `> 0`).
- **Un CSV può contenere più segnali insieme**: righe con selezioni, mercati, eventi e persino
  `Provider` diversi convivono nello stesso file. **Una riga = un segnale.** Il bridge sfrutta
  questa possibilità solo nelle modalità multi-riga (`APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED`) e
  nei blocchi multi-riga di un singolo messaggio: in `OVERWRITE_LAST` (default) resta **una sola
  riga attiva** per scelta di sicurezza del bridge, non per un limite di XTrader.

### Colonne

- **`MarketName` non è obbligatorio** — coerente con la tabella colonne sopra.
- **Le colonne interamente vuote possono essere omesse** dal file. Il bridge **scrive comunque
  tutte e 14** le colonne nell'ordine fisso: è la forma degli esempi reali, non richiede logica
  condizionale ed è quella coperta dai test. Omettere colonne non è un'ottimizzazione che ci
  interessa, e cambiarla sarebbe un breaking change del contratto.
- **Separatore decimale**: XTrader accetta ormai **sia il punto `.` sia la virgola `,`** su tutte
  le colonne decimali, **`Handicap` compreso** (vedi «Regole di scrittura» → `csv_language`).
  *Nota di lettura:* qui «punto» e «virgola» sono i due **separatori decimali** alternativi, non
  il carattere punto-e-virgola `;` — che nel CSV non compare mai (il separatore di campo è la
  virgola, con tutti i valori tra doppi apici).
- **Le quote hanno al massimo 2 cifre decimali** (`1.25` sì, `1.225` mai): è il listino Betfair,
  non un limite del CSV. Il bridge non arrotonda né rifiuta per questo motivo — lo registra
  perché è l'assunzione dietro al riconoscimento della virgola decimale nell'identità di riga.

### Riconoscimento evento / mercato / selezione

- **Quando gli ID sono noti, XTrader preferisce `MarketId`/`SelectionId`**: è il riconoscimento
  più preciso. È ciò per cui esiste l'arricchimento dal dizionario Betfair (vedi sopra) — che però
  **oggi è staccato** (`id_resolver=None`) e comunque, quando riattivato, resta **fail-open sui
  nomi** se il match non è univoco. Allo stato attuale il bridge scrive **righe a nomi**: la
  preferenza di XTrader per gli ID è un vantaggio **non ancora sfruttato**, non una promessa del
  bridge.
- ⚠️ **Gli ID non sono portabili tra exchange.** Lo stesso evento ha `MarketId`/`SelectionId` —
  e a volte anche **nomi** — **diversi** su Betfair `.it` e `.com`. Un dizionario costruito da un
  export `.it` non vale per un account `.com`. È una ragione in più per cui il default delle
  config nuove resta `NAME_ONLY` finché il dizionario non è validato contro un export reale.
- **Il riconoscimento a nomi richiede di dichiarare la lingua della fonte** in XTrader, e i nomi
  nel CSV devono essere in quella lingua. Da qui la config **`source_language`** (#3 slice 5a),
  che filtra dizionario nomi e dizionario mercati.
  ⚠️ **`source_language` NON è `csv_language`, e confonderle porta a un CSV sbagliato:**
  `source_language` riguarda la **lingua dei nomi** (`EventName`, `SelectionName`, `MarketType`)
  usati per il riconoscimento; `csv_language` riguarda **solo il separatore decimale** delle
  colonne numeriche e **non tocca mai** una colonna testuale. Impostare `csv_language=IT`
  **non** traduce i nomi, e impostare `source_language=IT` **non** cambia come sono scritte le
  quote.
- **Il metodo di riconoscimento si eredita dalla fonte Segnali** ed è modificabile per singolo
  segnale dentro XTrader; ⚠️ **modificarlo a mano può duplicare il segnale** al refresh
  automatico della fonte. Non è qualcosa che il bridge possa prevenire: è una raccomandazione
  operativa lato XTrader.
- **Struttura e intestazioni sono identiche in tutte le lingue** di XTrader: il file non cambia
  forma passando IT/EN/ES.
- **I codici `MarketType` sono identici in tutte le lingue** (es. `MATCH_ODDS`; `CORRECT_SCORE`
  confermato dal supporto).
- ⚠️ **Il nome del mercato Over/Under dipende dalla lingua della fonte**: con fonte **italiana**
  è nella forma con la **virgola** (`Over 2,5`), con fonte **UK** col **punto** (`Over 2.5`).
  Attenzione: è una colonna **testuale**, che il bridge non tocca mai (vedi «Regole di
  scrittura» → il separatore decimale si applica solo alle colonne numeriche). La forma corretta
  la decide chi scrive la regola del Parser Personalizzato o il dizionario: la variante sbagliata
  per la lingua dichiarata significa che **XTrader non trova il mercato**.
- **`BetType`**: `PUNTA`/`BANCA`/`BACK`/`LAY` sono accettati **in ingresso** su tutte le versioni
  BT/XT — ma questo **non** autorizza un CSV con `BACK`/`LAY`: ciò che il bridge **scrive** resta
  sempre il canonico italiano `PUNTA`/`BANCA` (vedi «Valori in italiano»). Gli equivalenti
  spagnoli `FAVOR`/`CONTRA` sono **annunciati ma non ancora disponibili**: il bridge li rifiuta
  **fail-closed**.

## Stato implementazione (PR-01)

- `CSV_HEADER` allineato alle **14 colonne reali** con ordine corretto. ✅
- `build_csv_row()` emette `EventId/MarketId/SelectionId` vuoti, `Handicap="0"`,
  `BetType` mappato a `PUNTA/BANCA`, `Points` vuoto. ✅
- `init_csv()`/`write_csv()` scrivono in `utf-8-sig` con `QUOTE_ALL`. ✅
- README aggiornato sul formato reale. ✅

### Svuotare il CSV: cinque funzioni, precondizioni opposte (A4 della #69)

Portano tutte allo stesso risultato — un file col **solo header** — ma **non** sono
intercambiabili: due cancellano senza chiedere, tre proteggono. Sceglierle per il nome invece
che per il contratto può far sparire un segnale che XTrader non ha ancora letto.

| funzione | crea se manca | file **estraneo** | CSV con riga **attiva** |
|---|---|---|---|
| `init_csv` | sì | **sovrascrive** | **cancella** |
| `write_rows([], path)` | sì | **sovrascrive** | **cancella** |
| `init_csv_for_session` | sì | rifiuta (`CSV_INIT_FOREIGN`) | azzera (voluto: a START la riga stantia deve sparire) |
| `create_header_only_csv` | sì | rifiuta (`..._REFUSED_FOREIGN`) | **rifiuta** (`..._REFUSED_ACTIVE`), salvo `force=True` |
| `clear_stale_csv` | **no** | rifiuta e avvisa | azzera (voluto: pulizia avvio/STOP) |

In pratica: **START/clear di sessione** → `init_csv_for_session`; **azione esplicita
dell'utente** («📄 Crea CSV», wizard) → `create_header_only_csv`, che rifiuta e fa confermare;
**pulizia avvio/STOP** → `clear_stale_csv`, che non crea nulla su un path mai usato.
`init_csv` e `write_rows([])` **non controllano niente** e vanno usate solo dove il path è già
stato validato altrove.

### `csv_path` che è un link (o dentro una cartella collegata) — #194 B7

Se `csv_path` punta a un **link simbolico** (o a una *junction* Windows), la scrittura
**attraversa il link e aggiorna il file puntato**, lasciando il link intatto. È il
comportamento che serve: XTrader legge il file vero, quindi è quello che deve cambiare.

Prima non era così, ed era pericoloso in silenzio: la lettura seguiva il link (header
riconosciuto, decisione corretta) ma il rename atomico **sostituiva il link** con un file
normale. `clear_stale_csv` riportava `True` — «ripulito» — mentre la riga stantia restava nel
file che XTrader stava leggendo. Una difesa anti-segnale-stantio che dichiara successo senza
aver fatto nulla è il modo peggiore di fallire, perché nessuno va a ricontrollare.

La risoluzione avviene in `atomic_io.atomic_write`, quindi vale per **ogni** scrittura del
contratto e non solo per lo svuotamento. Le guardie anti data-loss **non** si indeboliscono:
un link a un file **estraneo** resta rifiutato e intoccato, esattamente come prima.

La matrice vive anche nel sorgente (sopra `init_csv` in `csv_writer.py`) ed è fissata da
`tests/unit/test_csv_family_a4_69.py`: se i contratti venissero uniformati, quei test
diventano rossi.

### Output multi-riga (#192) — contratto per-riga invariato

Un singolo messaggio Telegram può ora produrre **più righe CSV** (MultiMarket/MultiSelection,
vedi `docs/custom_parser.md`). Questo **non cambia il contratto**: header e **ordine delle 14
colonne restano identici** e **ogni riga** rispetta lo stesso formato per-riga descritto qui
(quota col punto, `BetType` ∈ {PUNTA, BANCA}, `Handicap="0"` di default, ecc.). Cambia solo il
**numero di righe dati** scritte (1 → N). **Non è un breaking change.**

### Rimandato (fuori scope PR-01)

- **`SelectionName` in italiano** (es. `Over 2,5 gol`, `Sì`/`No`, `Pareggio`): localizzato
  in **PR-08** (selection mapping IT). Nota storica: in PR-01 il fallback legacy poteva
  emettere stringhe inglesi come `Over 0.5 Goals`. Oggi quel fallback **non sintetizza più**
  la selezione (audit #104 A1): se l'alias non è risolto dal dizionario, `SelectionName`
  resta `""` e la riga è scartata dal riconoscimento (fail-closed), invece di una selezione
  inglese/sbagliata.
- Scrittura **atomica** (tmp + fsync + rename): **PR-05**.
- Validazione bloccante del segnale: **PR-10**; modalità riconoscimento: **PR-06**.
