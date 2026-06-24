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

```
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
2. **Match ambiguo (più frasi combaciano) — DA CONFERMARE (default: fail-closed).**
   Se due voci diverse combaciano e indicano Mercato/Selezione **diversi**, è ambiguo →
   `MARKET_MAPPING_MISSING` (non si tira a indovinare). *Alternativa* (se preferisci):
   match della frase **più lunga/più specifica**. Default proposto: **fail-closed**.
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
   mercato scelto (garantito già in fase di GUI: la tendina Selezione dipende dal Mercato).
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

## 6. GUI (area 🎯 Mercati della scheda Mapping)

Nell'area **🎯 Mercati** (oggi placeholder): selettore profilo (nuovo/rinomina/elimina,
come ⚽ Calcio) + tabella righe:

```
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
