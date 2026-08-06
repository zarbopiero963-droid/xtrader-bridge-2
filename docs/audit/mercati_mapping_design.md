# Design — Mappatura Mercati (FASE 2)

> **Stato: IMPLEMENTATO** (store + runtime + GUI + selettore nel Parser).
>
> **Revisione (post-merge):** la modalità di match è cambiata da **"frase su tutto il
> messaggio" (D3 originale)** a **estrazione da campo delimitato** (`Inizia dopo` /
> `Finisce prima`, come una regola del Parser). Motivo: i provider con un banner/menu di
> mercati in testa (es. `P.Bet. 30/0,5HT/1,5HT/1 ASIATICO`) producevano falsi match e
> ambiguità con la ricerca su tutto il testo. Leggendo solo il campo delimitato (es. fra
> «Quota» e «Prematch») si prende il mercato vero del segnale. Tutto il resto del design
> (precedenza D1, ambiguità fail-closed D2, canonicalizzazione dal Catalogo, no ID
> contraddittori) resta valido. Dove sotto si legge "frase", intendi ora "Testo mercato
> riconosciuto nel campo estratto".

## 1. Obiettivo

Tradurre una **frase-mercato del provider** nel **Mercato + Selezione XTrader** canonici,
scelti dal **Catalogo XTrader** (gli stessi menù a tendina `Mercato → Selezione` già usati
nel Parser Personalizzato, `parser_builder.market_options()/selection_options()`).

Esempio (richiesto dal proprietario):

```text
frase provider:  "goal prima di 70"
⇒  Mercato:   Over/Under 2.5
   Selezione: Over 2.5
```

È un **riconoscimento a frase**: se il messaggio Telegram contiene la frase, il bridge
imposta Mercato+Selezione dal dizionario. Si **richiama dentro il Parser Personalizzato**
(come già il dizionario nomi squadra), così il parser diventa più automatico.

## 2. Dove si colloca (speculare al dizionario nomi)

Il dizionario nomi squadra è già:

- **dati**: `name_mapping_store.py` (funzioni pure + profili in `config.json`);
- **GUI**: area **⚽ Calcio** della scheda **🗺️ Mapping** (`name_mapping_gui.py`);
- **runtime**: `custom_pipeline.build_validated_row()` traduce `EventName` **prima** della
  validazione; se richiesto ma non traducibile → stato **`MAPPING_MISSING`** (fail-closed,
  nessuna riga scritta).

La mappatura mercati replica lo **stesso schema**:

| Livello | Dizionario nomi (esistente) | Dizionario mercati (nuovo) |
|---|---|---|
| Dati/store | `name_mapping_store.py` | **`market_mapping_store.py`** (nuovo) |
| Config key | `name_mapping_profiles` | **`market_mapping_profiles`** (nuovo) |
| GUI | area ⚽ Calcio | area **🎯 Mercati** (già predisposta, vuota) |
| Aggancio parser | `defn.name_mapping_profiles` | **`defn.market_mapping_profiles`** (nuovo) |
| Runtime | traduce `EventName` | imposta `MarketName`/`SelectionName` (+ `MarketType`) |
| Fail-closed | `MAPPING_MISSING` | **`MARKET_MAPPING_MISSING`** (nuovo) |

## 3. Modello dati (proposta)

Una **voce** del dizionario mercati (per-profilo, come i nomi):

```jsonc
{
  "phrase": "goal prima di 70",     // frase del provider (match case-insensitive, vedi §5)
  "market_type": "OVER_UNDER",      // dal catalogo (può servire al contratto CSV)
  "market_name": "Over/Under 2.5",  // dal Catalogo XTrader (market_options)
  "selection_name": "Over 2.5"      // dal Catalogo XTrader (selection_options del mercato)
}
```

Un **profilo mercati** = lista di voci, salvato in `config.json` sotto
`market_mapping_profiles` (stessa forma a profili del dizionario nomi). `market_name`/
`selection_name`/`market_type` **non** sono testo libero: si scelgono dai menù del
Catalogo XTrader, così il valore scritto nel CSV è **sempre** canonico (no typo, no
mercato inesistente).

## 4. Runtime — dove agisce e regola di PRECEDENZA

Hook in `custom_pipeline.build_validated_row()`, **dopo** l'estrazione dei campi dal
messaggio e **prima** della validazione/scrittura, **solo** se il parser ha un profilo
mercati selezionato (`defn.market_mapping_profiles`).

**Regola di precedenza — CONFERMATA (D1): il DIZIONARIO mercati VINCE.**

> Quando il parser ha un profilo mercati selezionato e una frase **combacia in modo
> univoco**, i campi `MarketType`/`MarketName`/`SelectionName` del **dizionario
> sovrascrivono** quelli eventualmente estratti dalle regole-colonna. Se **nessuna** frase
> combacia, restano i valori delle regole-colonna (se presenti). In caso di **ambiguità**
> vale il fail-closed (§5.2). Se il mercato resta comunque assente → `MARKET_MAPPING_MISSING`.

Riepilogo decisione per `MarketName`/`SelectionName`/`MarketType`:

| Situazione | Risultato |
|---|---|
| Frase del dizionario combacia (univoca) | **valore del dizionario** (vince sulla regola-colonna) |
| Più frasi combaciano con mercati diversi | `MARKET_MAPPING_MISSING` (niente riga) |
| Nessuna frase combacia, ma la regola-colonna ha estratto il mercato | valore della regola-colonna |
| Nessuna frase combacia e nessuna regola-colonna | `MARKET_MAPPING_MISSING` (niente mercato inventato) |

Motivazione della scelta del proprietario: per i provider che scrivono i mercati **a
parole** ("goal prima di 70"), il dizionario è la sorgente autorevole del mercato; le
regole-colonna restano per gli altri campi e come fallback quando nessuna frase combacia.

## 5. Sicurezza / fail-safe (NON negoziabile)

1. **Nessun match ⇒ niente mercato inventato.** Se il profilo mercati è richiesto ma
   nessuna frase combacia, e il mercato non è stato estratto dalle regole → stato
   **`MARKET_MAPPING_MISSING`**: la riga **non** viene scritta nel CSV (come
   `MAPPING_MISSING` per i nomi). Mai scrivere un mercato "a caso".
2. **Match ambiguo (più frasi combaciano) — fail-closed, E ANNUNCIATO.**
   Se due voci diverse combaciano e indicano Mercato/Selezione **diversi**, è ambiguo →
   `MARKET_MAPPING_MISSING` (non si tira a indovinare).

   Il fail-closed da solo non basta: fino alla **#254** il conflitto non veniva detto a
   nessuno, e l'operatore lo scopriva da un segnale sparito — cioè quando era già perso.
   `ambiguous_phrase_warnings` lo porta nel log eventi **allo START**, gemella di
   `name_mapping_store.ambiguous_alias_warnings` (B21). È la stessa classe di difetto, e sui
   mercati morde più facilmente: le voci si scrivono a **frasi libere** («gg», «over 2,5»,
   «goal»), quindi due frasi finiscono per combaciare senza che l'utente se ne accorga molto
   più facilmente di due squadre con lo stesso alias.

   **L'avviso non ricalcola l'ambiguità: la chiede a `resolve_market`.** Per ogni voce
   costruisce dalla voce stessa il testo minimo che la farebbe combaciare (`start_after` +
   frase + `end_before`) e ne domanda l'esito — stessa estrazione, stesso match a confini di
   token, stessa canonicalizzazione, stesso tier lingua. La lezione arriva dalla #253, dove
   l'avviso gemello *simulava* il resolver e in quattro giri di review sono emersi quattro modi
   diversi in cui le due detection divergevano. E come lì si provano **più chiamanti** (senza
   filtro-lingua, più ogni lingua presente nelle voci): due voci di lingue diverse non sono un
   conflitto per chi dichiara la lingua, ma lo sono per chi non la dichiara.

   **Tetto dichiarato.** Il controllo chiede al runtime una volta per voce (e per lingua),
   quindi il costo cresce col **quadrato** delle voci. Misure allo START **col tetto
   disattivato**, prima e dopo la cache dei pattern compilati introdotta dalla #256:

   | voci | prima (#255) | dopo (#256) | col tetto attivo (oggi) |
   |---:|---:|---:|---|
   | 100 | 0,09 s | 0,09 s | 0,09 s — controllo eseguito |
   | 400 | 1,2 s | 1,15 s | **non eseguito** (oltre il tetto) |
   | 800 | **54 s** | **4,53 s** | **non eseguito** (oltre il tetto) |
   | 1200 | — | 9,35 s | **non eseguito** (oltre il tetto) |

   ⚠️ Le prime due colonne, dalle 400 voci in su, sono **ipotetiche**: servono a rispondere alla
   domanda «quanto costerebbe senza tetto», cioè a **giustificare che il tetto esista**. Non
   descrivono ciò che l'utente paga oggi — sopra le 300 voci per profilo il controllo non parte
   proprio, e al suo posto compare un avviso.

   Il dirupo a 800 voci era il **thrashing della cache interna di `re`**: `_phrase_in_text`
   ricostruiva e ricompilava un regex per frase a ogni chiamata, e oltre ~512 pattern distinti
   la cache smetteva di assorbire. La #256 compila una volta per frase e tiene i pattern in una
   `lru_cache` di modulo, chiusa la voragine (vedi §5.6).

   Oltre **300 voci per profilo** il controllo si ferma e **lo dice nel log**: il quadrato resta
   anche senza thrashing — a 1200 voci *sarebbero* ancora 9 s di finestra bloccata — e un cap che
   tace si leggerebbe come «nessun conflitto». Il tetto è oggi più conservativo di quanto
   servirebbe: alzarlo è una decisione a sé, con la sua misura. Le frasi ambigue restano comunque
   fail-closed a runtime — cambia solo che non vengono elencate.

   **Il tetto non protegge il runtime.** Vale solo per la diagnostica allo START. Il percorso
   live non ha tetto e non può averne uno — non si può rifiutare di risolvere un mercato perché
   il dizionario è grande — ed è esattamente per questo che la #256 era necessaria: prima della
   cache, un dizionario oltre le ~512 frasi costava ~100 ms **per messaggio** invece di ~1 ms.

   **Due tetti in più, dal punto 2 della #256.** Quello per profilo non limitava il **totale**:
   N profili al tetto sommavano il costo allo START, perché il costo è lineare nelle voci
   esaminate (~2,2 ms l'una). E il numero di **avvisi** è un problema a sé, indipendente dal
   tempo: 1200 righe di ⚠️ non si leggono, e un elenco che nessuno scorre informa quanto il
   silenzio che la #254 aveva tolto.

   | profili al tetto | voci | prima | dopo |
   |---:|---:|---:|---:|
   | 1 | 300 | 0,66 s · 150 avvisi | 0,66 s · 51 avvisi |
   | 3 | 900 | 1,92 s · 450 avvisi | 1,98 s · 51 avvisi |
   | 5 | 1500 | 3,31 s · 750 avvisi | 1,95 s · 52 avvisi |
   | 8 | 2400 | 5,39 s · 1200 avvisi | 1,93 s · 52 avvisi |

   - `_MAX_VOCI_TOTALI_CONTROLLO = 900` — budget globale, tiene il caso peggiore sotto ~2 s;
   - `_MAX_AVVISI_AMBIGUITA = 50` — tetto sugli avvisi elencati.

   **Entrambi dichiarati, come i precedenti.** Il budget nomina i profili **non controllati**
   («…5 profili NON controllati («P3», «P4»…)») e il troncamento dice **quanti** conflitti
   restano fuori. Vale anche per un profilo saltato che era *sano*: chi legge non può saperlo, e
   l'assenza di avvisi significherebbe «controllato e pulito».

   La riga che spiega la copertura parziale **non viene mai troncata**: è tenuta in una lista
   separata dai conflitti, perché un troncamento che si mangia la spiegazione sarebbe il cap
   muto travestito.
3bis. **Niente ID stantii quando il dizionario vince.** La mappatura mercati è *name-based*
   (`resolve_market` non risolve `MarketId`/`SelectionId`: non sono nel Catalogo). Se le
   regole-colonna hanno estratto una coppia ID e poi il dizionario vince, lasciare quegli ID
   nella riga darebbe identificatori **contraddittori** (nel CSV, o in validazione ID/BOTH
   gli ID vecchi "vincerebbero" ignorando la frase). Perciò, al match univoco, `MarketId`/
   `SelectionId` vengono **azzerati**: la riga ha un solo mercato, la tupla a nome del
   dizionario. In **ID_ONLY** ciò comporta fail-closed in validazione (combinazione
   incoerente: phrase-mapping + riconoscimento a ID); in **BOTH** la coppia a nome basta e la
   riga resta valida (CodeRabbit).
3. **Coerenza + canonicalizzazione Mercato/Selezione.** La selezione deve appartenere al
   mercato scelto. La GUI aiuta (la tendina Selezione dipende dal Mercato) ma **non basta**:
   `dizionario.selections_for_market` combacia su `MarketType` **oppure** `MarketName` —
   comodo per le tendine, pericoloso al momento di **accoppiare**. Se il `MarketName` risolto
   coincide col `MarketType` di un'altra riga, la selezione arriva da quella riga e finisce
   accoppiata al `market_type` di questa: una coppia che nel dizionario **non esiste**.
   Perciò `_canonical_market` verifica esplicitamente che la selezione appartenga al mercato
   risolto (`MarketName` normalizzato uguale) e, se non lo è, **non risolve** (B20 #194, audit
   #192 L16). Sul catalogo spedito non cambia nulla — misurato: 81 righe, 22 `MarketType` e 22
   `MarketName` distinti, **0 collisioni** — chiude il caso del dizionario esteso o editato a
   mano. *Residuo dichiarato:* su un catalogo così sporco le tendine GUI possono ancora
   **offrire** una coppia che il runtime rifiuterà; la direzione resta sicura (segnale non
   scritto, non scritto sbagliato).
   In più **`resolve_market` risolve ogni voce nella tupla CANONICA del Catalogo XTrader**
   (`_canonical_market`): il match è case/spazio-insensitive, ma ciò che si ritorna — e che
   il runtime scriverà nel CSV — sono **sempre** i valori canonici del catalogo
   (`MarketType`, `MarketName`, `SelectionName`), **non** i valori grezzi del config. Una
   coppia non nel catalogo → **ignorata** (mai scritta); una valida ma non-canonica
   (case/spazi diversi, `market_type` stantio) → valori canonici. Così anche un bypass della
   GUI o una config a mano restano fail-safe e producono sempre una tupla che XTrader
   riconosce (Codex).
4. **Una sola riga attiva.** Invariato: il CSV resta one-signal-at-a-time, svuotato dopo
   il timeout. La mappatura mercati non cambia questa catena.
5. **Match su che testo? — RIVISTO (vedi nota di revisione in testa): campo DELIMITATO.**
   Il mercato si legge **solo** dal campo ritagliato dai delimitatori ``Inizia dopo`` /
   ``Finisce prima`` della voce (stesso motore del Parser, ``custom_parser_engine.extract_between``);
   poi il **Testo mercato** della voce si confronta in quel campo (case-insensitive, confini
   di token). Una voce **senza** delimitatori è **preservata** in config (no perdita dati) ma
   **non applicata** (il resolver la salta, fail-closed). *Motivo del cambio*: molti provider
   mettono in testa un banner/menu con più mercati (es. ``30/0,5HT/1,5HT/1``); cercare la frase
   in **tutto** il messaggio dava falsi match/ambiguità. Leggendo solo il campo delimitato
   (es. fra «Quota» e «Prematch») si prende il mercato vero e si ignora il banner.
6. **Il pattern di match è compilato una volta per frase (#256).** Il regex a confini di token
   costruito da `_phrase_in_text` dipende **solo** dalla frase normalizzata, ma veniva
   ricostruito e ricompilato a **ogni** chiamata — cioè una volta per voce **per messaggio**.
   Il modulo `re` tiene una cache interna di ~512 pattern: sotto quella soglia il costo non si
   vede, sopra ogni messaggio ricompilava l'intero dizionario. Misurato sul percorso live
   (`resolve_market`, media su 20 messaggi):

   | frasi mappate | prima | dopo |
   |---:|---:|---:|
   | 100 | 0,73 ms | 0,61 ms |
   | 400 | 2,98 ms | 2,51 ms |
   | 600 | **54,04 ms** | 3,86 ms |
   | 1200 | 108,42 ms | 7,62 ms |

   `_phrase_pattern` è una `lru_cache` di modulo indicizzata sulla frase **normalizzata**
   («GG», «gg» e «  gg  » sono la stessa frase per il matching, quindi la stessa voce di
   cache). Il tetto `maxsize` è deliberato: le frasi arrivano dal config dell'utente, e una
   cache illimitata su input utente è una perdita di memoria lenta; oltre il tetto si sfrattano
   le voci meno usate e si torna a ricompilare quelle, senza mai sbagliare risposta.

   **Il confronto non cambia**: cambia solo quante volte lo si compila. È un punto sensibile
   perché `_phrase_in_text` sta sul percorso soldi — un confine di token sbagliato qui è un
   mercato sbagliato, cioè una scommessa sbagliata (P1 in
   `tests/safety/test_money_path_p1_bughunt.py`) — perciò i test della #256 verificano
   l'**invarianza del matching attraverso la cache**, non solo che la cache esista.

## 6. GUI (area 🎯 Mercati della scheda Mapping)

Nell'area **🎯 Mercati** (oggi placeholder): selettore profilo (nuovo/rinomina/elimina,
come ⚽ Calcio) + tabella righe:

```text
Frase provider           | Mercato (catalogo)   | Selezione (catalogo)  | 🗑
[ goal prima di 70     ] | [ Over/Under 2.5  ▾] | [ Over 2.5         ▾] | ✕
```

Mercato/Selezione = menù dal Catalogo XTrader (Selezione dipende dal Mercato). Nel
**Parser Personalizzato**: una spunta/selettore "profilo mercati" accanto a quello dei
nomi squadra, così al parsing si traducono **sia** i nomi **sia** i mercati.

## 7. Piano di implementazione (PR piccole, una alla volta)

1. **`market_mapping_store.py`** — ✅ **FATTO** — funzioni pure + `resolve_market(text,
   profiles)` → `MarketResolution(status, market)` con status `ok`/`ambiguous`/`none`. **Solo
   logica + test hard** (`tests/unit/test_market_mapping.py`, 18 test): match univoco,
   nessun match, ambiguità fail-closed (D2), confini di parola (D3), CRUD profili,
   immutabilità. Nessuna GUI, nessun runtime.
2. **Aggancio runtime** — ✅ **FATTO** — hook in `custom_pipeline.build_validated_row()`
   con la regola di precedenza §4 e `MARKET_MAPPING_MISSING`; campo
   `CustomParserDef.market_mapping_profiles` (modello + `to_dict`/`from_dict`); wiring
   `signal_router` (risolve le voci da config), `parser_builder` (round-trip + anteprima
   `test_message`), `parser_diagnostics` (overlay su Mercato/Selezione). Fallback **mode-aware**
   (`_row_has_market`): in assenza di match a frase il fail-closed scatta solo se le
   regole-colonna non hanno prodotto un mercato **per la modalità di riconoscimento** (NAME →
   MarketType+SelectionName; ID → MarketId+SelectionId), così una riga ID valida non viene
   scartata per errore. Test hard end-to-end in `tests/unit/test_market_mapping_runtime.py`
   (dizionario vince; ambiguo → niente riga; nessun match → fallback colonna; nessun match e
   nessun mercato → niente riga; voce incoerente ignorata; match sul messaggio grezzo;
   round-trip modello/builder; instradamento reale `signal_router`).
3. **GUI** — in due PR piccole:
   - **3a (FATTO)** — area **🎯 Mercati** della scheda Mapping (`MarketMappingPanel` in
     `name_mapping_gui.py`): profilo (nuovo/rinomina/elimina) + tabella `Frase | Mercato ▾ |
     Selezione ▾` dai menù del Catalogo (Selezione dipende dal Mercato, `MarketType` derivato);
     persiste in `market_mappings`. Helper parser generalizzati
     (`rename_market_mapping_profile_in_files`, `parsers_using_market_mapping_profile`) per
     aggiornare/avvisare i parser al rename/delete del profilo. Non testato in CI (display);
     logica pura coperta da `market_mapping_store`/`dizionario` + test helper. Verifica manuale
     su Windows.
   - **3b (FATTO)** — selettore dei **profili mercati dentro il Parser Personalizzato**
     (`custom_parser_gui`): riga «Mappatura mercati» con pulsante «🎯 Dizionario mercati»
     (`MarketMappingWindow`) + checkbox multi-selezione, accanto ai nomi. Sync a
     `builder.market_mapping_profiles`; «Prova messaggio» risolve i profili mercati dalla
     config (anteprima coerente col runtime). Include lo stesso meccanismo dei nomi: profili
     **⚠ fantasma** (selezionati ma non più esistenti) che **bloccano salvataggio e
     anteprima** (`_unresolved_market_selected`) + refresh su `refresh_options`. Questo
     **chiude il rilievo Codex P2** della PR 3a: un `CustomParserPanel` aperto non riscrive
     più un profilo mercati stantio dopo un rename/delete. Test: round-trip builder +
     forward `market_mapping_profiles` in `test_message`. GUI non testata in CI (display):
     verifica manuale su Windows.

Ogni passo: Phase 0, micro-audit, test hard veritieri, una PR, merge manuale.

## 8. Decisioni del proprietario (CONFERMATE)

- **D1 — Precedenza** (§4): **il DIZIONARIO vince** sulla regola-colonna quando una frase
  combacia (univoca). *(scelta dal proprietario; non il default proposto)*
- **D2 — Ambiguità** (§5.2): **fail-closed** — match ambiguo ⇒ `MARKET_MAPPING_MISSING`.
- **D3 — Testo di match** (§5.5): **RIVISTO → campo delimitato** (`Inizia dopo`/`Finisce
  prima`, poi Testo mercato nel campo estratto, case-insensitive, confini di token). Sostituisce
  il "messaggio grezzo" originale per non farsi ingannare dai banner/menu del provider.
- **D4 — `MarketType`**: **sì**, mappato dal Catalogo XTrader insieme a Mercato/Selezione.

Design **approvato** con queste decisioni → si procede dal passo 1 (`market_mapping_store.py`
+ test hard), senza toccare GUI/runtime finché lo store non è solido.
