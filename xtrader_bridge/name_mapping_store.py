"""Dizionario di mappatura nomi squadra: alias del provider → nome Betfair/XTrader.

Un *provider* (canale Telegram) può scrivere le squadre con nomi diversi da quelli
che XTrader/Betfair si aspettano nell'``EventName`` (es. "Liverpool" vs "Liverpool",
"Inter" vs "Internazionale", abbreviazioni, lingue diverse). Questo modulo tiene
**profili di mappatura** definiti dall'utente e li applica all'``EventName`` prima
della scrittura, così l'evento combacia col name-matching di XTrader.

Modello dati (config, chiave ``name_mappings``)::

    cfg["name_mappings"] = {
        "<nome profilo>": [
            {"country": "Inghilterra", "betfair": "Liverpool", "provider": "Liverpool FC"},
            ...
        ],
        ...
    }

Entrambe le colonne sono **campo libero** (le riempie l'utente): ``betfair`` è il
nome canonico XTrader/Betfair (anche l'output della mappatura), ``provider`` è
l'alias usato nei messaggi del canale. ``country`` è solo organizzativo (opz.).

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

from .dizionario import compose_event_name, normalize

# Chiave di config che ospita i profili di mappatura.
_STORE_KEY = "name_mappings"


def _store(cfg: dict) -> dict:
    """Sezione ``name_mappings`` della config (dict vuoto se assente/malformata)."""
    raw = (cfg or {}).get(_STORE_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _clean_entry(entry) -> dict:
    """Normalizza una riga di mappatura in ``{country, betfair, provider}`` (stringhe
    ripulite), oppure ``None`` se la riga è vuota/non valida. Una riga senza né
    ``betfair`` né ``provider`` è inutile (non mappa nulla) e viene scartata."""
    if not isinstance(entry, dict):
        return None
    country = str(entry.get("country", "") or "").strip()
    betfair = str(entry.get("betfair", "") or "").strip()
    provider = str(entry.get("provider", "") or "").strip()
    if not betfair and not provider:
        return None
    return {"country": country, "betfair": betfair, "provider": provider}


def profile_names(cfg: dict) -> list:
    """Nomi dei profili di mappatura salvati, ordinati (case-insensitive). Per le
    tendine/checkbox della GUI."""
    names = [str(k).strip() for k in _store(cfg).keys() if str(k).strip()]
    return sorted(names, key=str.casefold)


def get_entries(cfg: dict, name: str) -> list:
    """Righe (ripulite) di un profilo, nell'ordine salvato. Profilo assente → ``[]``.
    Le righe vuote vengono filtrate, così il resolver non itera su rumore."""
    rows = _store(cfg).get(str(name), [])
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
    nm = str(name or "").strip()
    if not nm:
        return out
    store = dict(_store(out))
    store[nm] = [ce for ce in (_clean_entry(e) for e in (entries or [])) if ce is not None]
    out[_STORE_KEY] = store
    return out


def add_profile(cfg: dict, name: str) -> dict:
    """Copia di ``cfg`` con un profilo vuoto ``name`` (no-op se esiste già o nome
    vuoto): la creazione non deve mai cancellare le righe di un profilo omonimo."""
    out = dict(cfg or {})
    nm = str(name or "").strip()
    store = dict(_store(out))
    if nm and nm not in store:
        store[nm] = []
    out[_STORE_KEY] = store
    return out


def delete_profile(cfg: dict, name: str) -> dict:
    """Copia di ``cfg`` senza il profilo ``name`` (idempotente)."""
    out = dict(cfg or {})
    nm = str(name or "").strip()
    store = {k: v for k, v in _store(out).items() if str(k) != nm}
    out[_STORE_KEY] = store
    return out


def rename_profile(cfg: dict, old: str, new: str) -> dict:
    """Copia di ``cfg`` con il profilo ``old`` rinominato ``new`` (conserva le righe).
    No-op se ``old`` non esiste, ``new`` è vuoto, o ``new`` esiste già (non si
    sovrascrive in silenzio un altro profilo)."""
    out = dict(cfg or {})
    o = str(old or "").strip()
    n = str(new or "").strip()
    store = dict(_store(out))
    if o == n or o not in store or not n or n in store:
        return out
    store[n] = store.pop(o)
    out[_STORE_KEY] = store
    return out


def resolve_team(team: str, profiles) -> str:
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

    L'esaurire alias+canonico di un profilo prima del successivo evita che l'alias di
    un profilo più in basso scavalchi il canonico di uno più in alto (Codex)."""
    nt = normalize(team)
    if not nt:
        return None
    for entries in profiles:
        for e in entries:
            alias = e.get("provider", "")
            betfair = e.get("betfair", "")
            if alias and betfair and normalize(alias) == nt:
                return betfair
        for e in entries:
            betfair = e.get("betfair", "")
            if betfair and normalize(betfair) == nt:
                return betfair
    return None


def split_event(event_name: str, separator: str):
    """Divide un ``EventName`` ("Casa <sep> Trasferta") in ``(casa, trasferta)``,
    o ``None`` se non si riesce a separarlo in due nomi non vuoti.

    Il separatore è **testo libero** configurato dall'utente (es. "v", "vs", "-",
    "/"). Per i separatori **alfabetici** ("v"/"vs") si richiedono spazi attorno
    (``\\s+v\\s+``) così "Liverpool" non viene spezzato sulla 'v' interna; per i
    **simboli** ("-"/"/") gli spazi attorno sono opzionali. Solo la prima
    occorrenza separa (``maxsplit=1``)."""
    name = str(event_name or "").strip()
    sep = str(separator or "").strip()
    if not name or not sep:
        return None
    if sep.isalpha():
        pattern = re.compile(r"\s+" + re.escape(sep) + r"\s+", re.IGNORECASE)
    else:
        pattern = re.compile(r"\s*" + re.escape(sep) + r"\s*")
    parts = pattern.split(name, maxsplit=1)
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    if not home or not away:
        return None
    return home, away


def resolve_event_name(event_name: str, separator: str, profiles) -> str:
    """Traduce un ``EventName`` provider in ``EventName`` Betfair/XTrader, o ``None``.

    Divide su ``separator``, mappa casa e trasferta coi ``profiles`` e ricompone nel
    formato XTrader "Casa - Trasferta" (`dizionario.compose_event_name`). Ritorna
    ``None`` (fail-closed: niente riga CSV) se non si riesce a dividere **o** se una
    delle due squadre non è mappabile."""
    split = split_event(event_name, separator)
    if split is None:
        return None
    home, away = split
    h = resolve_team(home, profiles)
    a = resolve_team(away, profiles)
    if not h or not a:
        return None
    return compose_event_name(h, a)
