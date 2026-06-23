# Parser Personalizzato — guida (CUSTOM_PARSER_READY)

> Stato: **pronto** (PHASE 3-bis, CP-01…CP-10). Il Parser Personalizzato permette
> di definire dalla GUI *come* estrarre ogni colonna del contratto CSV XTrader da
> un messaggio Telegram, **senza modificare il codice**. Quando è attivo per una
> chat è **autoritativo**; il parser hardcoded storico resta come fallback quando
> nessun parser personalizzato è attivo.

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
| `required` | obbligatorio: se il valore finale è vuoto il parser è **"Non pronto"** → nessuna riga CSV |

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
  conflitto vince la **prima** corrispondenza (deterministico).

**Sicuro (fail-closed)**: se il separatore non si trova **o** una squadra non è nei
profili, lo stato è `MAPPING_MISSING` → **nessuna riga CSV** (un evento sbagliato =
scommessa sbagliata). Nessun nome squadra viene mai tradotto "a caso". Un parser
**senza profili** non applica alcuna mappatura (`EventName` invariato,
retro-compatibile).

**GUI**: i profili si gestiscono nel **Dizionario nomi squadra** (pulsante «🗺️
Dizionario nomi» nella finestra principale, `name_mapping_gui.NameMappingWindow`):
una **finestra separata** con il selettore profilo (nuovo/rinomina/elimina) e la
tabella `Country | Betfair/XTrader | Provider`. Nel **Parser Personalizzato** scegli
il **separatore** squadre e spunti i **profili** da usare (checkbox multi-selezione);
«Prova messaggio» risolve i profili dalla config e mostra l'`EventName` tradotto (o
`MAPPING_MISSING` se non mappabile), coerente col runtime.

---

## 2bis. Modalità di riconoscimento e griglia a 14 colonne

Il builder mostra **tutte e 14 le colonne del contratto già pronte, in ordine fisso**
(una riga per colonna): compili quelle che ti servono e lasci vuote le altre — non si
aggiungono/scelgono colonne a mano, così l'ordine è sempre corretto e non se ne dimentica
nessuna.

La **Modalità** di riconoscimento (`ID_ONLY` / `NAME_ONLY` / `BOTH`) è una proprietà
**del parser** (salvata nel file, campo `mode`; default `NAME_ONLY`). Selezionandola dal
menu, le colonne richieste da quel set diventano **obbligatorie in automatico** (auto
«Obblig.»), senza spuntarle a mano:

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
   `BetType ∈ {PUNTA, BANCA}`, e i campi richiesti dalla modalità di
   riconoscimento (`ID_ONLY`/`NAME_ONLY`/`BOTH`) devono esserci.
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
4. **Approvazione chat**: un parser è usato solo per la chat **configurata**
   (`chat_id`) o per le chat con voce esplicita in `parser_by_chat`. Un
   `active_parser` globale **non** fa scommettere chat non approvate.
5. **Autoritativo, niente doppio parsing**: quando un parser custom è attivo per
   la chat, se non produce una riga piazzabile il segnale è **scartato** — non si
   ripiega sul parser hardcoded (che potrebbe interpretare diversamente lo stesso
   messaggio).

---

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
| `INVALID_BETTYPE` | `BetType` non è `PUNTA`/`BANCA` |
| `MODE_REQUIRED_MISSING` | campo richiesto dalla Modalità di riconoscimento mancante |
| `NO_CONTENT_MATCH` (messaggio) | nessuna estrazione ha trovato nulla: solo valori fissi / nessun match |

Il verdetto della diagnostica **coincide** con ciò che il bridge scriverebbe a
runtime (stessa pipeline `build_validated_row`): se "Prova messaggio" dice pronto,
il live scrive; se dice "Non pronto", il live scarta — col motivo per colonna.

---

## 4. Quale parser è attivo (routing)

Risoluzione (in `parser_manager` / `signal_router`):

1. se la chat di origine ha una voce in `parser_by_chat` → quel parser;
2. altrimenti, se è la chat configurata (`chat_id`) e c'è un `active_parser`
   globale → quel parser;
3. altrimenti → **parser hardcoded** storico.

Nel live, il chat id usato è quello **reale del messaggio** (così l'override
per-chat funziona anche con setup multi-chat dove `chat_id` singolo non è
impostato). Se né `chat_id` né `parser_by_chat` sono configurati, vale il
comportamento legacy (tutte le chat ammesse — responsabilità dell'utente).

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

---

## 6. Riferimenti (codice e test)

| Componente | Modulo | Test |
|---|---|---|
| Modello dati + persistenza | `custom_parser.py` | `tests/unit/test_custom_parser_model.py` |
| Motore di estrazione (delimitatori tolleranti) | `custom_parser_engine.py` | `tests/unit/test_custom_parser_engine.py` |
| Value-map (bettype + dizionario) | `value_maps.py` | `tests/unit/test_value_maps.py` |
| Mappatura nomi squadra (profili) | `name_mapping_store.py` | `tests/unit/test_name_mapping.py` |
| GUI Dizionario nomi (finestra) | `name_mapping_gui.py` | verifica manuale (GUI) |
| Trasformazioni | `transforms.py` | `tests/unit/test_transforms.py` |
| Riga validata col contratto | `custom_pipeline.py` | `tests/unit/test_custom_pipeline.py` |
| Diagnostica «Prova messaggio» (per-campo) | `parser_diagnostics.py` | `tests/unit/test_parser_diagnostics.py` |
| Builder GUI (controller + vista) | `parser_builder.py`, `custom_parser_gui.py` | `tests/unit/test_parser_builder.py` |
| Parser attivo / override per chat | `parser_manager.py` | `tests/unit/test_parser_manager.py` |
| Import/export + esempio | `parser_io.py` | `tests/unit/test_parser_io.py` |
| Instradamento live + gate | `signal_router.py` | `tests/unit/test_signal_router.py` |
| **Catena end-to-end** | — | `tests/integration/test_custom_parser_end_to_end.py` |

> Note di verifica: la **GUI** del builder e il **flusso live** Telegram→CSV vanno
> provati a mano su Windows (non testabili in ambiente headless). Tutta la logica
> di parsing/validazione/instradamento è invece coperta da test automatici. Il
> merge di ogni PR resta **manuale** del proprietario.
