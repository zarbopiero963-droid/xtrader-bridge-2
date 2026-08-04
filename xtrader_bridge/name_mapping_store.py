"""Dizionario di mappatura nomi squadra: alias del provider → nome Betfair/XTrader.

Un *provider* (canale Telegram) può scrivere le squadre con nomi diversi da quelli
che XTrader/Betfair si aspettano nell'``EventName`` (es. "Liverpool" vs "Liverpool",
"Inter" vs "Internazionale", abbreviazioni, lingue diverse). Questo modulo tiene
**profili di mappatura** definiti dall'utente e li applica all'``EventName`` prima
della scrittura, così l'evento combacia col name-matching di XTrader.

Modello dati (config, chiave ``name_mappings``)::

    cfg["name_mappings"] = {
        "<nome profilo>": [
            {"country": "Inghilterra", "betfair": "Liverpool", "provider": "Liverpool FC",
             "sport": "Calcio", "entity_type": "team", "language": "EN"},
            ...
        ],
        ...
    }

Entrambe le colonne sono **campo libero** (le riempie l'utente): ``betfair`` è il
nome canonico XTrader/Betfair (anche l'output della mappatura), ``provider`` è
l'alias usato nei messaggi del canale. ``country`` è solo organizzativo (opz.).
``sport`` (PR-P10), ``entity_type`` (PR-P10 / #178 §2) e ``language`` (epica #3
slice 5b: lingua della fonte, ``IT``/``EN``/``ES``) sono filtri opzionali per riga:
vuoti = agnostici, così le config salvate prima di questi campi restano valide. Il
filtro-lingua è ATTIVO solo quando il chiamante passa una ``language`` a
`resolve_team`/`resolve_event_name` (consumo cablato nella pipeline in una slice
successiva); con ``language=None`` (default) il comportamento è quello storico.

Logica PURA su un ``dict`` di config: nessuna GUI, nessun I/O — la persistenza è
del chiamante (``config_store.save_config``), come per ``provider_store``. Le
funzioni di modifica ritornano una COPIA della config, non mutano l'originale.

Regole di sicurezza (safety-critical: un evento sbagliato = scommessa sbagliata):
- lookup **normalizzato** (case/spazi-insensibile), come il dizionario XTrader;
- **fail-closed**: un nome non risolvibile NON viene tradotto a caso → il chiamante
  ottiene ``None`` e scarta il segnale (nessuna riga CSV);
- multi-profilo: i profili selezionati si applicano nell'ordine dato e vince la
  **prima** corrispondenza (deterministico in caso di conflitto fra profili).
"""

import re

import hashlib
import logging
import threading

from . import mapping_store_base, recognition, sports
from .dizionario import compose_event_name, normalize

_LOG = logging.getLogger(__name__)

# Coppie (campo, valore) già segnalate a log: il resolver gira in hot path
# (una risoluzione per messaggio) e una riga malformata non deve riempire il log con
# lo stesso warning a ogni evento (stesso pattern anti-flooding di `source_manager`).
_WARNED_MALFORMED = set()
_WARNED_CAP = 256
# P3-19 #76: check-and-add sotto lock come in `source_manager._WARNED_LOCK` — il
# resolver può girare dal thread del bot mentre la GUI valida dal thread Tk.
_WARNED_LOCK = threading.Lock()


def _reset_warnings() -> None:
    """Svuota il dedup dei warning (per i test)."""
    with _WARNED_LOCK:
        _WARNED_MALFORMED.clear()


def _warn_malformed(field: str, value) -> None:
    """Segnala UNA volta (per campo+valore) una riga di mappatura scartata perché
    `sport`/`entity_type` non è riconosciuto (fail-closed, audit #259 B4)."""
    shown = ascii(value)
    # P3-19 #76: la chiave di dedup usa il valore INTERO, non quello troncato per il
    # display — due valori lunghi distinti con lo stesso prefisso di 57 char non
    # devono più collassare in un solo warning (il secondo sparirebbe dal log).
    # Follow-up #76 (nota PR #104): digest sha256 al posto di `hash()` — stessa
    # memoria fissa, ma niente collisioni pratiche che sopprimerebbero il warning
    # di un valore DIVERSO (pattern allineato con `source_manager`).
    key = (field, hashlib.sha256(shown.encode("utf-8", "backslashreplace")).hexdigest())
    if len(shown) > 60:
        shown = shown[:57] + "..."
    with _WARNED_LOCK:
        if key in _WARNED_MALFORMED or len(_WARNED_MALFORMED) >= _WARNED_CAP:
            return
        _WARNED_MALFORMED.add(key)
    _LOG.warning(
        "name_mappings: %s=%s non riconosciuto -> riga di mappatura IGNORATA "
        "(fail-closed, #259 B4): correggi il valore per riattivarla.", field, shown)

# Chiave di config che ospita i profili di mappatura.
_STORE_KEY = "name_mappings"

# Tassonomia del tipo di entità mappata (issue #86 PR-P10 / #178 §2). Una riga può
# dichiarare COSA mappa, così un alias di "competition" non scavalca un nome squadra e
# si possono esprimere anche player/competition (non solo team/event). "" = agnostico
# (vale per ogni tipo), retro-compatibile con le righe salvate prima di questo campo.
ENTITY_TYPES = ("participant", "team", "player", "competition", "market", "selection")

# Tipi "partecipante" usati per risolvere un nome di squadra/giocatore nell'EventName.
# Il flusso live (custom_pipeline) restringe la mappatura dell'EventName a QUESTI tipi (più
# le righe agnostiche), così una riga di tipo competition/market/selection con un alias
# che collide NON traduce un partecipante dell'evento (issue #178 §2, Codex P1).
PARTICIPANT_ENTITY_TYPES = ("participant", "team", "player")


def normalize_entity_type(value) -> str:
    """Normalizza un tipo di entità a uno di ``ENTITY_TYPES`` (case-insensitive) oppure
    ``""`` (agnostico) se vuoto/ignoto. Fail-safe: un valore non riconosciuto NON sceglie
    un tipo a caso, diventa agnostico."""
    v = str(value or "").strip().casefold()
    return v if v in ENTITY_TYPES else ""


def _entity_filter(want_entity):
    """Normalizza ``want_entity`` (str, iterabile di str, o falsy) nell'insieme dei tipi
    AMMESSI (frozenset) oppure ``None`` = nessun filtro. I valori ignoti sono scartati;
    un insieme che si svuota → ``None`` (nessun filtro, non un filtro che blocca tutto)."""
    if not want_entity:
        return None
    if isinstance(want_entity, str):
        v = normalize_entity_type(want_entity)
        return frozenset({v}) if v else None
    allowed = {normalize_entity_type(x) for x in want_entity}
    allowed.discard("")
    return frozenset(allowed) if allowed else None


def _malformed_fields(entry: dict) -> list:
    """Coppie ``(campo, valore_grezzo)`` NON riconosciute di una riga di mappatura:
    ``sport`` non in ``sports.SPORTS`` o ``entity_type`` non in ``ENTITY_TYPES``
    (vuoto = agnostico intenzionale, NON malformato). Predicato unico (audit #259 B4)
    condiviso tra `_clean_entry` (scarto fail-closed + log) e
    `malformed_entry_warnings` (avvisi GUI), così i due non possono divergere."""
    out = []
    raw_sport = str(entry.get("sport", "") or "").strip()
    if raw_sport and not sports.normalize_sport(raw_sport):
        out.append(("sport", raw_sport))
    raw_entity = str(entry.get("entity_type", "") or "").strip()
    if raw_entity and not normalize_entity_type(raw_entity):
        out.append(("entity_type", raw_entity))
    # language (epica #3 slice 5b): non-vuoto ma non IT/EN/ES → FAIL-CLOSED come sport/entity_type
    # (un typo di lingua non deve allargare in silenzio la riga a "tutte le lingue"). Vuoto = agnostico.
    raw_language = str(entry.get("language", "") or "").strip()
    if raw_language and not recognition.normalize_source_language(raw_language):
        out.append(("language", raw_language))
    return out


def _clean_entry(entry) -> dict:
    """Normalizza una riga di mappatura in
    ``{country, betfair, provider, sport, entity_type, language}`` (stringhe ripulite),
    oppure ``None`` se la riga è vuota/non valida. Una riga senza né ``betfair`` né
    ``provider`` è inutile (non mappa nulla) e viene scartata.

    ``language`` (epica #3 slice 5b): lingua della fonte (``IT``/``EN``/``ES``); **vuoto**
    → ``""`` = agnostico (retro-compatibile con le righe salvate prima). Un valore non-vuoto
    ma **non riconosciuto** è FAIL-CLOSED come ``sport``/``entity_type`` (riga scartata, non
    allargata a tutte le lingue).

    ``sport`` (PR-P10) restringe la riga a uno sport (``sports.SPORTS``); **vuoto** →
    ``""`` = **agnostico** (vale per tutti gli sport, retro-compatibile con le righe
    salvate prima di P10). ``entity_type`` (PR-P10 / #178 §2) restringe la riga a un tipo
    di entità (``ENTITY_TYPES``); **vuoto** → ``""`` = agnostico.

    Un valore NON vuoto ma **non riconosciuto** (typo: ``"Calc1o"``) è invece FAIL-CLOSED
    (audit #259 B4, decisione proprietario): la riga viene **scartata** con warning, NON
    allargata ad agnostica — un typo non deve far applicare una mappatura pensata per uno
    sport/tipo a tutti gli altri (EventName sbagliato nel CSV). Le righe agnostiche
    INTENZIONALI (campo vuoto) restano valide e agnostiche."""
    if not isinstance(entry, dict):
        return None
    country = str(entry.get("country", "") or "").strip()
    betfair = str(entry.get("betfair", "") or "").strip()
    provider = str(entry.get("provider", "") or "").strip()
    if not betfair and not provider:
        return None
    bad = _malformed_fields(entry)
    if bad:
        for field, raw in bad:
            _warn_malformed(field, raw)
        return None
    return {"country": country, "betfair": betfair, "provider": provider,
            "sport": sports.normalize_sport(entry.get("sport")) or "",
            "entity_type": normalize_entity_type(entry.get("entity_type")),
            "language": recognition.normalize_source_language(entry.get("language"))}


# CRUD condiviso (store refactor #114): le dieci funzioni identiche fra i due store vivono in
# `mapping_store_base`; qui si iniettano le TRE differenze dello store nomi — la chiave di config,
# il proprio `_clean_entry` (schema nomi) e il prefisso di log dei profili duplicati — e si legano
# le funzioni al modulo con le firme storiche. `_store`/`_norm_profile_name`/`_find_store_key`
# restano accessibili (li usano i resolver e i test) puntando all'implementazione condivisa.
_crud = mapping_store_base.make_profile_crud(
    store_key=_STORE_KEY, clean_entry=_clean_entry, dup_warn_prefix="name_mappings", logger=_LOG)
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
    """Avvisi **non bloccanti** per la GUI/event log (audit #259 B4): righe di
    mappatura con ``sport``/``entity_type`` non riconosciuto, che il resolver SCARTA
    (fail-closed). Il warning del logger Python di `_clean_entry` non è visibile
    nell'app windowed (stesso principio di `source_manager.malformed_enabled_warnings`,
    Codex P2 #309): `_start` mostra QUESTI messaggi nel log eventi, così l'operatore
    scopre subito la riga disattivata invece che dal nome non tradotto."""
    warnings = []
    for profile, rows in _store(cfg).items():
        if not isinstance(rows, (list, tuple)):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            betfair = str(entry.get("betfair", "") or "").strip()
            provider = str(entry.get("provider", "") or "").strip()
            if not betfair and not provider:
                continue                      # riga vuota: scartata comunque, senza avviso
            bad = _malformed_fields(entry)
            if bad:
                dove = ", ".join(f"{f}={v!r}" for f, v in bad)
                riga = betfair or provider
                warnings.append(
                    f"Mappatura nomi «{_norm_profile_name(profile)}», riga «{riga}»: "
                    f"{dove} non riconosciuto -> riga IGNORATA (fail-closed). "
                    f"Correggi il valore per riattivarla.")
    return warnings


def ambiguous_alias_warnings(cfg: dict) -> list:
    """Avvisi **non bloccanti** (audit #137): nomi che, dentro lo **stesso profilo** e a
    parità di firma di scoping, combaciano con ≥2 ``betfair`` DIVERSI. Su questi
    `resolve_team` fail-closa (ritorna ``None``, vedi `_resolve_in_tier`) e logga con
    `_LOG.warning` — che nell'app **windowed non è visibile**: l'operatore vede soltanto il
    segnale scartato per «nome non tradotto», senza alcun indizio sul perché. Stesso
    principio di `malformed_entry_warnings`: `_start` porta questi messaggi nel log eventi,
    così il conflitto si scopre **al load** invece che a segnale già perso.

    **Riusa le funzioni del runtime, e non è un dettaglio.** Le righe arrivano da
    `get_entries` (già passate da `_clean_entry`, esattamente come le riceve il resolver), il
    nome è confrontato con `normalize` e il raggruppamento usa `_scope_signature`: sono le
    tre cose su cui `_resolve_in_tier` decide l'ambiguità. Una detection scritta a parte
    divergerebbe — e un avviso che diverge è peggio di nessun avviso, perché o tace su un
    conflitto vivo o accusa una configurazione sana.

    In particolare **non** si leggono le righe grezze da `_store` (come fa invece
    `malformed_entry_warnings`, che deve proprio segnalare i valori non riconosciuti): senza
    `_clean_entry`, ``sport="Calcio"`` e ``sport="calcio"`` darebbero due firme diverse e
    l'ambiguità sfuggirebbe per una differenza puramente cosmetica.
    """
    warnings = []
    for profile in profile_names(cfg):
        # (fase, nome normalizzato, firma di scoping) → destinazioni Betfair distinte.
        # `dict` preserva l'ordine d'inserimento: l'ordine degli avvisi è deterministico,
        # un log eventi che si rimescola a ogni avvio non si legge.
        conflitti = {}
        righe = get_entries(cfg, profile)       # una sola lettura+pulizia per profilo: le due
                                                # fasi scorrono le STESSE righe (GPT-5.5/Fable)
        for key in ("provider", "betfair"):    # alias e canonico: le due fasi del resolver
            for e in righe:
                # Stesso guard di `_resolve_in_tier`: una riga senza `key` o senza `betfair`
                # non combacia MAI in quella fase, quindi non può essere ambigua.
                if not e.get(key, "") or not e.get("betfair", ""):
                    continue
                nt = normalize(e.get(key, ""))
                if not nt:
                    continue
                voce = conflitti.setdefault(
                    (key, nt), {"nome": str(e.get(key, "")).strip(), "betfair": []})
                if e["betfair"] not in voce["betfair"]:
                    voce["betfair"].append(e["betfair"])
        chiamanti = _chiamanti_plausibili(righe)
        # Le righe indicizzate per nome normalizzato (alias E canonico). Senza questo, sondare
        # ogni chiamante per ogni nome in conflitto significa rieseguire `_resolve_scoped`
        # sull'INTERO profilo: misurato su un dizionario worst-case realistico (2000 righe,
        # tutti gli sport/tipi/lingue, 200 alias in conflitto → 168 chiamanti) il costo era di
        # **48,7 secondi**, e questa funzione gira allo START: l'app si sarebbe piantata per
        # quasi un minuto (rischio sollevato da GPT-5.5 sulla #253 e confermato misurando).
        #
        # È equivalente, non un'approssimazione: una riga il cui nome non combacia con `nt` non
        # produce mai un hit in `_resolve_in_tier` e non concorre mai all'ambiguità, e toglierla
        # non altera né il rango né l'ordine delle righe che restano — quindi i gruppi di
        # `_scoped_entry_groups` sono esattamente il sottoinsieme combaciante di quelli pieni.
        # L'equivalenza è verificata su 26.235 dizionari dal test esaustivo.
        per_nome = {}
        for e in righe:
            # `dict.fromkeys` deduplica i due nomi: se alias e canonico normalizzano uguale, la
            # riga va inserita UNA volta sola, altrimenti comparirebbe due volte nel gruppo e
            # falserebbe il conteggio delle destinazioni.
            for n in dict.fromkeys(normalize(e.get(k, "")) for k in ("provider", "betfair")):
                if n:
                    per_nome.setdefault(n, []).append(e)
        for (key, _nt), voce in conflitti.items():
            if len(voce["betfair"]) < 2:
                continue                       # una sola destinazione = nessun conflitto
            # L'avviso NON ricalcola l'ambiguità: la CHIEDE al runtime, con la STESSA funzione
            # (`_resolve_scoped`) e per OGNI chiamante plausibile (B21 #194). Le due stesure
            # precedenti sbagliavano proprio qui, e i due difetti sono stati trovati in review
            # sulla #253 da Fable 5 e Fugu Ultra indipendentemente: sondare il solo chiamante
            # agnostico taceva su un conflitto interno a uno sport con ripiego agnostico
            # (parser che dichiara lo sport → ogni segnale perso, nessun ⚠️), e passare le
            # righe PIATTE ignorava i tier di `_scoped_entry_groups`, quindi poteva accusare
            # una config che il runtime risolve.
            nt = normalize(voce["nome"])
            candidate = per_nome.get(nt, [])
            ambigui = [c for c in chiamanti
                       if _resolve_scoped(nt, [candidate], *c) is _AMBIGUOUS]
            if not ambigui:
                continue
            fase = "alias" if key == "provider" else "nome canonico"
            dove = ", ".join(f"«{b}»" for b in voce["betfair"])
            # Due diagnosi diverse, perché richiedono due azioni diverse dall'utente. Se
            # fail-closa anche un chiamante che FILTRA, il conflitto è dentro uno scope e
            # nessun parser può schivarlo: va corretto il dizionario. Se fail-closa solo
            # l'agnostico, le righe sono distinguibili e basta dichiarare lo scope.
            # Confronto come INSIEME, non come lista: `chiamanti` è un set, quindi l'ordine di
            # `ambigui` non è definito. Oggi la lista a un elemento rende il confronto corretto
            # per caso; scritto così lo è per costruzione (rilievo GPT-5.5 sulla #253).
            solo_agnostico = set(ambigui) == {("", None, "")}
            if solo_agnostico:
                warnings.append(
                    f"Mappatura nomi «{_norm_profile_name(profile)}», {fase} «{voce['nome']}»: "
                    f"punta a {len(voce['betfair'])} nomi Betfair diversi ({dove}), distinguibili "
                    f"SOLO da uno sport/tipo/lingua -> un parser che non li specifica NON traduce "
                    f"il nome (fail-closed). Va bene se i tuoi parser dichiarano lo scope; "
                    f"altrimenti lascia una riga agnostica come ripiego.")
            else:
                warnings.append(
                    f"Mappatura nomi «{_norm_profile_name(profile)}», {fase} «{voce['nome']}»: "
                    f"punta a {len(voce['betfair'])} nomi Betfair diversi ({dove}) con lo stesso "
                    f"scope -> il nome NON viene tradotto (fail-closed). Correggi il Dizionario "
                    f"nomi, oppure distingui le righe per sport/tipo/lingua.")
    return warnings


def _chiamanti_plausibili(righe) -> set:
    """Gli scope ``(sport, entity_type, language)`` per cui un parser dell'utente può
    interrogare **queste** righe: il **prodotto cartesiano** dei valori presenti su ciascuna
    dimensione, più il vuoto (= non filtrata) su ognuna.

    Il prodotto non è pignoleria (rilievo Fable 5 sulla #253). La stesura precedente provava
    le tuple **per riga** più l'agnostico, e mancava le combinazioni che nessuna singola riga
    esibisce. Una ricerca esaustiva su 26.235 dizionari di 2–3 righe ha trovato **528 casi** in
    cui il runtime fail-closava per ambiguità senza che l'avviso dicesse nulla; il più semplice:

        righe:  (agnostica → A) · (team, IT → A) · (team, EN → B)
        scope che perde: (sport="", entity_type="team", language="")

    `("", "team", "")` non è la tupla di nessuna riga — entrambe le righe `team` hanno anche
    una lingua — ma è esattamente ciò che passa `custom_pipeline` con un parser senza sport e
    senza lingua-fonte, cioè il caso **più comune**. La stessa ricerca, col prodotto, dà **0
    buchi e 0 falsi positivi**.

    Dimensione: `(|sport|+1) × (|tipo|+1) × (|lingua|+1)` per profilo, coi valori presi dalle
    righe — tipi e lingue sono limitati dai rispettivi vocabolari, gli sport da quanti ne usa
    l'utente. Si valuta **una volta al load**, non per messaggio."""
    sport = {e.get("sport", "") or "" for e in righe} | {""}
    tipi = {e.get("entity_type", "") or "" for e in righe} | {""}
    lingue = {e.get("language", "") or "" for e in righe} | {""}
    return {(s, t or None, l) for s in sport for t in tipi for l in lingue}


def _entity_eligible(entry, allowed) -> bool:
    """Una riga è eleggibile se il suo ``entity_type`` è fra quelli ``allowed`` (insieme
    dei tipi richiesti) oppure se è **agnostica** (``entity_type`` vuoto, vale per ogni
    tipo). ``allowed`` ``None`` → nessun filtro (tutte eleggibili)."""
    if allowed is None:
        return True
    et = str(entry.get("entity_type", "") or "")
    return et in allowed or et == ""


def _scoped_entry_groups(entries, want_sport, want_entity=None, want_language=""):
    """Righe eleggibili per lo scope richiesto (sport + tipo di entità + lingua-fonte)
    **raggruppate per tier di priorità**, dal più specifico all'agnostico, dando priorità ai
    match esatti su TUTTE le dimensioni (PR-P10, CodeRabbit + Codex; ``language`` = #3 slice 5b).

    ``want_language`` (``IT``/``EN``/``ES`` o ``""``): se valorizzata si scartano le righe di
    un'ALTRA lingua (le agnostiche restano) e la riga della lingua ESATTA ha priorità
    sull'agnostica; vuota = nessun filtro-lingua (comportamento storico invariato).

    Ritorna una **lista di gruppi** (ogni gruppo = righe con lo stesso rango, nell'ordine
    salvato), coi gruppi ordinati dal tier più specifico a quello più agnostico:

    - si scartano le righe di un ALTRO ``entity_type`` (le agnostiche restano) e di un
      ALTRO sport (le agnostiche restano);
    - le rimanenti si raggruppano per rango: PRIMA il **tipo esatto** sull'agnostico, e a
      parità PRIMA lo sport esatto sull'agnostico; a parità di rango l'ordine salvato è
      preservato (sort stabile). ``want_sport``/``want_entity`` assenti → quella dimensione
      non influenza il rango.

    Il **tipo** è la dimensione PRIMARIA (Codex): un override tipizzato (`entity_type`
    valorizzato) vince anche su una riga legacy **sport-specifica ma senza tipo** salvata
    prima. Senza filtro tipo (`allowed is None`) il tipo non influenza il rango, quindi lo
    scoping per sport resta identico al comportamento legacy.

    Il chiamante (`resolve_team`) esaurisce un tier — **alias E canonico** — prima di
    scendere al successivo: così un alias **agnostico** non scavalca un canonico
    **esatto-sport** dello stesso nome (Codex P2 #174), e una riga agnostica salvata PRIMA
    non scavalca un override esatto salvato dopo (la GUI fa solo append). Senza alcun filtro
    c'è **un solo gruppo** nell'ordine salvato (comportamento legacy invariato)."""
    want = want_sport or ""
    wl = recognition.normalize_source_language(want_language)   # "" = nessun filtro-lingua
    allowed = _entity_filter(want_entity)
    pool = [e for e in entries
            if _entity_eligible(e, allowed)
            and (not want or str(e.get("sport", "") or "") in (want, ""))
            and (not wl or str(e.get("language", "") or "") in (wl, ""))]
    if not want and allowed is None and not wl:
        return [pool] if pool else []         # nessun filtro → un solo gruppo (ordine salvato, legacy)

    def _rank(e):
        entity_rank = 0 if (allowed is None
                            or str(e.get("entity_type", "") or "") in allowed) else 1
        # lingua (epica #3 slice 5b): riga della lingua ESATTA prima dell'agnostica; senza
        # filtro-lingua (`wl` vuoto) il rank è costante → ordinamento legacy invariato.
        lang_rank = 0 if (not wl or str(e.get("language", "") or "") == wl) else 1
        sport_rank = 0 if (not want or str(e.get("sport", "") or "") == want) else 1
        return (entity_rank, lang_rank, sport_rank)   # tipo PRIMARIO, poi lingua, poi sport

    groups = {}
    for e in sorted(pool, key=_rank):         # sort STABILE: ordine salvato a parità di rango
        groups.setdefault(_rank(e), []).append(e)
    return [groups[rank] for rank in sorted(groups)]   # tier dal più specifico all'agnostico


# Sentinella: un tier contiene un alias/canonico che combacia con ≥2 betfair DIVERSI (conflitto
# reale). Distinta da ``None`` (nessun match nel tier) così `resolve_team` fail-closa senza indovinare.
_AMBIGUOUS = object()


#: Le dimensioni di scoping, nell'ordine della firma. Fonte unica: `_scope_signature`
#: e `resolve_team` devono nominarle allo stesso modo, o la firma si disallinea in
#: silenzio dal filtro (B21 #194).
_SCOPE_DIMENSIONS = ("sport", "entity_type", "language")


def _scope_signature(e, dimensioni_filtrate=()):
    """Firma di scoping di una riga, limitata alle dimensioni su cui il chiamante **ha
    davvero filtrato**. Due righe con firma DIVERSA sono override distinguibili, non un
    conflitto; solo righe con firma UGUALE sono indistinguibili.

    Le righe arrivano già ripulite da `_clean_entry` (sport via `sports.normalize_sport`, tipo e
    lingua via i rispettivi normalizzatori), quindi due scope **equivalenti** scritti con casing o
    spazi diversi (``"Calcio"``/``"calcio"``) collassano allo STESSO valore → l'ambiguità fra
    Betfair diversi viene comunque rilevata, non sfugge per una differenza cosmetica.

    **`dimensioni_filtrate` (B21 #194, audit #192 L13).** Prima la firma includeva SEMPRE tutte e
    tre le dimensioni, e quindi dichiarava «distinguibili» due righe che il chiamante **non aveva
    alcun modo di distinguere**. Un parser sport-agnostico chiama `resolve_team` senza `sport`:
    con `Inter → Inter Milano` (Calcio) e `Inter → Inter Miami` (Basket) le firme risultavano
    diverse, la guardia anti-ambiguità non scattava, e vinceva la **prima riga salvata**.
    Misurato prima della correzione:

        ordine A -> 'Inter Milano'
        ordine B -> 'Inter Miami'      <- la squadra dipendeva dall'ordine di salvataggio

    Senza un avviso, e su un percorso vivo: quel nome finisce nell'`EventName`, quindi nel
    mercato e nella selezione su cui si scommette.

    La regola giusta è che **una dimensione distingue solo se il chiamante ha filtrato su di
    essa**: se non ha passato `sport`, lo sport non può separare due righe in conflitto, perché
    non è una scelta che qualcuno abbia fatto — è solo un dato che sta nel file. Le dimensioni
    non filtrate collassano fuori dalla firma, le righe tornano indistinguibili e la guardia
    esistente fa fail-closed, come già faceva a firma uguale."""
    return tuple(str(e.get(d, "") or "") for d in _SCOPE_DIMENSIONS
                 if d in dimensioni_filtrate)


def _resolve_in_tier(nt, group, key, dimensioni_filtrate=()):
    """Risolve una fase (``key``: ``"provider"`` = alias · ``"betfair"`` = canonico) dentro un
    tier (gruppo di righe dello stesso rango), preservando l'ordine salvato:

    - 0 righe combaciano con il nome normalizzato ``nt`` → ``None``;
    - righe che combaciano ma, **a parità di firma di scoping** (`_scope_signature`), indicano
      ≥2 ``betfair`` DIVERSI → ``_AMBIGUOUS`` (duplicato indistinguibile in conflitto → il
      chiamante fail-closa: mai indovinare la squadra, come il lato mercati con ``"ambiguous"``);
    - altrimenti → il ``betfair`` della **prima** riga che combacia (ordine salvato = precedenza
      legacy invariata). Righe con firma di scoping DIVERSA sono override distinguibili, non
      ambigue; duplicati verso lo **stesso** Betfair non sono ambigui.

    Il campo ``key`` DEVE essere non vuoto (guard legacy ``alias and betfair``): così una riga con
    ``provider=""`` non combacia mai nella fase alias e nessun nome squadra vuoto viene tradotto,
    a prescindere dal guard sul ``nt`` in `resolve_team` (fail-closed anche in isolamento)."""
    matches = [e for e in group
               if e.get(key, "") and e.get("betfair", "") and normalize(e.get(key, "")) == nt]
    if not matches:
        return None
    # Dimensioni su cui il chiamante NON ha filtrato: lì una riga AGNOSTICA è la risposta
    # naturale — è esattamente ciò per cui l'utente l'ha creata — mentre le righe che portano
    # un valore SPECIFICO sono override che a questa domanda non si applicano. Se esistono
    # righe agnostiche su tutte le dimensioni non filtrate si usano quelle (comportamento
    # legacy: «agnostica + override per-sport, chiamante senza sport → l'agnostica»).
    # Solo quando NON ce n'è nessuna restano in gioco righe tutte specifiche e non
    # distinguibili, ed è lì che vive B21: `Calcio → Inter Milano` contro
    # `Basket → Inter Miami` con chiamante agnostico non ha una risposta giusta, e prima
    # vinceva la prima salvata.
    non_filtrate = [d for d in _SCOPE_DIMENSIONS if d not in dimensioni_filtrate]
    if non_filtrate:
        agnostiche = [e for e in matches
                      if all(not str(e.get(d, "") or "") for d in non_filtrate)]
        if agnostiche:
            matches = agnostiche
    by_sig = {}
    for e in matches:
        by_sig.setdefault(_scope_signature(e, dimensioni_filtrate), set()).add(e.get("betfair", ""))
    if any(len(betfairs) > 1 for betfairs in by_sig.values()):
        return _AMBIGUOUS
    return matches[0].get("betfair", "")


def resolve_team(team: str, profiles, sport=None, entity_type=None, language=None) -> str:
    """Traduce un nome squadra grezzo nel nome Betfair/XTrader, o ``None`` se ignoto.

    ``profiles`` è una lista di liste-di-righe (vedi `entries_for_profiles`), nell'
    ordine di selezione. Strategia (deterministica, fail-closed): **il primo profilo
    vince**. Per ogni profilo, nell'ordine, si prova prima l'alias e poi il canonico,
    e solo se nessuno dei due combacia si passa al profilo successivo:

    1. **alias provider**: riga del profilo il cui ``provider`` combacia (normalizzato)
       → ritorna il suo ``betfair``;
    2. **nome canonico**: altrimenti riga del profilo il cui ``betfair`` combacia (il
       provider ha già mandato il nome canonico, o la riga non ha alias);
    3. nessun match in TUTTI i profili → ``None`` (non si indovina mai un nome squadra).

    **Fail-closed su alias ambiguo (audit #137):** se DENTRO uno stesso tier una fase (alias
    o canonico) combacia con ≥2 ``betfair`` DIVERSI (es. due righe dello stesso profilo con
    provider "Inter" → "Inter Milano" e "Inter" → "Inter Miami"), è un conflitto reale →
    ritorna ``None`` invece di indovinare la prima riga (allineato a
    `market_mapping_store.resolve_market`, che su frasi che indicano mercati diversi ritorna
    ``"ambiguous"``). Righe duplicate che puntano allo **stesso** Betfair NON sono ambigue.
    La precedenza **cross-profilo** (primo profilo vince), **tier** (sport/tipo/lingua esatti
    prima degli agnostici) e **alias-prima-di-canonico** resta invariata: l'ambiguità è solo
    fra righe dello stesso rango nella stessa fase.

    ``sport`` (PR-P10): se valorizzato (uno fra ``sports.SPORTS``), si considerano SOLO
    le righe di quello sport o **agnostiche** (sport vuoto), con **priorità allo sport
    esatto** sulle agnostiche (vedi `_scoped_entry_groups`): un override per-sport non
    viene mai scavalcato da una riga agnostica salvata prima. Le righe taggate per un altro
    sport sono saltate. Sport assente/ignoto → nessun filtro (comportamento legacy).

    ``entity_type`` (PR-P10 / #178 §2): un singolo tipo (``ENTITY_TYPES``) **oppure un
    insieme** di tipi ammessi (es. ``PARTICIPANT_ENTITY_TYPES``). Si considerano SOLO le
    righe di quei tipi o agnostiche, saltando quelle di un altro tipo (così l'alias di una
    "competition" non traduce un nome squadra), con **priorità al tipo esatto** sulle
    agnostiche. Assente/ignoto → nessun filtro. È additivo allo scoping per sport.

    ``language`` (epica #3 slice 5b): se valorizzata (``IT``/``EN``/``ES``, la lingua-fonte
    del palinsesto) si considerano SOLO le righe di quella lingua o **agnostiche** (lingua
    vuota), con **priorità alla lingua esatta** sull'agnostica. Le righe taggate per un'altra
    lingua sono saltate. Assente/vuota/ignota → nessun filtro (comportamento legacy). È
    additiva allo scoping per sport/tipo. Fail-closed invariato: nessun nome tradotto a caso.

    L'esaurire alias+canonico di un profilo prima del successivo evita che l'alias di
    un profilo più in basso scavalchi il canonico di uno più in alto (Codex)."""
    nt = normalize(team)
    if not nt:
        return None
    esito = _resolve_scoped(nt, profiles, sport, entity_type, language)
    if esito is _AMBIGUOUS:
        _LOG.warning(
            "name_mappings: alias ambiguo (≥2 Betfair diversi per lo stesso nome "
            "nello stesso profilo/tier) → fail-closed, nessuna traduzione. "
            "Correggi il Dizionario nomi.")
        return None
    return esito


def _dimensioni_filtrate(sport, entity_type, language) -> set:
    """Quali dimensioni di scope il chiamante ha **davvero** filtrato (B21 #194).

    Solo queste possono rendere «distinguibili» due righe in conflitto: una dimensione su cui
    non si è filtrato non è una scelta di nessuno, è solo un dato che sta nel file — e usarla
    per separare due righe significa risolvere in base all'ordine di salvataggio. Si usano i
    valori NORMALIZZATI (come i filtri stessi), così uno sport ignoto — che non filtra nulla —
    non conta come filtro attivo."""
    filtrate = set()
    if sports.normalize_sport(sport):
        filtrate.add("sport")
    if _entity_filter(entity_type) is not None:
        filtrate.add("entity_type")
    if recognition.normalize_source_language(language):
        filtrate.add("language")
    return filtrate


def _resolve_scoped(nt, profiles, sport, entity_type, language):
    """Il **cuore** della risoluzione: ritorna il nome Betfair, `_AMBIGUOUS`, oppure ``None``.

    Fonte unica (Regola 3). `resolve_team` ci aggiunge solo la normalizzazione del nome e il
    log; `ambiguous_alias_warnings` la interroga per sapere se un dato chiamante fail-closa.
    Prima l'avviso *simulava* il runtime passando le righe piatte a `_resolve_in_tier`, e le
    due detection potevano divergere in due modi, entrambi trovati in review sulla #253
    (Fable 5 e Fugu Ultra, indipendentemente):

    - **taceva su un conflitto vivo**: due righe in conflitto dentro `sport=Calcio` più una
      riga agnostica di ripiego: il sondaggio agnostico risolveva sull'agnostica, quindi
      nessun avviso — ma un parser che dichiara `Calcio` perdeva OGNI segnale, senza un ⚠️;
    - **ignorava i tier**: il runtime scorre i gruppi di `_scoped_entry_groups` dal più
      specifico all'agnostico e si ferma al primo esito; su righe piatte quella precedenza
      non esiste, quindi l'avviso poteva accusare una config che il runtime risolve.

    Chiamando la stessa funzione la divergenza non è «improbabile»: è impossibile."""
    filtrate = _dimensioni_filtrate(sport, entity_type, language)
    want = sports.normalize_sport(sport)
    for entries in profiles:
        # Si esaurisce un TIER di priorità (alias, poi canonico) PRIMA di scendere al tier
        # più agnostico: così un alias agnostico non scavalca un canonico esatto-sport dello
        # stesso nome (Codex P2 #174). Dentro il tier resta alias→canonico (l'alias del
        # provider ha precedenza sul nome canonico). Un alias/canonico ambiguo nel tier
        # (≥2 betfair diversi) fa fail-closed, non si indovina (audit #137).
        for group in _scoped_entry_groups(entries, want, entity_type, language):
            for key in ("provider", "betfair"):   # alias PRIMA del canonico (precedenza invariata)
                hit = _resolve_in_tier(nt, group, key, filtrate)
                if hit is _AMBIGUOUS:
                    return _AMBIGUOUS
                if hit is not None:
                    return hit
    return None


def split_event(event_name: str, separator: str, *, spaced_only: bool = False):
    """Divide un ``EventName`` ("Casa <sep> Trasferta") in ``(casa, trasferta)``,
    o ``None`` se non si riesce a separarlo in due nomi non vuoti.

    Il separatore è **testo libero** configurato dall'utente (es. "v", "vs", "-",
    "/"). Si preferisce **sempre** il delimitatore **con spazi attorno**
    (``\\s+<sep>\\s+``): così non si spezza su punteggiatura/lettere interne al nome
    (es. "Paris Saint-Germain - Lyon" → "Paris Saint-Germain" / "Lyon", non sulla
    prima "-"). Solo per separatori **simbolici** ("-"/"/"), se la forma con spazi non
    c'è, si ripiega sulla forma **compatta** (``\\s*<sep>\\s*``, es. "Liverpool/Leeds");
    per i separatori **alfabetici** ("v"/"vs") non c'è fallback compatto, altrimenti
    "v" senza spazi spezzerebbe "Liverpool". Solo la prima occorrenza separa
    (``maxsplit=1``).

    ``spaced_only`` (issue #38, guardia anti-split-errato): se ``True`` si accetta
    **solo** la forma spaziata (``\\s+<sep>\\s+``) anche per i separatori simbolici —
    **nessun fallback compatto**. Serve al percorso di riformattazione SENZA dizionario
    nomi: lì un separatore simbolico sbagliato (es. ``-`` su "Al-Kholood Club v Al-Hilal",
    dove non c'è alcun « - » spaziato) NON deve tagliare dentro un nome col trattino
    interno → meglio nessuno split (l'evento resta verbatim) che un evento sbagliato.
    Il default ``False`` preserva ESATTAMENTE il comportamento storico (ramo dizionario
    e tutti i chiamanti esistenti invariati)."""
    name = str(event_name or "").strip()
    sep = str(separator or "").strip()
    if not name or not sep:
        return None
    esc = re.escape(sep)
    parts = re.compile(r"\s+" + esc + r"\s+", re.IGNORECASE).split(name, maxsplit=1)
    if len(parts) != 2 and not sep.isalpha() and not spaced_only:
        parts = re.compile(r"\s*" + esc + r"\s*").split(name, maxsplit=1)
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    if not home or not away:
        return None
    return home, away


# Separatori che un messaggio può plausibilmente usare fra le due squadre, in ordine di
# preferenza. Ordine deliberato: gli ALFABETICI per primi perché sono i più comuni nei canali
# e sono i meno ambigui (` v ` non può comparire dentro un nome, un `-` sì). `vs` prima di `v`
# non serve per correttezza — le due forme spaziate si escludono a vicenda (`\s+v\s+` non
# combacia con «A vs B», e viceversa) — ma tiene l'ordine leggibile dal più specifico.
# NB: NON è una lista di separatori "supportati": il campo resta testo libero. Serve solo a
# SUGGERIRE, e per questo si prova con `split_event` invece di una regex nuova (fonte unica:
# ciò che si suggerisce è esattamente ciò che poi dividerebbe davvero — #182 PR A ⑨).
SEPARATORI_PLAUSIBILI = ("vs", "v", "-", "/")


def detect_separator(event_name: str):
    """Il separatore che ``event_name`` sembra usare fra le due squadre, o ``None``.

    Sola LETTURA, pura, nessun effetto: serve a rendere AZIONABILI gli avvisi del pannello
    Parser («il messaggio sembra usare « v »») invece di dire solo che qualcosa non ha
    funzionato (#182 PR A ⑨).

    Si prova ogni candidato con `split_event(..., spaced_only=True)`, cioè **la stessa
    funzione** che poi dividerebbe davvero, con la stessa guardia anti-split del percorso
    senza dizionario. Conseguenza voluta: non si può mai suggerire un separatore che, una
    volta scritto nel campo, non dividerebbe. `spaced_only=True` è la scelta prudente — un
    `-` interno a «Al-Kholood Club» non viene proposto come separatore.

    Ritorna il primo candidato che divide in due nomi non vuoti; ``None`` se nessuno lo fa
    (nome non divisibile, vuoto, o già in un formato che non usa separatori noti)."""
    nome = str(event_name or "").strip()
    if not nome:
        return None
    for candidato in SEPARATORI_PLAUSIBILI:
        if split_event(nome, candidato, spaced_only=True) is not None:
            return candidato
    return None


def resolve_event_name(event_name: str, separator: str, profiles, sport=None,
                       entity_type=None, language=None) -> str:
    """Traduce un ``EventName`` provider in ``EventName`` Betfair/XTrader, o ``None``.

    Divide su ``separator``, mappa casa e trasferta coi ``profiles`` e ricompone nel
    formato XTrader "Casa - Trasferta" (`dizionario.compose_event_name`). Ritorna
    ``None`` (fail-closed: niente riga CSV) se non si riesce a dividere **o** se una
    delle due squadre non è mappabile.

    ``sport`` (PR-P10), ``entity_type`` (#178 §2) e ``language`` (#3 slice 5b) sono inoltrati
    a `resolve_team` per restringere la mappatura alle righe di quello sport/tipo/lingua o
    agnostiche. Le squadre di un evento sono partecipanti: il chiamante può passare
    ``entity_type`` per usare solo le righe pertinenti (default ``None`` = nessun filtro,
    comportamento legacy)."""
    split = split_event(event_name, separator)
    if split is None:
        return None
    home, away = split
    h = resolve_team(home, profiles, sport=sport, entity_type=entity_type, language=language)
    a = resolve_team(away, profiles, sport=sport, entity_type=entity_type, language=language)
    if not h or not a:
        return None
    return compose_event_name(h, a)
