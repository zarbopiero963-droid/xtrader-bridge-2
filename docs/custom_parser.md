# Parser Personalizzato — guida (CUSTOM_PARSER_READY)

> Stato: **pronto** (PHASE 3-bis, CP-01…CP-10). Il Parser Personalizzato permette
> di definire dalla GUI *come* estrarre ogni colonna del contratto CSV XTrader da
> un messaggio Telegram, **senza modificare il codice**. Quando è attivo per una
> chat è **autoritativo**. Nel percorso **live** NON c'è fallback al parser hardcoded
> storico (CP-09b): se per la chat non è attivo alcun parser personalizzato il messaggio
> è **ignorato**. Il parser hardcoded P.Bet resta nel repo solo per **compatibilità/test**.

Questo documento descrive il comportamento reale del codice (non promesse): come
si definisce un parser, come vengono estratti e tradotti i valori, quali gate di
sicurezza proteggono il CSV, e dove vengono salvati i parser.

---

## 1. Concetto

Un **Parser Personalizzato** è un insieme di **regole**, una per colonna del CSV.
Ogni regola dice da dove prendere il valore di quella colonna nel messaggio.

Catena completa di un messaggio:

```text
messaggio Telegram
  → estrazione del valore grezzo per regola      (custom_parser_engine, CP-02)
  → trasformazione opzionale                      (transforms, CP-05)
  → value-map opzionale (alias → valore XTrader)  (value_maps, CP-03)
  → riga a 14 colonne + default contratto         (custom_pipeline, CP-04)
  → validazione (modalità + Price + BetType)      (validator, PR-10)
  → instradamento live + gate sicurezza           (signal_router, CP-07/CP-09)
  → scrittura CSV solo se "piazzabile"            (app)
```

Il contratto CSV è la **fonte unica** delle colonne ammesse
(`csv_writer.CSV_HEADER`, 14 colonne):

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
```

---

## 2. La regola (`FieldRule`)

| Campo | Significato |
|---|---|
| `target` | colonna CSV di destinazione (deve stare in `CSV_HEADER`) |
| `start_after` | "Inizia dopo": l'estrazione parte **subito dopo** questo testo |
| `end_before` | "Finisce prima": l'estrazione finisce **subito prima** di questo testo (se vuoto → fino a fine riga) |
| `fixed_value` | valore costante: se valorizzato, la colonna vale esattamente questo e l'estrazione dal messaggio è ignorata |
| `transform` | nome di una trasformazione da applicare al valore estratto (es. `score_to_over`) |
| `value_map` | nome di una value-map per tradurre il valore nel valore esatto XTrader |
| `required` | obbligatorio: se il valore finale è vuoto **o di soli spazi** (audit #259 B5) il parser è **"Non pronto"** → nessuna riga CSV. Anche un `fixed_value` di soli spazi non conta come valore. |

`fixed_value` e `start_after`/`end_before` sono **alternativi** (non si possono
mettere insieme: `validate_parser_def` lo rifiuta).

### Estrazione: delimitatori tolleranti agli spazi

I delimitatori `start_after`/`end_before` sono testo libero (anche emoji/simboli),
cercati nel messaggio con **tolleranza agli spazi**:

- spazi/tab **ai bordi** del delimitatore vengono ignorati (uno spazio iniziale o
  finale digitato per errore non rompe il match);
- i run di spazi/tab **interni** sono flessibili (uno o più): `"Esito :"` combacia
  con `"Esito :"` e `"Esito  :"`;
- **parole, simboli ed emoji restano letterali**: un delimitatore con parola o
  emoji diversa **non** combacia (`"Quota:"` ≠ `"Quotaz:"`, `📊` ≠ `📈`);
- il valore è preso dal **testo originale** (spazi/accenti **dentro** il valore
  preservati, es. `"Inter v Milan"`), poi rifilato solo ai bordi;
- i **newline non sono toccati**: un delimitatore `"\n"` resta letterale, cioè
  "fino a fine riga"; se manca l'a-capo l'estrazione fallisce (resta "Non pronto").

> Consiglio pratico: nella GUI usa il **test-live**, incolla un messaggio reale e
> verifica subito cosa estrae ogni regola.

### Trasformazioni (`transform`)

Derivano un valore calcolato da quello estratto. Built-in:

- `score_to_over`: punteggio `"6-0"`/`"6:0"`/`"6 x 0"` → `"Over 6,5"` (somma gol +
  linea `,5`). Input non interpretabile → vuoto (→ "Non pronto").

L'ordine è sempre **estrazione → trasformazione → value-map**.

### Value-map (`value_map`)

Traducono il valore grezzo nel valore esatto XTrader. Disponibili:

- `bettype`: `BACK`/`back`/sinonimi → `PUNTA`; `LAY`/`lay`/sinonimi → `BANCA`;
- mappe dal **dizionario** (`data/dizionario_xtrader.csv`): `markettype`,
  `marketname`, `selectionname`, chiavate sia sugli alias interni sia sugli
  **shorthand Telegram** (es. `"GG"` → `Sì`, `"OVER 2.5"` → mercato/selezione
  Over/Under 2,5).

**Sicuro**: value-map sconosciuta o valore non mappato → vuoto (→ "Non pronto"),
mai un lato/selezione tradotto a caso.

### Mappatura nomi squadra (`name_mapping_profiles` + `team_separator`)

Un canale può scrivere le squadre con nomi diversi da quelli che XTrader/Betfair si
aspettano nell'`EventName` (alias, abbreviazioni, lingue diverse). I **profili di
mappatura nomi** (`name_mapping_store`, config `name_mappings`) traducono i nomi
provider nei nomi Betfair/XTrader **prima** della scrittura:

- ogni profilo è una tabella a campi liberi `Betfair/XTrader ↔ Provider` (+ `Country`
  organizzativo); entrambe le colonne le compili tu;
- il parser seleziona uno o più profili (`name_mapping_profiles`) e indica il
  separatore casa/trasferta del canale (`team_separator`, testo libero: `v`, `vs`,
  `-`, `/`; vuoto = default `v`). I separatori **alfabetici** (`v`/`vs`) richiedono
  spazi attorno, così `Liverpool` non viene spezzato sulla `v` interna;
- l'`EventName` viene diviso, casa e trasferta tradotte e ricomposte nel formato
  XTrader `Casa - Trasferta` (`dizionario.compose_event_name`);
- **multi-profilo**: i profili selezionati si applicano nell'ordine dato; in caso di
  conflitto vince la **prima** corrispondenza (deterministico);
- **multi-sport (PR-P10)**: ogni riga di mappatura ha una colonna **Sport** opzionale
  (`Calcio`/`Tennis`/`Basket`/`Rugby Union` o **«(tutti gli sport)»** = agnostica). Se il
  parser ha uno **Sport** impostato, la mappatura considera SOLO le righe di quello sport o
  agnostiche — con **priorità allo sport esatto** sulle agnostiche (un override per-sport
  non viene scavalcato da una riga agnostica salvata prima) — e **salta** le righe taggate
  per un altro sport: così un nome non viene
  tradotto con una voce pensata per uno sport diverso (es. un "Milan" del basket non mappa
  un evento di calcio). La priorità vale su **entrambe** le forme di match: le righe dello
  sport esatto sono provate del tutto — sia per **alias** (colonna Provider) sia per **nome
  canonico** (colonna Betfair) — **prima** di ricadere sulle agnostiche, così un alias
  agnostico non scavalca un canonico dello sport giusto con lo stesso nome (#174). Parser
  senza sport / righe agnostiche → comportamento legacy (nessun filtro), retro-compatibile.
- **tipo entità (`entity_type`, #178 §2)**: ogni riga ha anche una colonna **Tipo**
  opzionale con i valori `participant`, `team`, `player`, `competition`, `market`,
  `selection` o **«(qualsiasi tipo)»** = agnostica (chiave di config `entity_type`; vuoto
  → agnostica, retro-compatibile con le config salvate prima del campo). Serve a
  dichiarare COSA mappa una riga, così un alias di un altro tipo non scavalca un nome
  squadra; come per lo sport, il **tipo esatto** ha priorità sull'agnostico. **Nel flusso
  live l'`EventName` (i partecipanti dell'evento) è tradotto SOLO dalle righe
  `participant`/`team`/`player` e dalle agnostiche**: le righe `competition`/`market`/
  `selection`, anche con un alias che collide, **non** traducono un partecipante (evita un
  `EventName` CSV sbagliato). Gli altri tipi restano disponibili per la risoluzione quando
  il chiamante li richiede esplicitamente.

**Sicuro (fail-closed)**: se il separatore non si trova **o** una squadra non è nei
profili (per lo sport del parser), lo stato è `MAPPING_MISSING` → **nessuna riga CSV** (un
evento sbagliato = scommessa sbagliata). Nessun nome squadra viene mai tradotto "a caso".

Altre due difese fail-closed (audit #259):

- **righe con sport/tipo NON riconosciuto** (typo: `sport="Calc1o"`, `entity_type="boh"`)
  vengono **IGNORATE** con un avviso ⚠️ nel log eventi all'avvio — prima diventavano
  agnostiche e una mappatura pensata per uno sport poteva rinominare eventi di TUTTI gli
  sport. Le righe agnostiche **intenzionali** (campo vuoto / «(tutti gli sport)») restano
  valide; per riattivare una riga ignorata basta correggere il valore.
- **quando la traduzione CAMBIA l'EventName**, gli eventuali `EventId`/`MarketId`/
  `SelectionId` estratti dalle regole-colonna vengono **azzerati** (stessa regola della
  mappatura mercati): riferivano l'evento col nome provider e nel CSV contraddirebbero il
  nome canonico appena scritto — XTrader, se prioritizza gli ID, punterebbe l'oggetto
  sbagliato. La risoluzione ID dal **dizionario locale** (PR-P12) li ricostruisce dal
  nome canonico; se la modalità richiede gli ID e il dizionario non li ha, la riga fa
  fail-closed in validazione. Se la traduzione NON cambia il nome, gli ID restano intatti.
  **Nota (rimozione «Betfair Sync»):** l'arricchimento ID è disattivato **sia** nel **CSV live**
  **sia** nell'**anteprima** «Prova messaggio» (`id_resolver=None`) — il dizionario locale va
  popolato a mano e il seam è riattivabile in entrambi i punti insieme; in `ID_ONLY` senza ID
  risolti la riga resta non piazzabile (fail-closed). Anteprima e runtime **coincidono** (niente
  «Pronto» in GUI su una riga che il live scarterebbe).
Un parser **senza profili** non applica alcuna mappatura (`EventName` invariato,
retro-compatibile).

**GUI**: i profili si gestiscono nella scheda **Mapping** della finestra «🧰 Strumenti»
(pulsante «🗺️ Mapping» nella finestra principale → `name_mapping_gui.MappingPanel`),
**area ⚽ Calcio** (`NameMappingPanel`): selettore profilo (nuovo/rinomina/elimina) e
tabella `Country | Betfair/XTrader | Provider | Sport | Tipo`. La classe
`NameMappingWindow` resta come finestra standalone (compatibilità). La tabella ha una
colonna **Sport** per riga (PR-P10: «(tutti gli sport)» = agnostica, oppure uno sport
specifico) e una colonna **Tipo** (#178 §2: «(qualsiasi tipo)» = agnostica, oppure
`participant`/`team`/`player`/`competition`/`market`/`selection`). Nel **Parser
Personalizzato** scegli
il **separatore** squadre e spunti i **profili** da usare (checkbox multi-selezione);
«Prova messaggio» risolve i profili dalla config e mostra l'`EventName` tradotto (o
`MAPPING_MISSING` se non mappabile), coerente col runtime.

#### Nomi squadra permanenti nel dizionario locale (#282: precompila)

> **Nota (rimozione «Betfair Sync»).** In origine questi nomi erano **raccolti dalla sync**
> Betfair. Con la rimozione della funzione la sync non esiste più: la tabella
> `betfair_known_teams` resta come substrato ed è **popolata a mano** dall'utente (o via import
> del suo dizionario custom). Lo schema e la precompila qui sotto sono invariati.

La colonna **Betfair/XTrader** della mappatura nomi resta **campo libero** (puoi sempre
digitare un nome), ma può essere **precompilata** coi nomi squadra **permanenti** presenti nel
dizionario locale per i 4 sport:

- per ogni evento «Home v Away» i due partecipanti sono salvati in una tabella locale dedicata
  `betfair_known_teams` (chiave `sport` + `normalized_name`, con lo **stesso** normalizzatore
  della mappatura nomi, così le chiavi combaciano);
- questa tabella è la **sola permanente**: **non** ha colonna `active` e **non** viene
  mai toccata dal mark-and-sweep, quindi i nomi restano **per sempre** anche quando
  l'evento finisce. Gli `MarketId`/`SelectionId` restano invece **effimeri** come prima
  (il loro ciclo di vita non cambia): sopravvivono i **nomi**, non gli ID;
- inserimenti ripetuti **accumulano** senza duplicare (idempotente); un evento a un solo nome
  (torneo/outright, es. «ATP Finals») **non** è una squadra e viene saltato.

**Precompila (GUI, PR 11).** Nell'area **⚽ Calcio** del Mapping (scheda «🗺️ Mapping» →
`name_mapping_gui.NameMappingPanel`) il pulsante **«📥 Precompila da Betfair»** aggiunge una
riga per ogni nome noto: **nome Betfair già scritto** nel campo (nessun menu a tendina —
resta editabile), **Sport** impostato e **Tipo** `team`; tu scrivi solo l'**alias del
canale** nel campo **Provider**, poi **💾 Salva**. È **non distruttivo e idempotente**: non
tocca le righe esistenti e **salta** i nomi già presenti (stesso sport + nome normalizzato).
Fail-safe: con **dizionario locale vuoto** avvisa e non aggiunge nulla; **se un altro strumento
tiene il lock del DB** fa fail-fast («⏳ …riprova tra poco») invece di **congelare** la GUI (legge
il DB con probe non bloccante, come il viewer del dizionario). Fonte dati:
`BetfairLocalDB.known_teams(sport)` (sola lettura).

**Ripulitura manuale (GUI, PR 11-bis).** I nomi permanenti crescono nel tempo (mai
disattivati): la scheda **«🧹 Nomi squadra»** dell'hub Strumenti
(`known_teams_gui.KnownTeamsPanel`) li **sfoglia per sport** e li **elimina** uno per uno
(pulsante **«🗑 Elimina»**), l'unico modo per togliere un nome obsoleto/errato (squadra
retrocessa/rinominata) — `BetfairLocalDB.delete_known_team(sport, normalized_name)`. Come le
altre viste sul dizionario locale, è **fail-fast** se il DB è occupato («⏳ …riprova tra poco»,
niente freeze) e best-effort (DB assente → avviso).

#### Valori permanenti di mercato/selezione nel dizionario locale (#283: data layer)

> **Nota (rimozione «Betfair Sync»).** In origine questi valori erano **raccolti dalla sync**
> Betfair; con la rimozione della funzione la sync non esiste più e il dizionario locale è
> **popolato a mano** dall'utente. Il data layer (schema + lettura) resta invariato.

Oltre ai nomi squadra, il dizionario locale conserva in modo **permanente** i valori
universali di **MarketType**, **MarketName** e **SelectionName** dei 4 sport, così restano
disponibili (per il Parser) anche quando l'evento finisce e gli ID scadono. Decisione del
proprietario: **«diretto», nessuna mappatura** — i nomi Betfair (locale IT) sono già identici a
quelli attesi da XTrader, quindi il valore viene **persistito così com'è** (a differenza dei nomi
squadra della #282, che restano con mappatura provider→Betfair).

- per ogni mercato presente nel dizionario i valori vengono salvati in una tabella locale
  dedicata `betfair_known_market_terms` (chiave `sport` + `market_type` + `normalized_market`
  + `normalized_selection`, stesso normalizzatore del resto del dizionario; il `market_type`
  è **parte della chiave** così due mercati con lo stesso nome ma tipo diverso non collidono).
  Ogni riga è la **tupla coerente** `(sport, market_type, market_name, selection_name)` — così
  la selezione resta legata al suo mercato (invariante «la selezione appartiene al mercato»);
- come `betfair_known_teams`, la tabella è **permanente**: nessuna colonna `active`, mai
  toccata dal mark-and-sweep. `MarketId`/`SelectionId` restano **effimeri**;
- inserimenti ripetuti **accumulano** senza duplicare (idempotente); nuovi valori compaiono man mano che l'utente popola il dizionario.

**Principio safety-critical (SelectionName).** `MarketType` e `MarketName` sono descrittori
**universali** (es. `MATCH_ODDS` / «Esito Finale», `OVER_UNDER_25` / «Over/Under 2,5») → validi
per **tutti** i mercati. Le **SelectionName**, invece, andrebbero conservate **solo** per i
mercati i cui esiti sono **universali** (Over/Under di qualunque soglia, `BOTH_TEAMS_TO_SCORE`
Sì/No, `ODD_OR_EVEN`). I
mercati **team-dipendenti** (`MATCH_ODDS`, `*_HANDICAP`, `CORRECT_SCORE`, `DRAW_NO_BET`,
`DOUBLE_CHANCE` — su Betfair i suoi runner sono «{Home} o Pareggio», non «1X/12/X2», …)
hanno come esiti i **nomi delle squadre** o valori **per-partita**: fissarne uno come
SelectionName scriverebbe una riga CSV sbagliata (scommessa sbagliata), perciò **non**
contribuiscono selezioni. Il criterio è **conservativo e fail-closed** (nel dubbio un mercato
resta fuori). Per i risultati esatti (`CORRECT_SCORE` FT e
primo tempo) è tracciata a parte l'estrazione dinamica per-riga dal messaggio (issue #325).

> Letture (data layer): `BetfairLocalDB.known_market_types(sport)` /
> `known_market_names(sport)` / `known_selection_names(sport, market=None)`.

**Tendine nel Parser (PR 13).** Nella tabella regole del Parser Personalizzato, le righe
**MarketType / MarketName / SelectionName** hanno in colonna **«Valore fisso»** una **tendina
editabile** (`CTkComboBox`) popolata da questi valori permanenti, **filtrati per lo sport del
parser** (la tendina Sport in alto). A differenza della riga **Provider** (tendina a scelta
fissa dall'anagrafica), qui la tendina è **editabile**: suggerisce i valori presenti nel dizionario **ma
il testo libero resta digitabile**, così un valore valido non ancora nel dizionario è comunque
inseribile (nessuna regressione fail-closed). Le tendine si aggiornano al **cambio sport** e
quando la scheda torna attiva nell'hub Strumenti (una modifica al dizionario nel frattempo può
aver aggiunto valori). Fonte dati: `App._known_market_terms(sport)` — sola lettura, **fail-fast**
se un altro thread tiene il lock del DB (probe non bloccante: nessun suggerimento momentaneo
invece di congelare la GUI), DB assente → nessun suggerimento. La coerenza «selezione appartiene al mercato» resta garantita
dal picker **«Catalogo XTrader»** (che imposta la tripla Mercato→Tipo→Selezione); le tendine
per-riga offrono i valori per-sport senza cascading Mercato→Selezione (fuori scope PR 13).

### Mappatura mercati a frase (`market_mapping_profiles`)

Alcuni canali scrivono il **mercato a parole** dentro il messaggio (es. `Quota 0,5 HT
Prematch`). I **profili di mappatura mercati** (`market_mapping_store`, config
`market_mappings`) leggono il mercato **da una posizione precisa** del messaggio e lo
traducono nel **Mercato + Selezione XTrader** canonici (gli stessi del Catalogo del builder):

- ogni **voce** è `(Inizia dopo, Finisce prima, Testo mercato) → (MarketType, MarketName,
  SelectionName)`. I delimitatori **Inizia dopo / Finisce prima** funzionano **come nel
  Parser** (match tollerante agli spazi; se *Finisce prima* è vuoto → fino a fine riga). Si
  estrae il campo, e se vi compare il **Testo mercato** (case-insensitive, su confini di
  token) la voce scatta. Mercato e selezione **non** sono testo libero: si scelgono dal
  Catalogo XTrader, così il CSV è sempre canonico;
- **perché a delimitatori e non "frase su tutto il messaggio"**: molti provider mettono in
  testa un **banner/menu** con più mercati (es. `P.Bet. 30/0,5HT/1,5HT/1 ASIATICO`); cercare
  la frase nell'intero testo darebbe falsi match/ambiguità. Leggendo **solo** il campo
  delimitato (es. fra `Quota` e `Prematch`) si prende il mercato vero e si ignora il banner.
  Una voce **senza** delimitatori è **preservata** in config (le mappature vecchie non si
  perdono) ma **non applicata** dal bridge finché non aggiungi i delimitatori — la modalità
  "frase su tutto il messaggio" è rimossa, ma senza cancellare dati;
- **precedenza (D1): il dizionario VINCE.** Se una voce combacia in modo univoco, imposta
  `MarketType`/`MarketName`/`SelectionName` **sovrascrivendo** quelli eventualmente estratti
  dalle regole-colonna. Se **nessuna** voce combacia, restano i valori delle regole-colonna.

**Sicuro (fail-closed)**: match **ambiguo** (più voci → mercati diversi nello stesso campo)
→ stato `MARKET_MAPPING_MISSING`, **nessuna riga CSV** (un mercato sbagliato = scommessa
sbagliata). Se nessuna voce combacia **e** le regole-colonna non hanno prodotto un
mercato per la modalità di riconoscimento → ancora `MARKET_MAPPING_MISSING` (mai un
mercato inventato). Una voce con coppia Mercato/Selezione **non nel Catalogo** viene
ignorata (mai scritta); una valida ma non-canonica (case/spazi, `market_type` stantio) è
riportata ai valori canonici del catalogo. Un parser **senza profili mercati** non applica
alcuna mappatura (colonne invariate, retro-compatibile).

La mappatura mercati è **basata sui nomi** (imposta `MarketType`/`MarketName`/
`SelectionName`; il Catalogo non ha gli ID). Per evitare una riga con **identificatori
contraddittori**, quando il dizionario vince la coppia `MarketId`/`SelectionId`
eventualmente estratta dalle regole-colonna viene **azzerata**: il mercato della riga è
univocamente la tupla a nome del dizionario. Conseguenza voluta: un parser in modalità
**ID_ONLY** che usa anche la mappatura mercati a frase, al match, fa **fail-closed** in
validazione (gli ID azzerati mancano) — è una combinazione incoerente e non deve produrre
una scommessa su ID che contraddicono la frase. In **BOTH** la coppia a nome basta, quindi
la riga resta valida senza ID stantii.

**GUI**: l'area **🎯 Mercati** della scheda **Mapping** (`MarketMappingPanel`) è ora
**funzionante**: selettore profilo (nuovo/rinomina/elimina) + tabella `Inizia dopo |
Finisce prima | Testo mercato | Mercato (catalogo ▾) | Selezione (catalogo ▾)`, dove i
delimitatori ritagliano il campo del messaggio, il Testo mercato lo riconosce, e
Mercato/Selezione si scelgono dai menù del Catalogo XTrader (la Selezione dipende dal
Mercato) con `MarketType` derivato dal Catalogo. I profili persistono in `config.json` → `market_mappings`. Rinominare/eliminare un
profilo aggiorna/avvisa i parser che lo selezionano
(`rename_market_mapping_profile_in_files` / `parsers_using_market_mapping_profile`).

Nel **Parser Personalizzato** (`CustomParserPanel`) c'è ora la riga **«Mappatura mercati»**:
un pulsante **«🎯 Dizionario mercati»** (apre `MarketMappingWindow`) e le **checkbox dei
profili mercati** (multi-selezione), accanto a quelle dei nomi squadra. Al salvataggio del
parser i profili spuntati finiscono in `market_mapping_profiles`. Come per i nomi, un profilo
selezionato ma **non più esistente** in config compare come voce **⚠ fantasma** che **blocca
il salvataggio** (e l'anteprima) finché non lo si ricrea o si toglie la spunta — così un
profilo rinominato/eliminato non viene mai riscritto stantio nel parser (niente
`MARKET_MAPPING_MISSING` silenzioso). «Prova messaggio» risolve i profili mercati dalla config
e imposta Mercato/Selezione come il runtime (o fa fail-closed con `MARKET_MAPPING_MISSING`).

---

## 2bis. Modalità di riconoscimento e griglia a 14 colonne

Il builder mostra **tutte e 14 le colonne del contratto già pronte, in ordine fisso**
(una riga per colonna): compili quelle che ti servono e lasci vuote le altre — non si
aggiungono/scelgono colonne a mano, così l'ordine è sempre corretto e non se ne dimentica
nessuna.

La **Modalità** di riconoscimento (`ID_ONLY` / `NAME_ONLY` / `BOTH`) è una proprietà
**del parser** (salvata nel file, campo `mode`; default `NAME_ONLY`). Selezionandola dal
menu — **e già all'apertura di un parser nuovo** con la modalità di default — le colonne
richieste da quel set diventano **obbligatorie in automatico** (auto «Obblig.»), senza
spuntarle a mano:

| Modalità | Colonne rese obbligatorie |
|---|---|
| `NAME_ONLY` | `EventName`, `MarketType`, `SelectionName` |
| `ID_ONLY` | `MarketId`, `SelectionId` |
| `BOTH` | nessuna forzata (basta **un** set completo: lo decidi tu) |

`Price`, `BetType`, `Provider` non dipendono dalla modalità (la loro obbligatorietà la
gestisci tu). In particolare la casella **«Obblig.» sulla riga `Price`** è l'**unico
comando della quota**: se spuntata il segnale deve avere una quota valida (`>1.0`),
altrimenti è scartato; se non spuntata la quota è opzionale (CSV con `Price` vuoto
ammesso, la quota la mette poi l'azione XTrader). Non esiste più un interruttore globale. A **runtime** la validazione del segnale usa la modalità **del parser**:
ogni parser porta la sua, coerente col builder. **Eccezione (compatibilità):** un parser
salvato *prima* di questa feature non ha il campo `mode` (resta `""`) e in quel caso il
runtime **eredita la modalità globale** `recognition_mode`, così i parser vecchi non
cambiano comportamento. I parser creati/salvati dalla GUI hanno sempre una modalità
esplicita (incl. la voce «(eredita globale)» se la scegli apposta).

### Sport del parser (multi-sport)

Ogni parser può dichiarare uno **Sport** (menu a tendina accanto a «Modalità»): uno fra
**Calcio / Tennis / Basket / Rugby Union**, oppure **«(non specificato)»** = parser
**agnostico**. È salvato nel file del parser (campo `sport`; vuoto = non specificato) ed è
la fonte unica degli sport (`xtrader_bridge/sports.py`), usata dal parser e dalla risoluzione
ID del dizionario locale, con la mappa allo `event_type_id` ufficiale Betfair
(Calcio=1, Tennis=2, Basket=7522, Rugby Union=5).

Lo Sport **non cambia le colonne CSV** (restano le 14 generiche): serve a indicare a quale
sport appartiene il segnale così che — nelle versioni successive — la risoluzione degli ID
Betfair (`EventId`/`MarketId`/`SelectionId`) dal dizionario locale possa restringersi
all'`event_type_id` corretto. Uno Sport non riconosciuto (file manomesso) **blocca** la
validazione invece di scegliere un event_type_id a caso; un parser salvato *prima* di questa
feature non ha il campo `sport` e resta **agnostico** (retro-compatibile). Poiché il parser
attivo è per profilo (`active_parser`/`parser_by_chat` nello snapshot del profilo), cambiando
profilo cambia anche lo Sport del parser usato.

### Anagrafica Provider

La colonna **`Provider`** si compila da un **menu a tendina** con i nomi provider salvati
(invece di digitarli ogni volta): così eviti errori di battitura — il Provider deve
combaciare col filtro Provider dell'azione XTrader — e riusi gli stessi nomi su più
parser. Il pulsante **«➕ Provider»** aggiunge un nuovo nome all'anagrafica (salvato in
`config.json` sotto `providers`, condiviso fra tutti i parser). Un valore Provider già
presente nel parser ma non (più) in anagrafica resta selezionato e non si perde.

Per una gestione completa dell'anagrafica c'è il pulsante **«📇 Provider»** nella GUI
principale: apre una finestra dedicata dove **vedere**, **aggiungere** e **rimuovere** i
nomi provider salvati, senza dover aprire il builder. Le modifiche persistono subito in
`config.json` (chiave `providers`) e si riflettono nelle tendine della colonna Provider.

---

## 3. Gate di sicurezza (perché non scrive righe sbagliate)

Tutti questi gate devono passare perché una riga venga scritta:

1. **"Non pronto"** (obbligatori): se un campo `required` è vuoto dopo
   estrazione/trasformazione/value-map → nessuna riga CSV.
2. **Validazione contratto**: `Price` deve essere numerico `> 1.0`,
   `BetType` è uno dei quattro lati validi `{PUNTA, BANCA, BACK, LAY}` (indifferenti su tutte le
   versioni BT/XT, #3; l'output CSV resta canonico `PUNTA`/`BANCA`; ES `FAVOR`/`CONTRA` non ancora
   supportati → rifiutati), e i campi richiesti dalla modalità di
   riconoscimento (`ID_ONLY`/`NAME_ONLY`/`BOTH`) devono esserci. Il separatore
   decimale di `Price`/`MinPrice`/`MaxPrice` è normalizzato **internamente** a `.`
   (rappresentazione canonica: es. `1,85`→`1.85`; `1.234,56`→`1234.56` con raggruppamento
   migliaia valido). Un doppio separatore **malformato** (es. `1.2,3`) NON viene aggiustato:
   resta invalido → `INVALID_PRICE` (fail-closed, niente prezzo sbagliato nel CSV).
   Il separatore **scritto nel file** segue poi la config `csv_language` (#342: `IT`/`ES` =
   virgola «1,85», `EN` = punto — vedi `docs/xtrader_csv_contract.md`). I campi facoltativi, **se valorizzati**,
   sono validati anch'essi (il percorso hardcoded li lascia vuoti):
   - `MinPrice`/`MaxPrice` devono essere quote valide e **coerenti** — l'intervallo non può
     essere invertito (`MinPrice > MaxPrice`) né escludere la quota (`MinPrice > Price`,
     `MaxPrice < Price`); bordi inclusivi ammessi → altrimenti `INVALID_PRICE_BOUNDS`;
   - `Points` (moltiplicatore stake), se valorizzato, deve essere un numero **positivo**
     (`> 0`) → altrimenti `INVALID_POINTS`.
3. **Gate di contenuto**: un parser i cui obbligatori sono **tutti `fixed_value`**
   sarebbe "piazzabile" su qualsiasi testo (anche vuoto). Nel live, che bypassa il
   prefiltro marker per i parser custom attivi, questo scriverebbe lo stesso bet
   su ogni messaggio. Perciò una riga è accettata solo se **almeno una regola di
   estrazione che rappresenta contenuto di segnale** (non `fixed_value`) ha trovato un
   valore nel messaggio: una regola **obbligatoria** (`required`) **oppure** una regola su
   un **campo di riconoscimento rilevante per la modalità** (in `NAME_ONLY` i campi nome,
   in `ID_ONLY` i campi ID, in `BOTH` entrambi i set) — stato `NO_CONTENT_MATCH`
   altrimenti. Un'estrazione **opzionale** "larga" su un campo **non** di riconoscimento
   (es. una nota) non basta: non deve far passare un messaggio non-segnale che la attiva
   per caso (A10). Per usare un campo non di riconoscimento come "trigger" di contenuto,
   marcalo **obbligatorio**.
   - **Set di riconoscimento già FISSO-completo (#74).** Se i **soli valori fissi** completano
     già un set di riconoscimento per la modalità (es. `MarketId`+`SelectionId` fissi in
     `BOTH`, oppure il set nomi tutto fisso), la riga sarebbe piazzabile per **qualsiasi**
     messaggio: in quel caso un'estrazione **opzionale** — anche su un campo di riconoscimento
     — **non** basta come contenuto (eviterebbe altrimenti un bet spurio su un non-segnale).
     Serve un'estrazione **obbligatoria**. Quando invece il riconoscimento **non** è già
     completo coi soli fissi, l'estrazione di un campo di riconoscimento conta come prima
     (così i parser basati su **mappatura mercati**, che estraggono solo l'evento, restano validi).
4. **Approvazione chat**: un parser è usato solo per la chat **configurata**
   (`chat_id`) o per le chat con voce esplicita in `parser_by_chat`. Un
   `active_parser` globale **non** fa scommettere chat non approvate.
5. **Autoritativo, niente doppio parsing**: quando un parser custom è attivo per
   la chat, se non produce una riga piazzabile il segnale è **scartato** — non si
   ripiega sul parser hardcoded (che potrebbe interpretare diversamente lo stesso
   messaggio).
6. **Condizioni di gate** (PR-1, opzionali): se il parser definisce condizioni
   `contiene`/`NON contiene` (con modo `E`/`O`), il messaggio viene processato **solo se**
   le soddisfa; altrimenti è **scartato** (`NO_CONTENT_MATCH`, nessuna riga). Vedi §3ter.

---

## 3ter. Condizioni di gate (PR-1) — «il parser scatta solo se…»

Un Parser Personalizzato può opzionalmente dichiarare una lista di **condizioni** sul testo
del messaggio: il parser **scatta soltanto se il messaggio le soddisfa**, altrimenti il
messaggio è **scartato** (`NO_CONTENT_MATCH`, nessuna riga CSV). È un **filtro fail-closed**
valutato **prima** di ogni estrazione (in cima a `custom_parser_engine.matches_message`), utile
per far agire un parser **solo sui messaggi pertinenti** — es. «un mercato/lato diverso a
seconda dello scenario nel messaggio».

Modello (`custom_parser.py`):

- `conditions: list[Condition]` — ogni `Condition` ha `text` (il testo da cercare) e `negate`
  (bool: `False` = *deve contenere*, `True` = *NON deve contenere*);
- `conditions_mode: str` — `"all"` (default, **E**: tutte devono valere) o `"any"` (**O**:
  ne basta una). Un valore ignoto/manomesso ricade su `"all"` (fail-closed, più restrittivo).

Regole di valutazione (`conditions_pass`):

- il confronto è **case-insensitive e tollerante agli spazi** (stessa normalizzazione di
  `dizionario.normalize`: minuscole + spazi collassati);
- il match è **per sottostringa**, **non** per parola intera (nota Fugu #390): un testo **breve**
  come `BACK` scatta anche dentro parole più lunghe (`BACKGROUND`, `OUTBACK`) e `1` scatterebbe in
  ogni `10`/`21`. Usa testi **distintivi** (es. `@punta`, `⚽ 0 - 1`, `OVER SUCCESSIVO`) per evitare
  match indesiderati;
- una condizione a **testo vuoto** è **ignorata** (`active_conditions()` la filtra) — non fa né
  matchare né scartare nulla;
- **nessuna condizione** (lista vuota o tutte vuote) = **nessun filtro**: comportamento identico
  a prima della feature (retro-compatibile: i file salvati senza chiavi `conditions`/
  `conditions_mode` caricano con default vuoti).

Retro-compatibilità: `to_dict`/`from_dict` serializzano le due chiavi nuove; un parser salvato
prima della feature si carica con `conditions=[]` e `conditions_mode="all"`.

**GUI (scheda 🧩 Parser):** sotto la sezione «Output multi-riga» c'è il riquadro **«Condizioni
di gate»** — tendina modo **TUTTE (E)** / **una qualsiasi (O)**, pulsante **«➕ Aggiungi
condizione»**, e una riga per condizione (**tendina contiene/NON contiene** + **testo** +
**🗑 Rimuovi**). Le righe a testo vuoto sono **scartate al salvataggio** (non generano errori di
validazione). Vedi `docs/design/design_handoff.md` §7.1.

---

## 3bis-A. Tester multiplo «Prova più messaggi» (#311 §3.2)

Accanto a «🧪 Prova messaggio» c'è **«🧪🧪 Prova più messaggi (separati da ---)»**: incolla
nel box N **messaggi reali** del canale separandoli con una riga che contiene **solo `---`**
(separatore ESPLICITO: nessuna euristica sui confini — i messaggi Telegram sono multi-linea).
Per OGNI messaggio ottieni: **valido/scartato** (✅/⛔), il **motivo esatto** (lo STESSO
verdetto sintetico del singolo «Prova messaggio»: status + campi mancanti — stessa pipeline
read-only, `ParserBuilder.batch_report`), e l'**anteprima delle righe CSV** generate (con i
decimali nel formato `csv_language`, come il singolo). In cima il riepilogo «Messaggi validi:
X/N». Fail-safe: massimo **50 messaggi** per prova (gli extra sono segnalati, mai valutati in
silenzio); blocchi vuoti scartati; **nessuna scrittura** del CSV operativo (solo anteprima).

## 3bis. Diagnostica «Prova messaggio» (perché "Non pronto")

Nel builder, **«Prova messaggio»** non dà più solo il verdetto: mostra una
**diagnostica per ogni colonna** lungo la catena
`estrazione → trasformazione → value-map → validazione`, così si capisce *quale*
campo ha fallito e *perché*. Il pulsante **«📋 Copia diagnostica»** copia il report
negli appunti (utile per condividerlo).

Per ogni colonna il report mostra il valore `grezzo` estratto, `→tr` (dopo
trasformazione) e `→map` (dopo value-map), più un codice di stato:

| Codice | Significato |
|---|---|
| `OK` / `EMPTY_OPTIONAL` | valore valido / vuoto ma facoltativo (non blocca) |
| `START_NOT_FOUND` | il delimitatore «Inizia dopo» non è nel messaggio |
| `END_NOT_FOUND` | «Finisce prima» non trovato dopo l'inizio |
| `REQUIRED_EMPTY` | campo obbligatorio rimasto vuoto |
| `TRANSFORM_FAILED` | la trasformazione non ha prodotto un valore |
| `VALUE_MAP_MISS` | la value-map non ha trovato il valore (→ vuoto) |
| `INVALID_PRICE` | `Price` non numerico o ≤ 1.0 |
| `INVALID_BETTYPE` | `BetType` non è un lato valido (`PUNTA`/`BANCA`/`BACK`/`LAY`) |
| `INVALID_POINTS` | `Points` valorizzato ma non un numero positivo (`> 0`) |
| `INVALID_PRICE_BOUNDS` | limiti incoerenti: `Min > Max`, o l'intervallo esclude `Price` (segnalato solo sul limite che offende) |
| `MODE_REQUIRED_MISSING` | campo richiesto dalla Modalità di riconoscimento mancante |
| `NO_CONTENT_MATCH` (messaggio) | nessuna estrazione ha trovato nulla: solo valori fissi / nessun match |

Il verdetto della diagnostica **coincide** con ciò che il bridge scriverebbe a
runtime (stessa pipeline `build_validated_row`): se "Prova messaggio" dice pronto,
il live scrive; se dice "Non pronto", il live scarta — col motivo per colonna.

La diagnostica per-colonna segnala **tutte** le colonne invalide di un messaggio, non
solo la prima (es. `BetType` sbagliato **e** `Price` non numerico vengono mostrati
entrambi); e per un campo richiesto dalla **Modalità** ma con estrazione fallita
mantiene il motivo azionabile (es. `START_NOT_FOUND` per un delimitatore non trovato)
invece del generico `MODE_REQUIRED_MISSING`.

Il **verdetto sintetico** in cima segue questa precedenza:
- **⛔ Non salvabile**: il parser ha errori **strutturali** (gli stessi che bloccano
  «Salva», es. una regola con `fixed_value` **e** delimitatori insieme). In questo caso
  non viene mai mostrato «Pronto», anche se la pipeline per caso produce una riga — una
  definizione non salvabile non è «pronta».
- **Output multi-riga attivo** (MultiMarket/MultiSelection): il verdetto si basa sulle
  **righe generate**, non sulla sola base, e ha un formato diverso (es. «✅ Pronto · N righe
  generate, tutte piazzabili.», «⚠ X/N righe piazzabili …» o «⛔ Nessuna delle N righe è
  piazzabile …») — il dettaglio per-riga è nella tabella anteprima qui sotto.
- **⛔ Non pronto (`STATO`)**: superata la struttura (single-row), la riga è scartata dalla pipeline.
  Oltre allo stato, il verdetto **elenca i campi mancanti** — sia gli obbligatori del parser
  sia i campi di **riconoscimento** richiesti dalla Modalità (`INVALID_MISSING_FIELDS`), così
  si sa quale colonna aggiungere.
- **✅ Pronto**: la riga è piazzabile (col riepilogo dei campi valorizzati).

---

## 4. Quale parser è attivo (routing)

La risoluzione avviene in **due passi** — prima l'**approvazione** della chat, poi la
**scelta** del parser (`signal_router._chat_approved_for_custom` +
`parser_manager.resolve_parser_name`):

**A. La chat è approvata per il parsing?** Sì se è:
- la chat configurata (`chat_id`), **oppure**
- una chat con voce esplicita in `parser_by_chat`, **oppure**
- una **sorgente `source_chats` ATTIVA**.

Una sorgente **disattivata** è deny-list: **mai** approvata, nemmeno con un override. Una
chat **non** approvata → messaggio **ignorato** (`IGNORE_NOT_RELEVANT`).

**B. Quale/i parser usa una chat approvata?** (PR-2 — router multi-parser)
1. se la chat ha una **lista** in `parser_list_by_chat` → **quei parser, in ordine** (multi-parser);
2. altrimenti se ha un singolo override in `parser_by_chat` → quel parser (override per-chat);
3. altrimenti → l'**`active_parser` globale**. ⚠️ Questo vale **anche per una sorgente
   `source_chats` attiva senza override**: eredita il parser globale ed è **processata** (può
   scrivere il CSV) — **non** è inerte. Perciò, con un `active_parser` globale impostato,
   **tutte** le sorgenti attive senza override lo usano;
4. se non c'è né lista, né override per-chat, né `active_parser` globale → **nessun parser**: nel
   live il messaggio è **ignorato** (`NO_PARSER`, CP-09b); il parser hardcoded **non** entra in
   gioco (resta solo per compatibilità/test).

La fonte unica è `parser_manager.resolve_parser_names(cfg, chat)` (lista ordinata, precedenza
lista → singolo → globale); `resolve_parser_name` (singolo) ne ritorna il primo, per i chiamanti
legacy.

**Multi-parser per chat (PR-2).** Una chat può avere **più parser** valutati **in ordine di
priorità**: il messaggio è passato a **ciascuno** e **scattano TUTTI quelli le cui condizioni di
gate/estrazione combaciano** (non solo il primo). Le righe dei parser che scattano sono **unite in
ordine** e **deduplicate per-riga**: due parser che producono la **stessa** riga CSV = **una sola**
scommessa (nessuna doppia scommessa accidentale); righe **diverse** = bet diversi voluti. Se
**nessun** parser scatta → `NO_CONTENT_MATCH`, nessuna riga. Il gate (`matches_message`, incl. le
**condizioni** §3ter) è valutato **per parser**, sul messaggio intero: così ogni parser agisce solo
sui messaggi pertinenti. Con **un solo** parser il comportamento è **identico** a prima
(retro-compatibile). Si configura dall'editor **«📡 Chat sorgenti»** (colonna Parser → editor a
lista ordinata). Combinato con le **condizioni di gate** (§3ter), è la soluzione a «un mercato/lato
diverso per messaggio sulla stessa chat».

Nel live, il chat id usato è quello **reale del messaggio** (così l'override
per-chat funziona anche con setup multi-chat dove `chat_id` singolo non è
impostato). Se né `chat_id`, né `parser_by_chat`, né `parser_list_by_chat`, né alcuna
`source_chats` sono configurati, vale il comportamento legacy (tutte le chat ammesse —
responsabilità dell'utente).

---

## 5. Persistenza, import/export

- I parser sono salvati **per-parser** in una **cartella utente persistente**:
  `custom_parser.default_parsers_dir()` → `<config_dir>/parsers/<nome>.json`,
  cioè `config_store.config_dir()/parsers`. Su Windows è
  `%APPDATA%\XTraderBridge\parsers`; in dev/Linux/macOS è
  `~/.config/XTraderBridge/parsers` (o `$XDG_CONFIG_HOME/XTraderBridge/parsers`).
  È questa la cartella da editare/backuppare per l'app reale (i test passano
  invece una `dir_path` temporanea esplicita). La scelta della cartella utente
  fa sopravvivere i parser a reinstallazioni/spostamenti dell'EXE.
- Nota: `.gitignore` esclude anche `data/parsers/` (voce difensiva, sono
  configurazione utente e non si committano), ma **non** è il percorso usato a
  runtime: quello di default è `<config_dir>/parsers/` qui sopra.
- Scrittura **atomica** e rifiuto di nomi che collidono o non fanno round-trip col
  filename (anti path-traversal).
- `parser_io.export_parser` / `import_parser` per condividere i file (valida prima
  di scrivere/salvare; import non sovrascrive senza `overwrite=True`).
- `parser_io.example_parser()` + `fixture_message()`: un parser realistico
  (Match/Esito/Quota/Lato) che produce una riga piazzabile end-to-end, usato anche
  nei test.
- **Gestione dalla finestra builder (CP-11):** la tendina "Parser salvati" elenca i
  parser nella cartella utente, con **🆕 Nuovo / 📂 Carica / 📑 Duplica / 🗑 Elimina**.
  La duplica chiede un nuovo nome e **rifiuta** un nome già esistente (non
  sovrascrive); l'eliminazione rimuove il file per nome (anti path-traversal). Un
  file corrotto compare in lista col nome del file, senza nascondere gli altri.
  L'**attivazione** resta nella finestra "📡 Chat sorgenti" (parser globale o
  per-chat); la finestra builder serve a creare/modificare/gestire le definizioni.
- **Adattamento allo schermo:** la finestra builder è interamente **scrollabile**
  (un solo contenitore: griglia 14 colonne, area "Prova messaggio" e tabella
  diagnostica restano raggiungibili anche su schermi piccoli). Come tutte le finestre
  del bridge, si apre con altezza **clampata all'area schermo** e un `minsize`, tramite
  l'helper condiviso `gui_utils.fit_to_screen(...)`, così non sfora sotto la taskbar.

---

## 5-bis. Output multi-riga: MultiMarket / MultiSelection (#192)

Un singolo messaggio Telegram può generare **più righe CSV**. Le **14 righe del parser**
restano la **riga base** (campi comuni: Provider, EventName, eventuali Market/Selection di
default, Price, BetType…); due opzioni del modello la espandono in più righe:

- **MultiMarket** (`multi_market_enabled` + `multi_markets`): più **mercati diversi** della
  stessa partita (es. `FIRST_HALF_GOALS_05 / Over 0,5` **e** `OVER_UNDER_15 / Over 1,5`).
- **MultiSelection** (`multi_selection_enabled` + `multi_selections`): più **selezioni dello
  stesso mercato** (es. `CORRECT_SCORE` con `1 - 0`, `2 - 1`, `1 - 2`).

**Modello** (`custom_parser.MultiRowRule`): ogni riga multi porta
`start_after, end_before, market_type, market_name, selection_name, price, min_price,
max_price, bet_type, points, handicap, enabled`. Ogni campo **non vuoto SOVRASCRIVE** quello
della riga base; un campo **vuoto eredita** dalla base. Tutto è serializzato nel JSON del
parser ed è **retro-compatibile**: i file salvati prima di #192 (senza questi campi) caricano
con flag `False` e liste vuote → comportamento **single-row identico a prima**.

**Pipeline** (`custom_pipeline.build_validated_rows`): ritorna una **lista** di righe validate
(una per mercato/selezione attiva). Ogni riga è validata singolarmente: una riga non valida
**non blocca** le altre (l'instradamento scrive solo quelle piazzabili). `signal_router.
resolve_row` espone le righe in `RouteResult.rows` (e `RouteResult.row` resta la **prima**,
retro-compatibile).

- **Base bloccata ma completata dalle righe multi (#192 kyZ):** un campo della **riga base** che è
  però fornito da **ogni** riga multi (es. `SelectionName` obbligatorio in `NAME_ONLY`, valorizzato
  da ogni MultiSelection) **non** blocca più la generazione. Con l'output multi attivo, se la base
  è bloccata per un motivo **colmabile** — `NOT_READY` (obbligatorio della regola) o
  `MARKET_MAPPING_MISSING` (mercato incompleto, nessuna frase combacia) — viene ri-valutata
  trattando come presenti **solo** le colonne fornite da ogni riga multi; passa comunque per
  mappatura nomi/mercati ed enrichment ID e ogni riga derivata è validata singolarmente.
  **Fail-closed** restano: un obbligatorio **non** coperto dal multi (resta `NOT_READY`, così un
  messaggio dichiarato incompleto non raggiunge il CSV), un mercato non coperto, e gli altri gate
  (`Provider` mancante, `Handicap` non numerico, mappatura nomi non risolta).
  - *ID per riga (risolto):* in `ID_ONLY` con dizionario locale gli ID sono ora risolti **per
    singola riga derivata** (`_resolve_ids_into` in `_validated_multi_row`) — una MultiSelection
    azzera `SelectionId` al cambio selezione e subito dopo ri-risolve gli ID per quella selezione,
    così l'ID_ONLY produce righe con gli ID corretti. Vedi «ID coerenti + risoluzione per riga».

**Regole e limiti (v1):**

- `BetType` resta `PUNTA`/`BANCA` (contratto XTrader): una riga multi con un valore diverso
  (es. `BACK`) risulta **non valida** in validazione — il contratto CSV non cambia.
- **Estrazione per-riga DINAMICA (#325):** una regola **MultiSelection** può estrarre dal
  messaggio la **lista di risultati esatti** e generare **una riga CSV per ciascuno** — invece di
  un `selection_name` fisso. Si attiva quando la regola ha `selection_name` **vuoto** **e**
  `start_after`/`end_before` valorizzati («Inizia dopo / Finisce prima»): dalla regione fra i
  delimitatori si estraggono i punteggi (separatore interno **solo `-`**, con **spazi orizzontali**
  attorno al trattino; es. «1-0», «1 - 0»), **normalizzati** al formato del dizionario («01 - 0» →
  «1 - 0») e **deduplicati** nell'ordine del messaggio. Il separatore *fra* i risultati
  (virgola/spazio/newline/slash…) **non conta** (i punteggi si riconoscono per forma). Difese
  anti-abuso (input non attendibile): il «:» **non** è riconosciuto come separatore di punteggio
  (evita di scambiare orari come «20:45» per risultati); un punteggio deve stare su **una sola riga**
  — cifre di righe adiacenti («3⏎- 0») **non** si fondono in un risultato spurio; ogni lato è **1–2
  cifre** con confini di cifra (niente maglie/ID come «100-1»); un **decimale** (handicap/quota,
  col punto **o** la virgola italiana: «0-0,5», «0,5-1», «1-0.25») **non** produce un punteggio spurio
  «0 - 0»/«5 - 1»; numero di risultati per messaggio **limitato** (cap difensivo, ~50). *Separatore
  fra i risultati:* usare **«, » (virgola + spazio)**, spazio o newline; una virgola **senza spazio**
  fra cifre («1-0,2-1») è ambigua con un decimale → **fail-closed** (non estratta).
  L'estrazione dinamica si attiva **solo** sui mercati-punteggio **canonici** **Correct Score
  full-time** (`CORRECT_SCORE`) e **primo tempo** (`HALF_TIME_SCORE`) — gli unici che elencano
  risultati «N - N»; il confronto è **esatto** (un `MarketType` non canonico, es. «correct_score»
  minuscolo da JSON legacy, **non** attiva l'estrazione, così le righe dinamiche emettono solo
  mercati che XTrader/Betfair riconoscono). Su qualunque **altro** mercato una regola con
  `selection_name` vuoto + delimitatori resta una **riga fissa** (eredita la selezione della base),
  così un JSON legacy con quei campi residui non moltiplica le scommesse. Il mercato lo dà la base,
  la selezione arriva dall'estrazione.
  Ogni riga è
  **validata singolarmente** (fail-closed per-riga, come #192) con **azzeramento + ri-risoluzione
  ID** per la selezione; un token non-punteggio non genera una riga; lista vuota → nessuna riga.
  Una regola con `selection_name` **fisso** resta invariata (override diretto, percorso #192).
  **Configurazione in GUI (#325 slice 2):** ogni riga **MultiSelection** ha i campi **«Inizia
  dopo» / «Finisce prima»** in coda alla riga (dopo Handicap): lasciare **«Selezione» vuota** e
  compilare i delimitatori attiva l'estrazione dinamica (un hint 💡 sotto la lista lo ricorda).
  I campi **non** sono esposti sulle righe **MultiMarket** (lì sarebbero solo una
  misconfigurazione: il runtime li ignora per design) dove restano preservati come campi nascosti.
  I delimitatori **non** vengono strippati al salvataggio (come nella griglia base): un
  delimitatore whitespace (es. fine riga) è legittimo.
  **Nota modalità e sicurezza (importante).** I risultati esatti Betfair sono selezioni
  **per-partita** (dipendono dalle squadre) e tipicamente **NON** sono nel dizionario locale (una
  popolazione «diretta» conserva la riga àncora del mercato `CORRECT_SCORE`/`HALF_TIME_SCORE` ma
  **nessuna** SelectionName per-partita). Di conseguenza un
  `SelectionId` per «1 - 0» **non è risolvibile** dal dizionario: in **`ID_ONLY`/`BOTH`** ogni
  punteggio estratto resterebbe **senza ID → scartato** (la feature non produrrebbe righe). Perciò
  l'estrazione dinamica dei punteggi **piazza a NOME** ed è di fatto una funzione di **`NAME_ONLY`**
  (contratto #192: piazzamento a nome, senza validazione ID) — **non** esiste una validazione a
  dizionario possibile per i risultati esatti. La sicurezza contro un punteggio **ben formato ma
  inesistente** («12 - 30») **non** è quindi un gate a dizionario (impossibile), ma la combinazione:
  **form-validation robusta** (niente orari con «:», niente decimali punto/virgola, niente fusione
  multi-riga, confini di cifra anti-maglie/ID), **regione delimitata dall'utente** (`start_after`/
  `end_before` puntati sull'elenco risultati, non su tutto il messaggio), **filtro `chat_id`** (solo
  canali configurati), **cap difensivo ~50**, dedup, e **XTrader a valle non abbina** una selezione
  inesistente «12 - 30». Un eventuale **cap di plausibilità** sul valore dei punteggi (per scartare
  «12-30»/«45-67») è un follow-up valutabile nella slice 2 GUI, dove vive la scelta modalità/UX di
  sicurezza; non è imposto qui perché rischierebbe di sopprimere risultati alti legittimi rari.
- **MultiMarket + MultiSelection insieme** generano righe **separate** (prima i mercati, poi
  le selezioni sul mercato base), **mai** il prodotto cartesiano (`custom_pipeline.
  both_multi_active` segnala il caso, da avvisare in GUI).
- **Deduplica per-riga** (`signal_dedupe.row_dedup_key`): la chiave combina l'hash del
  messaggio con `Provider+EventName+MarketType+SelectionName+BetType`, così righe diverse
  dello **stesso** messaggio non si auto-dedupano, ma una riga **identica** reinviata resta un
  duplicato.
- **Coda/CSV**: `write_path.commit_signals` valuta ogni riga (dedup per-riga + limiti), accoda
  le righe `WRITE` e riscrive il CSV in modo **atomico** (rollback completo se la scrittura
  fallisce). Garanzie allineate al single-row: in **DRY_RUN** non scrive nulla; se **tutte** le
  righe sono soppresse (duplicati/limiti) il CSV **non viene riscritto** (XTrader non riconsuma
  righe identiche); una riga `DAILY_LIMITED` o oltre il tetto `max_active` **non** è scritta e il
  suo consumo dedup/daily è **annullato** (ritentabile).
  - In `APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED` configurare **`max_active` ≥ numero di righe** del
    messaggio (le righe oltre il tetto sono bloccate, non scritte).
  - In `OVERWRITE_LAST` l'«ultima istruzione» è il **blocco intero** del messaggio: tutte le
    righe generate restano attive insieme (sostituiscono il blocco precedente), via
    `signal_queue.replace_block`.
- **ID coerenti + risoluzione per riga**: quando una riga multi cambia `MarketType`/`MarketName`/
  `SelectionName`/`Handicap`, gli eventuali `MarketId`/`SelectionId` ereditati dalla base vengono
  **azzerati** (una riga non può nominare un mercato e identificarne un altro per ID); subito dopo,
  se è disponibile il dizionario locale (`id_resolver` + sport del parser), gli ID vengono
  **ri-risolti per la selezione/mercato di QUELLA riga** (`_resolve_ids_into`, additivo/fail-open/
  non distruttivo). Così un **MultiSelection in `ID_ONLY`** produce righe con gli ID corretti per
  ciascuna selezione; senza dizionario (o parser agnostico) le righe restano a **nomi** — in
  `NAME_ONLY` piazzabili, in `ID_ONLY` scartate (fail-closed, nessun ID inventato).

**GUI (scheda 🧩 Parser di «🧰 Strumenti»):** la sezione **«Output multi-riga»** sopra la griglia
14 colonne offre due interruttori indipendenti — **MultiMarket** e **MultiSelection** — ciascuno
con un pulsante **`➕ Aggiungi`** che inserisce una **riga dinamica** editabile (Tipo mercato,
Mercato, Selezione, Quota, BetType, Handicap — e, **solo sulle righe MultiSelection**, anche
**«Inizia dopo» / «Finisce prima»** per l'estrazione dinamica dei risultati esatti, #325) con
casella **Attiva** e pulsante **`🗑 Rimuovi`**. Sotto la lista selezioni un **hint 💡** ricorda la
combinazione che attiva l'estrazione (Selezione vuota + delimitatori, solo
`CORRECT_SCORE`/`HALF_TIME_SCORE`).
Un **banner ⚠** avvisa quando entrambi gli interruttori sono attivi (righe **separate**, non
cartesiane) o quando un interruttore è acceso senza righe abilitate. Dagli avvisi **per-riga**
(follow-up #325/#341) il banner segnala anche le configurazioni ambigue delle righe SELEZIONE
attive coi delimitatori: **Selezione fissa + delimitatori** → «i delimitatori verranno IGNORATI»
(con Selezione impostata il runtime usa il valore fisso); **Selezione vuota + delimitatori ma
mercato effettivo NON-punteggio** → «estrazione dinamica INATTIVA … la riga resta FISSA ed
eredita la Selezione della riga base» (è il gate #341). L'avviso sul mercato è emesso **solo
quando il mercato effettivo è determinabile staticamente** (override `Tipo mercato` della riga,
oppure MarketType base a **valore fisso** senza transform/value-map e senza mappatura mercati a
frase): se il mercato è noto solo a runtime il banner **tace** (mai falsi allarmi). La detection
specchia `custom_pipeline._is_dynamic_selection` (stesso set di mercati-punteggio, importato —
non copiato). Il banner si aggiorna su aggiungi/rimuovi/toggle, quando si lascia un campo della
riga (`<FocusOut>`), sulla casella **Attiva** e a ogni **«Prova messaggio»**. **«Prova messaggio»** mostra
una **tabella «Anteprima righe generate»** con **una riga per ogni riga CSV** che il messaggio
produrrebbe (Base / Mercato / Selezione), col **verdetto per-riga** (✅ piazzabile · ⛔ + motivo):
usa lo **stesso motore del runtime** (`build_validated_rows`). Quando l'output
multi-riga è attivo, anche il **verdetto sintetico** in cima si basa sulle **righe generate** (es.
«✅ Pronto · N righe generate, tutte piazzabili»), non sulla sola riga base — che in un parser
MultiMarket può mancare di MarketType/SelectionName **di proposito** (li fornisce ogni riga
mercato), e altrimenti farebbe apparire un falso «Non pronto».

> **Decimali nell'anteprima = formato del file (#342, follow-up #344).** Il riepilogo
> «Colonna=valore» delle righe anteprima e del verdetto «✅ Pronto · …» mostra le colonne
> **decimali** (`Price`, `MinPrice`, `MaxPrice`, `Points`, `Handicap`) **nel formato della
> `csv_language` corrente** — virgola per `IT`/`ES` («Price=1,50»), punto per `EN` — cioè
> **come usciranno davvero nel CSV**, tramite lo **stesso** localizzatore del write-path
> (`csv_writer.localize_row`): anteprima e file non possono divergere. È solo la **vista**:
> il dato interno resta canonico col punto (validatori/dedup invariati) e le colonne
> testuali («Over 2.5 Goals») non sono mai toccate.

> **Nota sull'arricchimento ID in anteprima (#192, Codex).** L'anteprima usa lo stesso motore del
> runtime e, quando il dizionario locale è popolato, **risolve gli ID dal dizionario**: la
> GUI inoltra a `test_message`, `diagnose` e `preview_rows` un `id_resolver` opzionale, ottenuto
> best-effort dall'app (factory `id_resolver_factory` → `App._betfair_id_resolver`). Così un parser
> **multi-riga** `ID_ONLY` che si affida al dizionario per `MarketId`/`SelectionId` (lasciati vuoti)
> mostra nella **tabella anteprima** le righe risolte come verrebbero scritte a runtime. Se il
> resolver **non** è disponibile (factory assente o che solleva → `None`), l'anteprima resta
> **conservativa e fail-closed** (mostra «non pronto» invece di un falso «pronto»): fail-open sul lato
> comodità, mai sul lato sicurezza. La risoluzione in anteprima è puramente di lettura e non ha alcun
> effetto sul flusso reale.
>
> **Limite single-row (#192, Codex).** L'arricchimento ID dal dizionario è una funzione **multi-riga**
> (`build_validated_rows` rilassa il gate degli ID obbligatori PER RIGA solo quando è attivo
> MultiMarket/MultiSelection). Un parser `ID_ONLY` **a riga singola** che lascia `MarketId`/
> `SelectionId` obbligatori **vuoti** aspettandosi che li riempia il dizionario resta «Non pronto» in
> anteprima — **coerentemente col runtime**, che per lo stesso parser ritorna `NOT_READY` e non
> piazza nulla (nessun rilassamento del gate nel path single-row). Per un segnale a riga singola in
> `ID_ONLY`, fornisci gli ID dal messaggio (regole `MarketId`/`SelectionId`), oppure usa il path
> multi-riga. Il verdetto conservativo qui **non** è un buco di sicurezza (sotto-promette).
>
> **Tabella diagnostica base-level (#192, Codex).** Per un parser multi-riga la tabella «Diagnostica
> per colonna» riflette la **riga base** (`diagnose` gira su `build_validated_row`): i campi che le
> righe generate riempiono (es. `SelectionName` in un MultiSelection, o gli ID risolti PER RIGA dal
> dizionario) possono comparire come «MANCANTE/REQUIRED_EMPTY» sulla base pur essendo risolti sulle
> righe. La fonte **autorevole** per l'esito delle righe generate è la **tabella anteprima multi-riga**
> (verde/rosso per riga); la tabella per-campo è un aiuto di diagnosi a livello base. È una discrepanza
> in direzione conservativa (mostra più «mancanti» del reale), non un falso «pronto».
>
> **Anteprima = live (rimozione «Betfair Sync»).** Con la funzione rimossa l'arricchimento ID è
> staccato in **entrambi** i punti: il **CSV live** (`_process` → `id_resolver=None`) e
> l'**anteprima** (`App._preview_id_resolver_factory` → `None`). Così l'anteprima resta
> **conservativa** e non mostra `✅ Pronto` su una riga che il live scarterebbe (`ID_ONLY` senza
> ID risolti → fail-closed): invariante «anteprima = runtime». `App._betfair_id_resolver` resta il
> **seam** (resolver sul dizionario locale) da ricablare in entrambi i punti quando il dizionario
> custom sarà popolato.
>
> **Gate di contenuto nel verdetto multi (#192, Codex).** Il verdetto sintetico «Prova messaggio»
> onora `NO_CONTENT_MATCH` **anche** per l'output multi-riga: un parser a soli valori fissi (che non
> estrae nulla dal messaggio) NON risulta «✅ Pronto · N righe» pur generando righe piazzabili, perché
> il runtime lo scarterebbe (`matches_message`). Coerente col verdetto single-row.

I campi per-riga **non esposti** nella griglia GUI (`min_price`, `max_price`, `points`,
`start_after`, `end_before` di `MultiRowRule`) sono **preservati** quando si modifica e salva un
parser caricato: la GUI applica solo gli override visibili senza azzerare i vincoli nascosti.

La logica che la GUI usa (round-trip dei campi multi in `to_def()`, gestione righe, avvisi,
anteprima `ParserBuilder.preview_rows`) vive nel **controller** ed è coperta in CI da
`tests/unit/test_parser_builder_multirow.py`; i widget (`custom_parser_gui.py`) restano una
**vista sottile**, verificabile solo manualmente su Windows (display richiesto). Il motore è
coperto da `tests/unit/test_multirow_192.py`.

**Collaudo manuale GUI (Windows):** apri «🧰 Strumenti» → scheda 🧩 Parser; spunta MultiMarket,
premi `➕ Aggiungi mercato` due volte e compila due mercati; incolla un messaggio reale e premi
«Prova messaggio»; verifica che la tabella mostri **2 righe Mercato** entrambe ✅. Spunta anche
MultiSelection, aggiungi 3 selezioni → la tabella deve mostrare **5 righe** (2 Mercato + 3
Selezione), col banner ⚠ «righe SEPARATE». Salva, riapri il parser e verifica che interruttori
e righe siano ripristinati.

## 6. Riferimenti (codice e test)

| Componente | Modulo | Test |
|---|---|---|
| Modello dati + persistenza | `custom_parser.py` | `tests/unit/test_custom_parser_model.py` |
| Motore di estrazione (delimitatori tolleranti) | `custom_parser_engine.py` | `tests/unit/test_custom_parser_engine.py` |
| Value-map (bettype + dizionario) | `value_maps.py` | `tests/unit/test_value_maps.py` |
| Mappatura nomi squadra (profili) | `name_mapping_store.py` | `tests/unit/test_name_mapping.py` |
| GUI Mapping nomi — area ⚽ Calcio (+ 🎯 Mercati predisposta) | `name_mapping_gui.py` (`MappingPanel`, `NameMappingPanel`) | verifica manuale (GUI) |
| Trasformazioni | `transforms.py` | `tests/unit/test_transforms.py` |
| Riga validata col contratto | `custom_pipeline.py` | `tests/unit/test_custom_pipeline.py` |
| Diagnostica «Prova messaggio» (per-campo) | `parser_diagnostics.py` | `tests/unit/test_parser_diagnostics.py` |
| Builder GUI (controller + vista) — scheda 🧩 Parser di "🧰 Strumenti" | `parser_builder.py`, `custom_parser_gui.py` (`CustomParserPanel`) | `tests/unit/test_parser_builder.py` |
| Output multi-riga GUI (controller: round-trip, righe, anteprima `preview_rows`) | `parser_builder.py` (`PreviewRow`, `preview_rows`, `multi_warnings`), `custom_parser_gui.py` (sezione «Output multi-riga» + tabella anteprima) | `tests/unit/test_parser_builder_multirow.py` (+ vista: verifica manuale GUI) |
| Adattamento finestre allo schermo (clamp altezza + minsize) | `gui_utils.py` | `tests/smoke/test_imports.py` |
| Finestra hub "🧰 Strumenti" a schede (consolidazione GUI) | `tools_gui.py` | `tests/smoke/test_imports.py` |
| Parser attivo / override per chat | `parser_manager.py` | `tests/unit/test_parser_manager.py` |
| Import/export + esempio | `parser_io.py` | `tests/unit/test_parser_io.py` |
| Instradamento live + gate | `signal_router.py` | `tests/unit/test_signal_router.py` |
| **Catena end-to-end** | — | `tests/integration/test_custom_parser_end_to_end.py` |

> Note di verifica: la **GUI** del builder e il **flusso live** Telegram→CSV vanno
> provati a mano su Windows (non testabili in ambiente headless). Tutta la logica
> di parsing/validazione/instradamento è invece coperta da test automatici. Il
> merge di ogni PR resta **manuale** del proprietario.
