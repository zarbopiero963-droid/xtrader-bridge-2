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
             "sport": "Calcio", "entity_type": "team"},
            ...
        ],
        ...
    }

Entrambe le colonne sono **campo libero** (le riempie l'utente): ``betfair`` è il
nome canonico XTrader/Betfair (anche l'output della mappatura), ``provider`` è
l'alias usato nei messaggi del canale. ``country`` è solo organizzativo (opz.).
``sport`` (PR-P10) ed ``entity_type`` (PR-P10 / #178 §2) sono filtri opzionali per
riga (vedi `ENTITY_TYPES`): vuoti = agnostici, così le config salvate prima di questi
campi restano valide.

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

from . import sports
from .dizionario import compose_event_name, normalize

# Chiave di config che ospita i profili di mappatura.
_STORE_KEY = "name_mappings"

# Tassonomia del tipo di entità mappata (issue #86 PR-P10 / #178 §2). Una riga può
# dichiarare COSA mappa, così un alias di "competition" non scavalca un nome squadra e
# si possono esprimere anche player/competition (non solo team/event). "" = agnostico
# (vale per ogni tipo), retro-compatibile con le righe salvate prima di questo campo.
ENTITY_TYPES = ("participant", "team", "player", "competition", "market", "selection")


def normalize_entity_type(value) -> str:
    """Normalizza un tipo di entità a uno di ``ENTITY_TYPES`` (case-insensitive) oppure
    ``""`` (agnostico) se vuoto/ignoto. Fail-safe: un valore non riconosciuto NON sceglie
    un tipo a caso, diventa agnostico."""
    v = str(value or "").strip().casefold()
    return v if v in ENTITY_TYPES else ""


def _store(cfg: dict) -> dict:
    """Sezione ``name_mappings`` della config (dict vuoto se assente/malformata)."""
    raw = (cfg or {}).get(_STORE_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _norm_profile_name(name) -> str:
    """Nome profilo normalizzato per il confronto: stringa ripulita (strip)."""
    return str(name or "").strip()


def _find_store_key(store: dict, name: str):
    """Chiave REALE in ``store`` che corrisponde a ``name`` una volta normalizzata, o
    ``None``. Serve a ritrovare profili salvati con spazi attorno al nome (``config.json``
    legacy/editato a mano), che ``profile_names`` mostra già ripuliti: senza, lookup/CRUD
    mancherebbero il profilo o creerebbero un doppione, disabilitando in silenzio la
    mappatura nomi per quel profilo (audit L1, come ``market_mapping_store``). Compatibilità
    con vecchie config preservata."""
    target = _norm_profile_name(name)
    if not target:
        return None
    for k in store:
        if _norm_profile_name(k) == target:
            return k
    return None


def _clean_entry(entry) -> dict:
    """Normalizza una riga di mappatura in
    ``{country, betfair, provider, sport, entity_type}`` (stringhe ripulite), oppure
    ``None`` se la riga è vuota/non valida. Una riga senza né ``betfair`` né ``provider``
    è inutile (non mappa nulla) e viene scartata.

    ``sport`` (PR-P10) restringe la riga a uno sport (``sports.SPORTS``); vuoto/ignoto →
    ``""`` = **agnostico** (vale per tutti gli sport, retro-compatibile con le righe
    salvate prima di P10). ``entity_type`` (PR-P10 / #178 §2) restringe la riga a un tipo
    di entità (``ENTITY_TYPES``); vuoto/ignoto → ``""`` = agnostico. Entrambi sono filtri
    AGGIUNTIVI in `resolve_team`: non cambiano il comportamento delle righe agnostiche
    (file pre-esistenti restano validi e agnostici)."""
    if not isinstance(entry, dict):
        return None
    country = str(entry.get("country", "") or "").strip()
    betfair = str(entry.get("betfair", "") or "").strip()
    provider = str(entry.get("provider", "") or "").strip()
    if not betfair and not provider:
        return None
    sport = sports.normalize_sport(entry.get("sport")) or ""
    entity_type = normalize_entity_type(entry.get("entity_type"))
    return {"country": country, "betfair": betfair, "provider": provider,
            "sport": sport, "entity_type": entity_type}


def profile_names(cfg: dict) -> list:
    """Nomi dei profili di mappatura salvati, ordinati (case-insensitive). Per le
    tendine/checkbox della GUI."""
    names = [str(k).strip() for k in _store(cfg).keys() if str(k).strip()]
    return sorted(names, key=str.casefold)


def get_entries(cfg: dict, name: str) -> list:
    """Righe (ripulite) di un profilo, nell'ordine salvato. Profilo assente → ``[]``.
    Le righe vuote vengono filtrate, così il resolver non itera su rumore."""
    store = _store(cfg)
    key = _find_store_key(store, name)
    rows = store.get(key, []) if key is not None else []
    if not isinstance(rows, (list, tuple)):
        return []
    out = []
    for e in rows:
        ce = _clean_entry(e)
        if ce is not None:
            out.append(ce)
    return out


def entries_for_profiles(cfg: dict, names) -> list:
    """Lista di liste-di-righe per i profili indicati (ordine preservato): è la
    forma attesa da `resolve_team`/`resolve_event_name`. Un profilo mancante
    contribuisce con ``[]`` (nessun match da lì → fail-closed a valle)."""
    return [get_entries(cfg, n) for n in (names or []) if str(n or "").strip()]


def set_entries(cfg: dict, name: str, entries) -> dict:
    """Copia di ``cfg`` con il profilo ``name`` impostato/sostituito da ``entries``
    (ripulite). Nome vuoto → config invariata. Crea il profilo se non esiste."""
    out = dict(cfg or {})
    nm = _norm_profile_name(name)
    if not nm:
        return out
    store = dict(_store(out))
    existing = _find_store_key(store, nm)
    if existing is not None and existing != nm:
        store.pop(existing)   # migra una chiave legacy con spazi al nome normalizzato (no doppioni)
    store[nm] = [ce for ce in (_clean_entry(e) for e in (entries or [])) if ce is not None]
    out[_STORE_KEY] = store
    return out


def add_profile(cfg: dict, name: str) -> dict:
    """Copia di ``cfg`` con un profilo vuoto ``name`` (no-op se esiste già o nome
    vuoto): la creazione non deve mai cancellare le righe di un profilo omonimo."""
    out = dict(cfg or {})
    nm = _norm_profile_name(name)
    store = dict(_store(out))
    if nm and _find_store_key(store, nm) is None:
        store[nm] = []
    out[_STORE_KEY] = store
    return out


def delete_profile(cfg: dict, name: str) -> dict:
    """Copia di ``cfg`` senza il profilo ``name`` (idempotente)."""
    out = dict(cfg or {})
    nm = _norm_profile_name(name)
    store = {k: v for k, v in _store(out).items() if _norm_profile_name(k) != nm}
    out[_STORE_KEY] = store
    return out


def rename_profile(cfg: dict, old: str, new: str) -> dict:
    """Copia di ``cfg`` con il profilo ``old`` rinominato ``new`` (conserva le righe).
    No-op se ``old`` non esiste, ``new`` è vuoto, o ``new`` esiste già (non si
    sovrascrive in silenzio un altro profilo)."""
    out = dict(cfg or {})
    o = _norm_profile_name(old)
    n = _norm_profile_name(new)
    store = dict(_store(out))
    old_key = _find_store_key(store, o)
    new_key = _find_store_key(store, n)
    if o == n or old_key is None or not n or new_key is not None:
        return out
    store[n] = store.pop(old_key)
    out[_STORE_KEY] = store
    return out


def _entity_eligible(entry, want_entity) -> bool:
    """Una riga è eleggibile per il tipo di entità richiesto se ne combacia, oppure se è
    **agnostica** (``entity_type`` vuoto, vale per ogni tipo). ``want_entity`` falsy →
    nessun filtro (tutte eleggibili)."""
    if not want_entity:
        return True
    et = str(entry.get("entity_type", "") or "")
    return et == want_entity or et == ""


def _iter_entries_for_scope(entries, want_sport, want_entity=None):
    """Itera le righe eleggibili per lo scope richiesto (sport + tipo di entità), **dando
    priorità allo sport esatto** sulle righe agnostiche (PR-P10, CodeRabbit).

    - prima si scartano le righe di un ALTRO ``entity_type`` (le agnostiche restano);
    - poi, se ``want_sport`` è valorizzato → PRIMA le righe con ``sport == want_sport``
      (override per-sport), POI le righe agnostiche (``sport`` vuoto) come fallback; le
      righe taggate per un ALTRO sport sono escluse. ``want_sport`` falsy → ordine salvato.

    Così una riga agnostica salvata PRIMA non scavalca un override per-sport salvato dopo
    (la GUI fa solo append): l'override per-sport ha sempre la precedenza, e l'agnostica
    resta un fallback se non c'è un match esatto. Il filtro ``entity_type`` è additivo:
    senza ``want_entity`` il comportamento è identico al solo scoping per sport (legacy)."""
    pool = [e for e in entries if _entity_eligible(e, want_entity)]
    if not want_sport:
        yield from pool
        return
    for e in pool:
        if str(e.get("sport", "") or "") == want_sport:
            yield e
    for e in pool:
        if not str(e.get("sport", "") or ""):
            yield e


def resolve_team(team: str, profiles, sport=None, entity_type=None) -> str:
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

    ``sport`` (PR-P10): se valorizzato (uno fra ``sports.SPORTS``), si considerano SOLO
    le righe di quello sport o **agnostiche** (sport vuoto), con **priorità allo sport
    esatto** sulle agnostiche (vedi `_iter_entries_for_scope`): un override per-sport non
    viene mai scavalcato da una riga agnostica salvata prima. Le righe taggate per un altro
    sport sono saltate. Sport assente/ignoto → nessun filtro (comportamento legacy).

    ``entity_type`` (PR-P10 / #178 §2): se valorizzato (uno fra ``ENTITY_TYPES``), si
    considerano SOLO le righe di quel tipo o agnostiche, saltando quelle di un altro tipo
    (così l'alias di una "competition" non traduce un nome squadra). Assente/ignoto →
    nessun filtro. È additivo allo scoping per sport.

    L'esaurire alias+canonico di un profilo prima del successivo evita che l'alias di
    un profilo più in basso scavalchi il canonico di uno più in alto (Codex)."""
    nt = normalize(team)
    if not nt:
        return None
    want = sports.normalize_sport(sport)
    want_entity = normalize_entity_type(entity_type) if entity_type else None
    for entries in profiles:
        for e in _iter_entries_for_scope(entries, want, want_entity):
            alias = e.get("provider", "")
            betfair = e.get("betfair", "")
            if alias and betfair and normalize(alias) == nt:
                return betfair
        for e in _iter_entries_for_scope(entries, want, want_entity):
            betfair = e.get("betfair", "")
            if betfair and normalize(betfair) == nt:
                return betfair
    return None


def split_event(event_name: str, separator: str):
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
    (``maxsplit=1``)."""
    name = str(event_name or "").strip()
    sep = str(separator or "").strip()
    if not name or not sep:
        return None
    esc = re.escape(sep)
    parts = re.compile(r"\s+" + esc + r"\s+", re.IGNORECASE).split(name, maxsplit=1)
    if len(parts) != 2 and not sep.isalpha():
        parts = re.compile(r"\s*" + esc + r"\s*").split(name, maxsplit=1)
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    if not home or not away:
        return None
    return home, away


def resolve_event_name(event_name: str, separator: str, profiles, sport=None,
                       entity_type=None) -> str:
    """Traduce un ``EventName`` provider in ``EventName`` Betfair/XTrader, o ``None``.

    Divide su ``separator``, mappa casa e trasferta coi ``profiles`` e ricompone nel
    formato XTrader "Casa - Trasferta" (`dizionario.compose_event_name`). Ritorna
    ``None`` (fail-closed: niente riga CSV) se non si riesce a dividere **o** se una
    delle due squadre non è mappabile.

    ``sport`` (PR-P10) ed ``entity_type`` (#178 §2) sono inoltrati a `resolve_team` per
    restringere la mappatura alle righe di quello sport/tipo o agnostiche. Le squadre di un
    evento sono partecipanti: il chiamante può passare ``entity_type`` per usare solo le
    righe pertinenti (default ``None`` = nessun filtro, comportamento legacy)."""
    split = split_event(event_name, separator)
    if split is None:
        return None
    home, away = split
    h = resolve_team(home, profiles, sport=sport, entity_type=entity_type)
    a = resolve_team(away, profiles, sport=sport, entity_type=entity_type)
    if not h or not a:
        return None
    return compose_event_name(h, a)
