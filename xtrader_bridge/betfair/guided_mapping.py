"""Logica PURA del «Mapping guidato» Betfair → nome canale (Fase 3 collaudo Betfair).

Alimenta la sotto-scheda «🌳 Mapping guidato» di Strumenti → Mapping: l'utente naviga
Sport → Competizione → Squadre (dai dati Betfair già sincronizzati sul PC) e, per ogni
squadra, scrive «come la chiama il canale Telegram». Il risultato viene fuso nei profili
`name_mappings` esistenti (consumati dal parser via `name_mapping_store.resolve_event_name`).

Questo modulo è **puro** (niente GUI, niente rete, niente scrittura): solo lettura del
dizionario Betfair locale (`BetfairLocalDB.fetchall`) e trasformazioni di liste/dict,
così è testabile headless. Il busy-guard sul lock del DB (fail-fast durante una sync,
come `DictionaryViewerController.view_if_free`) e la persistenza su `config.json` restano
al chiamante (app/GUI).

Punti chiave del design (decisi col proprietario):
- la **competizione serve solo a navigare/trovare la squadra**: NON entra nella riga di
  mapping salvata (il parser non filtra per competizione). La riga salvata è per-squadra:
  `{country:"", betfair:<squadra>, provider:<alias canale>, sport:<sport>, entity_type:"team"}`;
- le **squadre** di una competizione sono l'unione di `participant_1`/`participant_2` degli
  eventi di quella competizione (popolati da `catalogue_client.split_participants`), con i
  vuoti scartati (eventi outright/tornei hanno `participant_2` vuoto) e dedup;
- ri-salvare **aggiorna** (non duplica) le righe delle squadre editate e **lascia intatte**
  tutte le altre righe del profilo (altri sport, mercati, righe manuali).
"""

from .. import sports
from ..dizionario import normalize
from ..name_mapping_store import normalize_entity_type

# Entity type scritto dall'albero guidato per una squadra.
_TEAM_ENTITY = "team"


def _is_active(row) -> bool:
    try:
        return int(row.get("active", 0)) == 1
    except (TypeError, ValueError):
        return False


def competitions_for_sport(db, sport) -> list:
    """Competizioni **attive** di uno sport, come ``[{"competition_id", "name"}]`` ordinate per
    nome (case-insensitive), dedup per id.

    `db` è un `BetfairLocalDB` (letto via `fetchall`, nessun filtro server-side). Sport non
    valido/non riconosciuto → ``[]`` (tendina vuota). Solo le competizioni attive: quelle di
    stagioni concluse (disattivate dal mark-and-sweep) non intasano la tendina; le squadre
    storiche di una competizione attiva restano comunque disponibili (vedi `teams_for_competition`,
    che NON filtra per `active`)."""
    etid = sports.event_type_id_for_sport(sport)
    if not etid:
        return []
    seen = {}
    for c in db.fetchall("betfair_competitions"):
        if str(c.get("event_type_id", "")) != etid or not _is_active(c):
            continue
        cid = str(c.get("competition_id", "") or "")
        if not cid or cid in seen:
            continue
        seen[cid] = str(c.get("name", "") or "")
    return sorted(({"competition_id": cid, "name": name} for cid, name in seen.items()),
                  key=lambda c: c["name"].casefold())


def teams_for_competition(db, competition_id) -> list:
    """Nomi squadra **unici** degli eventi di una competizione, ordinati case-insensitive.

    Unione di `participant_1`/`participant_2` degli eventi con quel `competition_id`, scartando i
    vuoti (eventi outright/tornei senza secondo partecipante) e deduplicando **preservando il
    display** (se lo stesso nome compare con casing diversi, tiene la prima occorrenza in ordine).
    NON filtra per `active`: include anche gli eventi passati/disattivati, così il roster storico
    della competizione resta mappabile. `competition_id` vuoto → ``[]``."""
    cid = str(competition_id or "")
    if not cid:
        return []
    seen = {}
    for e in db.fetchall("betfair_events"):
        if str(e.get("competition_id", "")) != cid:
            continue
        for key in ("participant_1", "participant_2"):
            name = str(e.get(key) or "").strip()
            if not name:
                continue
            k = normalize(name)
            if k and k not in seen:
                seen[k] = name
    return sorted(seen.values(), key=lambda t: t.casefold())


def _entry_matches_team(entry, sport_norm, team_keys) -> bool:
    """True se `entry` è una riga-squadra da SOSTITUIRE quando si ri-salva l'albero: stesso sport
    (normalizzato) e `betfair` che combacia (normalizzato) con una delle squadre editate. Limita ai
    tipi entità squadra/agnostico (una riga `player`/`competition`/`market`/`selection` con lo stesso
    nome NON viene toccata, per non distruggere mapping manuali di altro tipo)."""
    if normalize_entity_type(entry.get("entity_type", "")) not in ("", _TEAM_ENTITY):
        return False
    if sports.normalize_sport(entry.get("sport", "")) != sport_norm:
        return False
    return normalize(entry.get("betfair", "")) in team_keys


def merge_team_aliases(existing_entries, sport, team_aliases) -> list:
    """Fonde le associazioni squadra→alias-canale dell'albero guidato nelle righe di UN profilo,
    senza toccare le righe non pertinenti.

    - `existing_entries`: righe correnti del profilo (lista di dict
      ``{country, betfair, provider, sport, entity_type}``).
    - `sport`: sport del ramo corrente (nome; normalizzato internamente).
    - `team_aliases`: dict ``{nome_squadra_betfair: alias_canale}``. Alias vuoto/solo-spazi →
      nessuna riga per quella squadra (e rimuove un'eventuale riga precedente: è il modo per
      «cancellare» una mappatura dall'albero).

    Ritorna la nuova lista di righe del profilo:
      - **rimuove** le righe-squadra (stesso sport, entity team/agnostico) il cui `betfair` combacia
        con una squadra presente in `team_aliases` (così ri-salvare AGGIORNA invece di duplicare —
        indipendentemente dall'alias, anche vuoto);
      - **aggiunge** una riga ``{country:"", betfair:<squadra>, provider:<alias>, sport, entity_type:"team"}``
        per ogni squadra con alias non vuoto (display della squadra preservato);
      - **lascia intatte** tutte le altre righe (altri sport, mercati, righe manuali, entity diverse).

    La pulizia/validazione finale (fail-closed su sport/entity_type ignoti, dedup) resta a
    `name_mapping_store.set_entries`, che il chiamante usa per persistere."""
    sport_norm = sports.normalize_sport(sport)
    # Chiavi normalizzate delle squadre editate (sia quelle con alias sia quelle svuotate).
    team_keys = {normalize(t) for t in team_aliases if normalize(t)}
    # 1) tieni tutte le righe NON pertinenti (le squadre editate vengono ricostruite sotto).
    kept = [e for e in existing_entries
            if not _entry_matches_team(e, sport_norm, team_keys)]
    # 2) aggiungi una riga per ogni squadra con alias non vuoto.
    added = []
    for team, alias in team_aliases.items():
        team = str(team or "").strip()
        alias = str(alias or "").strip()
        if not team or not alias:
            continue
        added.append({"country": "", "betfair": team, "provider": alias,
                      "sport": sport or "", "entity_type": _TEAM_ENTITY})
    return kept + added


def existing_aliases_for_teams(existing_entries, sport, teams) -> dict:
    """Pre-compilazione: per le `teams` date, ritorna ``{nome_squadra: alias_già_salvato}`` leggendo
    le righe del profilo che mappano quella squadra (stesso sport, entity team/agnostico). Serve alla
    GUI per mostrare l'alias già presente accanto alla squadra. Nessun match → chiave assente.

    Se più righe mappano la stessa squadra, vince la **prima** in ordine di profilo (stessa priorità
    del runtime, dove il primo match utile vale)."""
    sport_norm = sports.normalize_sport(sport)
    by_key = {}
    for k in (normalize(t) for t in teams):
        by_key.setdefault(k, None)
    out = {}
    for e in existing_entries:
        if normalize_entity_type(e.get("entity_type", "")) not in ("", _TEAM_ENTITY):
            continue
        if sports.normalize_sport(e.get("sport", "")) != sport_norm:
            continue
        k = normalize(e.get("betfair", ""))
        if k in by_key and k not in out:
            alias = str(e.get("provider", "") or "").strip()
            if alias:
                out[k] = alias
    # rimappa dalle chiavi normalizzate ai nomi-squadra originali
    result = {}
    for t in teams:
        k = normalize(t)
        if k in out:
            result[t] = out[k]
    return result
