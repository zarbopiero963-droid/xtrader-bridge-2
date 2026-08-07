"""Dizionario di mappatura mercati: frase del provider → Mercato/Selezione Betfair.

Alcuni provider (canali Telegram) scrivono il mercato **a parole** ("0,5 HT") dentro il
messaggio. Questo modulo tiene **profili** di regole che leggono il mercato **da una
posizione precisa** del messaggio — tra i delimitatori ``Inizia dopo``/``Finisce prima``,
come una regola del Parser Personalizzato — e lo traducono nel Mercato/Selezione canonici
del **Catalogo Betfair**. I valori di mercato/selezione **non** sono testo libero: vanno
scelti dal Catalogo (vedi GUI), così ciò che finisce nel CSV è sempre canonico.

Perché a delimitatori e non "frase su tutto il messaggio": molti provider mettono in testa
un **banner/menu** con più mercati (es. ``P.Bet. 30/0,5HT/1,5HT/1 ASIATICO``); cercare la
frase nell'intero testo darebbe falsi match/ambiguità. Leggendo SOLO il campo delimitato
(es. fra «Quota» e «Prematch») si prende il mercato vero del segnale e si ignora il banner.

Modello dati (config, chiave ``market_mappings``)::

    cfg["market_mappings"] = {
        "<nome profilo>": [
            {"start_after": "Quota",      # "Inizia dopo": delimitatore sinistro
             "end_before": "Prematch",    # "Finisce prima": delimitatore destro ("" = fine riga)
             "phrase": "0,5 HT",          # testo mercato da riconoscere nel campo estratto
             "market_type": "FIRST_HALF_GOALS_05",
             "market_name": "1º tempo - Totale goal 0,5",
             "selection_name": "Over 0,5 goal"},
            ...
        ],
        ...
    }

Logica PURA su un ``dict`` di config: nessuna GUI, nessun I/O — la persistenza è del
chiamante (``config_store.save_config``), come ``name_mapping_store``/``provider_store``.
Le funzioni di modifica ritornano una COPIA della config, non mutano l'originale.

Sicurezza (safety-critical: un mercato sbagliato = scommessa sbagliata). Decisioni
del proprietario, vedi ``docs/audit/mercati_mapping_design.md``:
- **D2 fail-closed sull'ambiguità**: se più frasi combaciano e indicano mercati
  **diversi**, ``resolve_market`` ritorna stato ``"ambiguous"`` → il chiamante NON
  scrive nulla (niente mercato "a caso");
- **D3 match sul campo estratto**: il mercato si legge SOLO tra i delimitatori
  ``Inizia dopo``/``Finisce prima`` (non su tutto il messaggio), poi il testo mercato si
  confronta case-insensitive e su **confini di token** (no falsi positivi tipo "over" dentro
  "overflow"). Una voce **senza delimitatori** è **preservata** in config ma **non
  applicata** (``resolve_market`` la salta, fail-closed): la modalità "frase su tutto il
  messaggio" è rimossa, ma le voci vecchie non vengono cancellate (no perdita dati);
- nessun match → stato ``"none"`` (il chiamante decide il fallback, vedi precedenza D1
  nel runtime). ``resolve_market`` non inventa mai un mercato.

NB: la **precedenza D1** ("il dizionario vince" sulla regola-colonna) è una scelta del
**runtime** (``custom_pipeline``), non di questo store: qui si risolve solo la frase.
"""

import logging
import re
from collections import namedtuple
from functools import lru_cache

from . import dizionario, mapping_store_base, recognition
from .custom_parser_engine import extract_between

_LOG = logging.getLogger(__name__)

# Chiave di config che ospita i profili di mappatura mercati.
_STORE_KEY = "market_mappings"

# Tetto di voci per profilo oltre il quale il controllo delle frasi ambigue (#254) non viene
# eseguito: il costo cresce col quadrato delle voci. Oltre il tetto il controllo si ferma e
# LO DICE.
#
# Misure allo START col TETTO DISATTIVATO, prima e dopo la cache dei pattern della #256.
# Dalle 400 voci in su sono IPOTETICHE: servono a giustificare che il tetto esista, non a
# descrivere ciò che si paga oggi (col tetto attivo il controllo su quei profili non parte).
#
#     voci     prima      dopo
#      100     0,09 s     0,09 s     <- l'unica riga sotto il tetto, quindi davvero eseguita
#      400     1,2  s     1,15 s
#      800    54    s     4,53 s      <- il dirupo era il thrashing della cache di `re`
#     1200      —        9,35 s
#
# Il dirupo a 800 era la cache interna di `re` (~512 pattern) che andava in thrashing; con
# `_phrase_pattern` non c'è più, e il costo è tornato quadratico-liscio. **Il tetto resta a
# 300** lo stesso: il quadrato cresce comunque, e 1200 voci costano ancora 9 s allo START.
# È ora più conservativo del necessario — alzarlo è una decisione a sé, con la sua misura.
_MAX_VOCI_CONTROLLO_AMBIGUITA = 300

# Budget GLOBALE di voci esaminate dal controllo frasi ambigue, su tutti i profili (#256 punto
# 2). Il tetto per profilo qui sopra non limitava il totale, e il costo e' lineare nelle voci:
# ~2,2 ms l'una, misurato. Con profili tutti al tetto per profilo:
#
#     1 profilo  =  300 voci ->  0,66 s ·  150 avvisi
#     3 profili  =  900 voci ->  1,92 s ·  450 avvisi
#     8 profili  = 2400 voci ->  5,39 s · 1200 avvisi
#
# 900 tiene il caso peggiore sotto i ~2 s di finestra bloccata allo START, ed e' ben oltre
# qualunque config reale (i profili veri hanno decine di voci, non centinaia).
_MAX_VOCI_TOTALI_CONTROLLO = 900

# Tetto sul NUMERO di avvisi di conflitto elencati. Problema distinto dal tempo: 1200 righe di
# avviso nel log non si leggono, e un elenco che nessuno scorre informa quanto il silenzio che
# la #254 aveva tolto. Si tronca DICENDO quanti ne restano.
_MAX_AVVISI_AMBIGUITA = 50

# Esito della risoluzione di un mercato da una frase.
#   status: "ok"        → match univoco; `market` = {market_type, market_name, selection_name}
#           "ambiguous" → più frasi combaciano con mercati DIVERSI (fail-closed, D2); market=None
#           "none"      → nessuna frase combacia; market=None
MarketResolution = namedtuple("MarketResolution", ["status", "market"])


def _normalize_text(s) -> str:
    """Testo normalizzato per il confronto: spazi collassati + casefold (case-insensitive)."""
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _malformed_fields(entry: dict) -> list:
    """Coppie ``(campo, valore_grezzo)`` NON riconosciute di una voce mercato: per ora la
    sola ``language`` (epica #3 slice 5c) non-vuota e non ``IT``/``EN``/``ES``. Vuoto =
    agnostico intenzionale (vale per tutte le lingue), NON malformato. Predicato unico
    condiviso tra ``_clean_entry`` (scarto fail-closed) e ``malformed_entry_warnings``
    (avvisi GUI), così i due non possono divergere — stesso pattern di
    ``name_mapping_store._malformed_fields``."""
    out = []
    # language (epica #3 slice 5c): non-vuoto ma non IT/EN/ES → FAIL-CLOSED come nel
    # dizionario nomi. Un typo di lingua non deve allargare in silenzio la voce a "tutte le
    # lingue" (un mercato applicato a una lingua sbagliata = scommessa sbagliata).
    raw_language = str(entry.get("language", "") or "").strip()
    if raw_language and not recognition.normalize_source_language(raw_language):
        out.append(("language", raw_language))
    return out


def _clean_entry(entry) -> dict:
    """Normalizza una voce in ``{start_after, end_before, phrase, market_type, market_name,
    selection_name, language}`` (stringhe ripulite), o ``None`` se inutile.

    Una voce è valida se ha **testo mercato** (``phrase``), **market_name** e
    **selection_name**: senza, non può formare un mercato. I delimitatori ``start_after``/
    ``end_before`` sono **facoltativi a livello dati**: così una config vecchia senza
    delimitatori NON viene cancellata al load/save (niente perdita dati, CodeRabbit). È
    ``resolve_market`` a **non applicare** una voce senza delimitatori — la **salta**
    (fail-closed) — invece di eliminarla. Dei delimitatori si tolgono **solo spazi/tab** ai
    bordi (come ``_delim_pattern`` del Parser), **preservando i newline** (es. ``"\\nMercato:"``
    resta ancorato a inizio riga, Codex). ``market_type`` può essere vuoto (lo ricava
    ``_canonical_market`` dal catalogo).

    ``language`` (epica #3 slice 5c): lingua della fonte (``IT``/``EN``/``ES``); **vuoto** →
    ``""`` = agnostico (retro-compatibile con le voci salvate prima). Un valore non-vuoto ma
    **non riconosciuto** (typo) è FAIL-CLOSED come nel dizionario nomi: la voce viene
    **scartata** (mai allargata a tutte le lingue), con avviso in ``malformed_entry_warnings``."""
    if not isinstance(entry, dict):
        return None
    start_after = str(entry.get("start_after", "") or "").strip(" \t")
    end_before = str(entry.get("end_before", "") or "").strip(" \t")
    phrase = str(entry.get("phrase", "") or "").strip()
    market_type = str(entry.get("market_type", "") or "").strip()
    market_name = str(entry.get("market_name", "") or "").strip()
    selection_name = str(entry.get("selection_name", "") or "").strip()
    # `raw_language` ripulito UNA volta e condiviso con la validazione: `_malformed_fields`
    # valida `str(...).strip()`, quindi persistere lo STESSO valore ripulito evita ogni
    # divergenza tra ciò che si valida e ciò che si salva (Sourcery bug_risk #26).
    raw_language = str(entry.get("language", "") or "").strip()
    if not phrase or not market_name or not selection_name:
        return None
    if _malformed_fields(entry):                 # language typo → voce scartata (fail-closed)
        return None
    return {"start_after": start_after, "end_before": end_before, "phrase": phrase,
            "market_type": market_type, "market_name": market_name,
            "selection_name": selection_name,
            "language": recognition.normalize_source_language(raw_language)}


# CRUD condiviso (store refactor #114): le dieci funzioni identiche fra i due store vivono in
# `mapping_store_base`; qui si iniettano le TRE differenze dello store mercati — la chiave di
# config, il proprio `_clean_entry` (schema mercati) e il prefisso di log dei profili duplicati —
# e si legano le funzioni al modulo con le firme storiche. `_store`/`_norm_profile_name`/
# `_find_store_key` restano accessibili (li usano i resolver e i test) sull'implementazione condivisa.
_crud = mapping_store_base.make_profile_crud(
    store_key=_STORE_KEY, clean_entry=_clean_entry, dup_warn_prefix="market_mappings", logger=_LOG)
_store = _crud._store
_norm_profile_name = _crud._norm_profile_name
_find_store_key = _crud._find_store_key
profile_names = _crud.profile_names
get_entries = _crud.get_entries
entries_for_profiles = _crud.entries_for_profiles
set_entries = _crud.set_entries
add_profile = _crud.add_profile
delete_profile = _crud.delete_profile
rename_profile = _crud.rename_profile


def malformed_entry_warnings(cfg: dict) -> list:
    """Avvisi **non bloccanti** per la GUI/event log (epica #3 slice 5c): voci mercato con
    ``language`` non riconosciuta, che il resolver SCARTA (fail-closed). Il warning del
    logger Python non è visibile nell'app windowed: ``_start`` mostra QUESTI messaggi nel log
    eventi, così l'operatore scopre subito la voce disattivata invece che dal mercato non
    riconosciuto — stesso principio di ``name_mapping_store.malformed_entry_warnings``."""
    warnings = []
    for profile, rows in _store(cfg).items():
        if not isinstance(rows, (list, tuple)):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            phrase = str(entry.get("phrase", "") or "").strip()
            market_name = str(entry.get("market_name", "") or "").strip()
            selection_name = str(entry.get("selection_name", "") or "").strip()
            if not phrase or not market_name or not selection_name:
                continue                      # voce incompleta: scartata comunque, senza avviso
            bad = _malformed_fields(entry)
            if bad:
                dove = ", ".join(f"{f}={v!r}" for f, v in bad)
                warnings.append(
                    f"Mappatura mercati «{_norm_profile_name(profile)}», voce «{phrase}»: "
                    f"{dove} non riconosciuto -> voce IGNORATA (fail-closed). "
                    f"Correggi il valore per riattivarla.")
    return warnings


def _piano_controllo_ambiguita(cfg: dict):
    """Chi viene esaminato dal controllo frasi ambigue e chi **no**, e perché.

    Ritorna ``(esaminati, oltre_tetto, saltati_per_budget)``: il primo è una lista di
    ``(profilo_grezzo, voci)``, gli altri due contengono i nomi **normalizzati** dei profili
    esclusi — dal tetto per profilo il primo, dal budget globale il secondo.

    Estratta da `ambiguous_phrase_warnings` (#258) perché la stessa decisione serve a due
    chiamanti: gli avvisi, che la spiegano all'utente, e il semaforo Dizionari del pannello
    🚦 Salute, che **non deve mostrare verde** su profili mai controllati. Scriverla due volte
    significherebbe due copie che divergono, e la seconda direbbe «pulito» dove la prima dice
    «non guardato»: esattamente il difetto che questi avvisi esistono per togliere.

    L'ordine dei due tetti è parte del contratto (rilievo Fable 5 + GPT-5.5 sulla #261): il
    tetto per profilo va valutato **prima** del budget, altrimenti un profilo troppo grande —
    quindi mai esaminato — scalerebbe comunque il suo peso e farebbe saltare profili successivi
    sani con un «budget esaurito» che non è vero.
    """
    esaminati, oltre_tetto, saltati_per_budget = [], [], []
    voci_esaminate = 0
    for profile, righe in sorted(_store(cfg).items(),
                                 key=lambda kv: (_norm_profile_name(kv[0]), repr(kv[0]))):
        if not isinstance(righe, (list, tuple)):
            continue
        voci = [e for e in righe if isinstance(e, dict)]
        if not voci:
            continue
        if len(voci) > _MAX_VOCI_CONTROLLO_AMBIGUITA:
            oltre_tetto.append((_norm_profile_name(profile), len(voci)))
            continue
        if voci_esaminate + len(voci) > _MAX_VOCI_TOTALI_CONTROLLO:
            saltati_per_budget.append(_norm_profile_name(profile))
            continue
        voci_esaminate += len(voci)
        esaminati.append((profile, voci))
    return esaminati, oltre_tetto, saltati_per_budget


def profili_non_controllati(cfg: dict) -> list:
    """I profili mercati su cui il controllo frasi ambigue **non è stato eseguito** (#258).

    Nomi normalizzati, in ordine deterministico. Serve al semaforo Dizionari: su questi profili
    l'assenza di conflitti elencati **non** significa che siano puliti — significa che nessuno
    ha guardato. Un semaforo verde lì sarebbe una rassicurazione senza copertura.

    Pura e totale come le funzioni di avviso: non solleva, così un chiamante che la interroga
    all'avvio non può essere bloccato da una config manomessa.
    """
    _esaminati, oltre_tetto, saltati = _piano_controllo_ambiguita(cfg)
    return [nome for nome, _voci in oltre_tetto] + list(saltati)


def mercati_in_conflitto(text: str, profiles, rows=None, language=None) -> list:
    """Le coppie canoniche ``(market_type, market_name, selection_name)`` che si **contendono**
    ``text``, in ordine di incontro e senza duplicati (#282 A2).

    **Fonte unica** (regola 3). Questa tecnica esisteva già dentro `ambiguous_phrase_warnings`,
    dove serviva a scrivere l'avviso di configurazione, ed è stata **corretta quattro volte in
    review**: chiedere al runtime chi ha davvero combaciato, invece di ricostruirlo confrontando
    stringhe, è ciò che impedisce le due divergenze opposte già viste sulla #255 —

    - confronto ``==`` sulla frase: «GG» e «gg» combaciano per il resolver ma non per il
      reporting, e l'elenco mostrava un contendente solo;
    - delimitatori ignorati: una voce con la stessa frase ma altri delimitatori, estranea al
      conflitto, veniva accusata.

    La #282 ha bisogno **della stessa cosa a runtime**, per dire all'utente quali coppie sono in
    conflitto nel verdetto del «🧪 Prova messaggio». Riscriverla sarebbe stata la seconda copia
    destinata a divergere: qui è estratta, e `ambiguous_phrase_warnings` la chiama.

    Le coppie sono tuple canoniche, **non** nomi di mercato: Over e Under dello stesso mercato
    sono due contendenti distinti — sono i due lati opposti della scommessa, e chi corregge deve
    sapere quale riga guardare.

    Pura e fail-safe come le sorelle di questo modulo: `resolve_market` è difensivo su tutto ciò
    che arriva dal config, quindi testo vuoto o senza match danno semplicemente lista vuota.
    """
    contesi, viste = [], set()
    for entries in (profiles or []):
        for e in (entries or []):
            singola = resolve_market(text, [[e]], rows, language)
            if singola.status != "ok":
                continue
            m = singola.market
            tupla = (m["market_type"], m["market_name"], m["selection_name"])
            if tupla not in viste:
                viste.add(tupla)
                contesi.append(tupla)
    return contesi


def descrivi_conflitto(contesi) -> str:
    """Le coppie in conflitto rese leggibili: ``«Mercato / Selezione», «Mercato / Selezione»``.

    Sta qui e non nei chiamanti perché la #255 aveva già insegnato che **mercato senza
    selezione** non basta: due voci in conflitto sullo stesso mercato (Over/Under) sarebbero
    indistinguibili, e l'utente non saprebbe quale riga correggere.
    """
    return ", ".join(f"«{mn} / {sn}»" for _mt, mn, sn in contesi)


def ambiguous_phrase_warnings(cfg: dict, rows=None) -> list:
    """Avvisi **non bloccanti** (#254): voci mercato che combaciano con la **stessa frase** ma
    indicano mercati **diversi**. Su queste `resolve_market` ritorna ``ambiguous`` e il segnale
    viene scartato (fail-closed, design §5.2 D2) — ma finora nessuno lo diceva: il conflitto si
    scopriva solo da un segnale che spariva. Gemella di
    `name_mapping_store.ambiguous_alias_warnings`; ``_start`` porta questi messaggi nel log
    eventi, così il conflitto si vede **al load** invece che a segnale già perso.

    **Chiede al runtime, non lo simula** — ed è la lezione più cara della #253, dove l'avviso
    gemello *rifaceva* la detection e in quattro giri di review sono emersi quattro modi diversi
    in cui le due divergevano (fra cui un avviso che taceva su un conflitto vivo e uno che
    mandava a correggere un dizionario sano). Qui, per ogni voce, si costruisce dalla voce
    **stessa** il testo minimo che la farebbe combaciare — ``start_after`` + frase +
    ``end_before`` — e si chiede l'esito a `resolve_market`. Stessa estrazione
    (`extract_between`), stesso match a confini di token, stessa canonicalizzazione, stesso
    tier lingua: la divergenza non è improbabile, è impossibile.

    **Si provano più chiamanti**, non uno solo (B21 #194): l'ambiguità dipende da quale
    lingua-fonte dichiara il parser, quindi si sonda il chiamante senza filtro **più** ogni
    lingua presente nelle voci. Due voci di lingue diverse non sono un conflitto per chi
    dichiara la lingua, ma lo sono per chi non la dichiara — e va detto a quest'ultimo.

    **Due tetti, non uno** (#256 punto 2). Quello per profilo (`_MAX_VOCI_CONTROLLO_AMBIGUITA`)
    non limitava il totale: N profili al tetto sommavano il costo allo START, perché il costo è
    lineare nelle voci esaminate (~2,2 ms l'una, misurato). Da qui il budget **globale**
    `_MAX_VOCI_TOTALI_CONTROLLO`. E il numero di avvisi ha un tetto suo, indipendente dal tempo:
    1200 righe di ⚠️ non si leggono, e un elenco che nessuno scorre informa quanto il silenzio
    che la #254 aveva tolto.

    Entrambi **dichiarati, mai silenziosi**: un cap che tace si legge come «nessun conflitto».
    Vale anche per un profilo saltato che era *sano* — chi legge non può saperlo, e l'assenza di
    avvisi significherebbe «controllato e pulito».

    Fail-safe come i fratelli: la config arriva da un file editabile a mano, e un avviso
    diagnostico non deve mai impedire l'avvio."""
    # `struttura` = ciò che dice cosa NON è stato controllato; `conflitti` = i conflitti veri.
    # Separati perché il troncamento degli avvisi non deve mai mangiarsi la riga che spiega una
    # copertura parziale: sarebbe il cap muto travestito.
    struttura, conflitti = [], []
    # Chi viene esaminato e chi no lo decide `_piano_controllo_ambiguita`, **fonte unica**
    # condivisa con `profili_non_controllati` (#258): il semaforo Dizionari del pannello
    # 🚦 Salute deve sapere esattamente quali profili non sono stati guardati, e una seconda
    # copia di questa decisione finirebbe per dire «pulito» dove questa dice «non controllato».
    # I due tetti, il loro ordine e le misure che li giustificano sono documentati lì.
    esaminati, oltre_tetto, saltati_per_budget = _piano_controllo_ambiguita(cfg)
    for nome_profilo, n_voci in oltre_tetto:
        struttura.append(
            f"Mappatura mercati «{nome_profilo}»: {n_voci} voci, oltre il "
            f"tetto di {_MAX_VOCI_CONTROLLO_AMBIGUITA} per il controllo delle frasi ambigue "
            f"-> controllo NON eseguito su questo profilo (l'avvio resterebbe bloccato per "
            f"decine di secondi). Le frasi ambigue restano fail-closed a runtime, ma qui non "
            f"vengono elencate: se sospetti un conflitto, riduci il profilo o dividilo.")
    for profile, voci in esaminati:
        profili = [voci]
        # I chiamanti plausibili: senza filtro-lingua, più ogni lingua che il dizionario
        # stesso contiene. Sono le sole lingue-fonte per cui un parser può interrogare
        # queste voci.
        # Le lingue-fonte per cui un parser può interrogare queste voci. Se NESSUNA voce
        # dichiara una lingua il filtro è inerte, quindi si sonda solo il chiamante agnostico:
        # è il caso più comune, e vale un terzo del lavoro (misurato).
        dichiarate = {recognition.normalize_source_language(e.get("language", "")) for e in voci}
        dichiarate.discard("")
        lingue = {""} | dichiarate
        visti = set()
        # Sonde già provate: due voci con delimitatori e frase identici producono lo stesso
        # testo, e lo stesso testo con la stessa lingua dà lo stesso esito. Dedup esatta,
        # nessuna perdita di copertura.
        sondate = set()
        for e in voci:
            sa = str(e.get("start_after", "") or "")
            eb = str(e.get("end_before", "") or "")
            ph = str(e.get("phrase", "") or "").strip()
            if not ph or (not sa.strip(" \t") and not eb.strip(" \t")):
                continue        # voce non applicata dal runtime: non può essere ambigua
            # Il testo minimo che FA combaciare questa voce, costruito dai suoi delimitatori:
            # cercare la frase in tutto il messaggio sarebbe l'errore che il design §5.5 ha
            # già corretto una volta sul percorso runtime (banner/menu → falsi match).
            sonda = f"{sa}{ph}{eb}" if eb else f"{sa}{ph}\n"
            for lingua in sorted(lingue):
                if (_normalize_text(sonda), lingua) in sondate:
                    continue
                sondate.add((_normalize_text(sonda), lingua))
                # Nessun `try` attorno alla chiamata: `resolve_market` è difensivo su tutto
                # ciò che arriva da config (frase vuota, delimitatori assenti, coppia non
                # canonica) e la frase passa da `re.escape`, quindi non c'è nulla da cui
                # difendersi. Un blind-except qui sarebbe rumore, e il ratchet
                # (`test_blind_except_allowlist`) lo rifiuta a ragione: la garanzia «non
                # esplode» la dà `test_254_config_spazzatura_non_esplode`, che la MISURA
                # sulle config rotte, invece di asserirla con un catch-all.
                esito = resolve_market(sonda, profili, rows, lingua or None)
                if esito.status != "ambiguous":
                    continue
                # Quali mercati si contendono la frase: lo decide `mercati_in_conflitto`, la
                # FONTE UNICA condivisa col runtime della #282 (A2). La logica — ri-sondare una
                # voce alla volta e tenere chi risolve `ok` — sta lì, col perché per esteso:
                # è stata corretta quattro volte in review proprio perché ricostruirla a mano
                # faceva divergere il reporting dalla detection, in due modi opposti.
                #
                # Da #282 la stessa risposta serve anche al verdetto del «🧪 Prova messaggio»:
                # tenerne due copie avrebbe rimesso in piedi la divergenza appena chiusa.
                contesi = mercati_in_conflitto(sonda, profili, rows, lingua or None)
                if len(contesi) < 2:
                    continue        # niente da elencare: non si scrive un avviso vuoto
                # La chiave include la SONDA: due conflitti fra gli stessi due mercati ma su
                # frasi diverse sono due righe diverse da correggere. Senza, 150 conflitti
                # distinti collassavano in **un solo** avviso (misurato), cioè 149 nascosti —
                # una diagnostica che ne mostra uno su 150 è peggio di nessuna, perché dà la
                # sensazione di aver capito il problema (Fugu Ultra, Fable 5).
                # La sonda entra NORMALIZZATA come la normalizza il runtime: «GG» e «gg»
                # sono la stessa sonda per `_phrase_in_text`, quindi lo stesso conflitto —
                # due avvisi sarebbero rumore. Frasi davvero diverse restano distinte.
                chiave = (profile, _normalize_text(sonda), frozenset(contesi))
                if chiave in visti:
                    break
                visti.add(chiave)
                # Mercato + selezione: col solo mercato due righe in conflitto sullo
                # stesso mercato sarebbero indistinguibili nel messaggio. La resa è in
                # `descrivi_conflitto` (#282), condivisa col motivo mostrato a runtime: la
                # stessa coppia in conflitto si legge identica nell'avviso di config e nel
                # verdetto del test messaggio.
                dove = descrivi_conflitto(contesi)
                # «coppie mercato/selezione», non «mercati»: i contendenti sono tuple canoniche,
                # quindi Over e Under dello STESSO mercato contano due — ed è giusto che contino
                # due, sono i due lati opposti della scommessa. Dire «2 mercati diversi» davanti
                # a un solo nome di mercato elencato due volte si legge come un errore
                # dell'avviso (GPT-5.5 e Fable 5, indipendentemente): il conteggio deve dire
                # esattamente cosa conta.
                conflitti.append(
                    f"Mappatura mercati «{_norm_profile_name(profile)}», frase «{ph}»: "
                    f"combacia con {len(contesi)} coppie mercato/selezione diverse ({dove}) -> il mercato "
                    f"NON viene risolto e il segnale è scartato (fail-closed). Rendi le frasi "
                    f"distinguibili, oppure togli una delle voci in conflitto.")
                break

    if saltati_per_budget:
        struttura.append(
            f"Controllo frasi ambigue: budget complessivo di {_MAX_VOCI_TOTALI_CONTROLLO} voci "
            f"esaurito -> {len(saltati_per_budget)} profili NON controllati "
            f"({', '.join(f'«{p}»' for p in saltati_per_budget)}). Il controllo costa ~2 ms per "
            f"voce e allo START blocca la finestra: oltre il budget si ferma. Le frasi ambigue "
            f"restano fail-closed a runtime, ma su questi profili non vengono elencate — non "
            f"significa che siano puliti. Riduci o dividi i profili per farli rientrare.")

    # Tetto sugli AVVISI, indipendente dal tempo: un elenco di centinaia di righe non si legge,
    # e un avviso che nessuno scorre informa quanto il silenzio che la #254 aveva tolto. Si
    # tronca dicendo QUANTI ne restano — troncare in silenzio ricreerebbe il cap muto.
    # La `struttura` non si tronca MAI: spiega cosa non e' stato controllato, ed e' l'ultima
    # cosa che deve sparire.
    nascosti = len(conflitti) - _MAX_AVVISI_AMBIGUITA
    if nascosti > 0:
        conflitti = conflitti[:_MAX_AVVISI_AMBIGUITA]
        conflitti.append(
            f"...e altri {nascosti} conflitti di frase NON elencati (tetto di "
            f"{_MAX_AVVISI_AMBIGUITA} avvisi). Correggi quelli sopra e riavvia per vedere i "
            f"successivi.")
    return struttura + conflitti


def _canonical_market(market_name: str, selection_name: str, rows=None):
    """Risolve ``(market_name, selection_name)`` del config nella tupla **canonica** del
    Catalogo Betfair ``{market_type, market_name, selection_name}``, o ``None`` se la
    coppia non è valida.

    Validazione + canonicalizzazione safety-critical (design §5.3): il match col catalogo è
    case/spazio-insensitive (``dizionario.normalize``), ma ciò che si ritorna — e che il
    runtime scriverà nel CSV — sono **sempre i valori canonici del catalogo** (MarketType,
    MarketName, SelectionName), non quelli grezzi del config: così una config editata a
    mano con case/spazi diversi (o un ``market_type`` stantio) non produce mai una tupla che
    XTrader non riconosce. Mercato **fisso** + selezione **non dinamica** (Codex). ``rows``
    inietta un catalogo nei test; di default usa quello reale."""
    mn = str(market_name or "").strip()
    sn = str(selection_name or "").strip()
    if not mn or not sn:
        return None
    nmn = dizionario.normalize(mn)
    nsn = dizionario.normalize(sn)
    # P3-20 #76: guardia anti-ambiguità, leggendo i TIPI direttamente dalle voci del
    # catalogo (NON via `market_type_for_name`, che è first-match sui nomi normalizzati
    # e per due duplicati ritornerebbe lo stesso tipo, mascherando l'ambiguità). Oggi il
    # catalogo non ha MarketName duplicati; se in futuro due nomi normalizzati-uguali
    # finissero sotto MarketType DIVERSI, il primo-match sceglierebbe in silenzio un
    # mercato — e il CSV punterebbe un mercato potenzialmente sbagliato. Fail-closed:
    # con tipi divergenti nessuna risoluzione (meglio nessuna riga che quella sbagliata).
    matches = [m for m in dizionario.market_catalog(rows)
               if not m["dynamic"] and dizionario.normalize(m["MarketName"]) == nmn]
    if not matches:
        return None
    tipi = {m["MarketType"] for m in matches}
    if len(tipi) > 1:
        _LOG.warning(
            "market_mappings: MarketName %r AMBIGUO nel catalogo (%d voci, MarketType "
            "divergenti %s) -> risoluzione RIFIUTATA (fail-closed, P3-20 #76).",
            mn, len(matches), sorted(tipi))
        return None
    canon_market = matches[0]["MarketName"]
    ncanon = dizionario.normalize(canon_market)
    for s in dizionario.selections_for_market(canon_market, rows):
        if s.get("dynamic") or not s.get("SelectionName"):
            continue
        # La selezione deve appartenere DAVVERO a questo mercato (B20 #194, audit #192 L16).
        # `selections_for_market` combacia su `MarketType` **oppure** `MarketName` — utile per
        # le tendine della GUI, pericoloso qui: se il `MarketName` risolto coincide col
        # `MarketType` di un'ALTRA riga, la selezione arriva da quella riga e si accoppia col
        # `market_type` di questa. Misurato su un catalogo sporco, prima della correzione:
        #
        #   {'market_type': 'MATCH_ODDS', 'market_name': 'Vincente',
        #    'selection_name': 'Selezione di UN ALTRO mercato'}
        #
        # cioè una coppia mercato/selezione che nel dizionario **non esiste**, scritta nel CSV
        # come se esistesse. Il catalogo spedito è pulito (22 tipi / 81 righe, 0 collisioni),
        # quindi qui non cambia nulla: chiude il caso del dizionario esteso o editato a mano.
        if dizionario.normalize(s.get("MarketName", "")) != ncanon:
            continue
        if dizionario.normalize(s["SelectionName"]) == nsn:
            mtype = dizionario.market_type_for_name(canon_market, rows) or ""
            return {"market_type": mtype, "market_name": canon_market,
                    "selection_name": s["SelectionName"]}
    return None


# Tetto della cache dei pattern compilati (#256). Sopra qualunque dizionario realistico —
# il caso peggiore misurato allo START era 300 voci per profilo — ma limitato, perché le
# frasi arrivano dal config dell'utente e una cache illimitata su input utente è una perdita
# di memoria lenta. Oltre il tetto `lru_cache` sfratta le voci meno usate: si torna a
# ricompilare quelle, esattamente come prima della patch, senza mai sbagliare risposta.
_MAX_PATTERN_CACHE = 4096


@lru_cache(maxsize=_MAX_PATTERN_CACHE)
def _phrase_pattern(p_norm: str):
    """Pattern compilato per la frase **già normalizzata** ``p_norm``, con cache di modulo.

    Il pattern dipende SOLO dalla frase, quindi è cacheabile senza rischi: due chiamate con
    la stessa frase normalizzata devono produrre lo stesso identico confronto. La chiave è la
    frase **normalizzata** e non quella grezza perché «GG», «gg» e «  gg  » sono la stessa
    frase per il matching — indicizzare sul grezzo moltiplicherebbe le voci e riaprirebbe il
    thrashing che questa cache chiude.

    Perché serve (#256): `re` tiene una cache interna di ~512 pattern; oltre quella soglia
    ogni chiamata ricompilava. Misurato sul percorso live, per messaggio:

        100 frasi 0,73 ms · 400 frasi 2,98 ms · **600 frasi 54 ms** · 1200 frasi 108 ms

    Il tetto `_MAX_VOCI_CONTROLLO_AMBIGUITA` protegge solo la diagnostica allo START; il
    runtime non ha tetto e non può averne uno (non si può rifiutare di risolvere un mercato
    perché il dizionario è grande).
    """
    # Confine: niente \w/-/ ai bordi; il separatore ,/. conta come confine SOLO se punteggiatura
    # (a sinistra: non preceduto da `cifra+separatore`; a destra: non seguìto da `separatore+cifra`).
    return re.compile(r"(?<![\w/-])(?<!\d[.,])" + re.escape(p_norm) + r"(?![\w/-])(?![.,]\d)")


def _phrase_in_text(phrase: str, text_norm: str) -> bool:
    """``True`` se ``phrase`` compare in ``text_norm`` (già normalizzato) come
    sottostringa su **confini di token**. I lookaround escludono dai confini i caratteri
    di parola (``\\w``), ``/`` e ``-``, **e** il separatore decimale ``,``/``.`` SOLO quando è
    davvero un decimale — cioè seguìto (a destra) o preceduto (a sinistra) da una **cifra**:

    - "over" non combacia dentro "overflow" (``\\w``); "x" non combacia dentro "1/x"/"1-x" (``/``/``-``);
    - **P1 percorso soldi**: una frase che finisce con un intero non combacia dentro una linea
      **decimale** diversa — "over 2" NON matcha in "over 2,75"/"over 2.75", e "5 HT" NON matcha in
      "1,5 HT" (senza questo, una linea non mappata risolveva al mercato di una voce più corta =
      scommessa sul mercato SBAGLIATO);
    - ma il ``,``/``.`` come **punteggiatura** (non seguìto da cifra) resta un confine valido:
      "over 2" combacia ancora in "over 2." / "over 2," e "gol gol" in "gol gol." (review GPT-5.5:
      non rompere i messaggi reali con punteggiatura finale). Una cifra dopo la frase era già
      esclusa da ``\\w`` (es. "over 0,5" non matcha "over 0,55").

    Il pattern è compilato una volta per frase e tenuto in cache (`_phrase_pattern`, #256):
    il **confronto è identico**, cambia solo quante volte lo si compila."""
    p = _normalize_text(phrase)
    if not p:
        return False
    return _phrase_pattern(p).search(text_norm) is not None


def resolve_market(text: str, profiles, rows=None, language=None) -> MarketResolution:
    """Risolve il mercato canonico XTrader dal mercato scritto dal provider nel ``text``.

    Per ogni voce il mercato si legge **da una posizione precisa** del messaggio: si estrae
    il testo tra i delimitatori ``start_after``/``end_before`` (stesso motore del Parser,
    ``extract_between``) e si verifica che il **testo mercato** (``phrase``) compaia in
    quel campo estratto (case-insensitive, a confini di token). Così un banner/menu altrove
    nel messaggio non crea falsi match (es. ``30/0,5HT/1,5HT/1`` non viene letto se il
    mercato vero sta tra «Quota» e «Prematch»). La coppia Mercato/Selezione dev'essere
    **coerente col Catalogo Betfair** (``_canonical_market``, §5.3): una voce incoerente
    (config a mano/bug) è ignorata, mai scritta. ``rows`` inietta un catalogo nei test.

    ``language`` (epica #3 slice 5c): lingua-fonte effettiva (``IT``/``EN``/``ES`` o
    ``None``/``""`` = nessun filtro = comportamento storico). Se valorizzata: le voci di
    un'ALTRA lingua vengono **scartate** (le agnostiche restano) e la voce della lingua
    ESATTA ha **priorità** sull'agnostica (tier), come il dizionario nomi (5b). Un dizionario
    tutto-agnostico continua a risolvere anche con la lingua-fonte impostata (retro-compat).
    Poi (D2):

    - 0 match → ``MarketResolution("none", None)``;
    - match che indicano **lo stesso** ``(market_type, market_name, selection_name)``
      → ``MarketResolution("ok", {...})``;
    - match che indicano mercati **diversi** → ``MarketResolution("ambiguous", None)``
      (fail-closed: il chiamante non scrive nulla, niente mercato a caso).
    """
    if not str(text or "").strip():
        return MarketResolution("none", None)
    wl = recognition.normalize_source_language(language)   # "" = nessun filtro-lingua (legacy)
    found = []                                             # (canon_tuple, entry_language)
    for entries in (profiles or []):
        for e in entries:
            sa = str(e.get("start_after", "") or "")
            eb = str(e.get("end_before", "") or "")
            ph = str(e.get("phrase", "") or "").strip()
            # Difesa ANCHE sul percorso runtime (i profili possono arrivare grezzi, non solo
            # ripuliti da _clean_entry): una voce senza testo mercato o senza alcun
            # delimitatore è ignorata qui (non applicata, fail-closed), così non può MAI
            # combaciare su tutto il messaggio (Sourcery/CodeRabbit). "Vuoto" = solo spazi/tab
            # ai bordi, come `_delim_pattern`: un delimitatore di soli newline conta.
            if not ph or (not sa.strip(" \t") and not eb.strip(" \t")):
                continue
            # Filtro-lingua (epica #3 slice 5c): con una lingua-fonte richiesta, una voce di
            # un'ALTRA lingua esatta è scartata (mai applicare un mercato di lingua sbagliata).
            # Le agnostiche (`""`) restano eleggibili. Senza filtro (`wl` vuoto) nessuno scarto
            # → comportamento storico invariato.
            el = str(e.get("language", "") or "")
            if wl and el and el != wl:
                continue
            # Leggi il mercato SOLO dalla posizione delimitata (niente scansione dell'intero
            # messaggio): i delimitatori RAW vanno a extract_between, che preserva i newline
            # (ancoraggio a inizio riga, Codex); poi il testo mercato si confronta sul campo
            # normalizzato. I delimitatori sono case-sensitive come nel Parser.
            region = extract_between(text, sa, eb)
            if not region:
                continue
            if not _phrase_in_text(e.get("phrase", ""), _normalize_text(region)):
                continue
            # Risolvi nella tupla CANONICA del catalogo (type+nomi esatti, ignorando i
            # valori grezzi del config): una coppia incoerente → None → IGNORATA, mai
            # scritta; una coppia valida ma non-canonica (case/spazi) → valori canonici,
            # così XTrader riconosce sempre la tupla (design §5.3, Codex).
            canon = _canonical_market(e.get("market_name", ""), e.get("selection_name", ""), rows)
            if canon is None:
                continue
            found.append(((canon["market_type"], canon["market_name"],
                           canon["selection_name"]), el))
    if not found:
        return MarketResolution("none", None)
    # Tier lingua (epica #3 slice 5c): se è richiesta una lingua-fonte e c'è almeno un match
    # della lingua ESATTA, si usano SOLO quelli — un match agnostico non deve creare una falsa
    # ambiguità contro la voce della lingua giusta (mirror del tier del dizionario nomi). Senza
    # filtro (`wl` vuoto) il set resta invariato → ambiguità/risultato identici al legacy.
    if wl and any(el == wl for _, el in found):
        found = [(canon, el) for canon, el in found if el == wl]
    canon_set = {canon for canon, _ in found}
    if len(canon_set) > 1:
        return MarketResolution("ambiguous", None)
    mt, mn, sn = next(iter(canon_set))
    return MarketResolution("ok", {"market_type": mt, "market_name": mn,
                                   "selection_name": sn})
