"""Sync del palinsesto Betfair: navigation menu + listMarketCatalogue (issue #86 PR-P6).

Scarica il **navigation menu** Betfair (read-only) filtrando gli sport del blocco
personale (Calcio, Tennis, Basket, Rugby Union), poi **arricchisce** i mercati con
`listMarketCatalogue` (MarketId, SelectionId, nome selezione, handicap, market type,
nome evento, participant_1/2) e salva tutto nel **dizionario locale** (`BetfairLocalDB`).

Vincoli (issue #86):
- usa la **Delayed App Key** (mai la Live Key); legge solo, niente quote live se non
  necessarie;
- **nessuna operazione di scommessa**: ogni operazione passa dal guard
  `safety.assert_read_only`, che blocca le operazioni di scommessa dell'Exchange;
- nessun dato sensibile nei log; i token restano in RAM (`BetfairSession`).

Le chiamate di rete sono **iniettabili** (`navigation_transport`, `catalogue_transport`)
così i test girano offline con mock; il default usa la stdlib (urllib) ed è verificato
a mano. Il parsing del menu/catalogue è puro e testato.
"""

import json

from . import safety
from .local_db import BetfairLocalDB

# Sport del blocco personale → event_type_id ufficiale Betfair.
SPORTS_EVENT_TYPE = {
    "Calcio": "1",
    "Tennis": "2",
    "Basket": "7522",
    "Rugby Union": "5",
}

# Operazioni Betfair usate da questo client: SOLO lettura (nomi per il guard/log).
NAVIGATION_OP = "navigationMenu"
CATALOGUE_OP = "listMarketCatalogue"

# Host/locale ITALIANI dell'Exchange (questo è il flusso Betfair.it): la Delayed Key
# e la sessione .it devono colpire l'host italiano, non quello UK/EN.
_NAV_URL = "https://api.betfair.it/exchange/betting/rest/v1/it/navigation/menu.json"
_CATALOGUE_URL = "https://api.betfair.it/exchange/betting/json-rpc/v1"
_HTTP_TIMEOUT = 30
# Quante selezioni richiedere per market nel catalogue (RUNNER_METADATA dà i runner).
_CATALOGUE_MAX_RESULTS = 1000


def _http_post_json(url, payload_dict, session_token, app_key):
    """POST JSON read-only verso l'Exchange .it con gli header Betfair. Solo stdlib;
    non logga nulla. Ritorna il JSON decodificato."""
    import json as _json
    import urllib.request

    body = _json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "X-Application": app_key,
        "X-Authentication": session_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return _json.loads(resp.read().decode("utf-8", "replace"))


def _http_navigation(session_token, app_key):
    """Default transport del navigation menu (.it), via stdlib GET."""
    import json as _json
    import urllib.request

    req = urllib.request.Request(_NAV_URL, method="GET", headers={
        "X-Application": app_key,
        "X-Authentication": session_token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return _json.loads(resp.read().decode("utf-8", "replace"))


def _http_catalogue(market_ids, session_token, app_key):
    """Default transport di listMarketCatalogue (.it), via JSON-RPC read-only."""
    payload = {
        "jsonrpc": "2.0",
        "method": "SportsAPING/v1.0/listMarketCatalogue",
        "params": {
            "filter": {"marketIds": list(market_ids)},
            "marketProjection": ["EVENT", "MARKET_DESCRIPTION", "RUNNER_DESCRIPTION"],
            "maxResults": _CATALOGUE_MAX_RESULTS,
        },
        "id": 1,
    }
    data = _http_post_json(_CATALOGUE_URL, payload, session_token, app_key)
    if isinstance(data, dict):
        return data.get("result") or []
    return []


def event_type_ids_for(sports) -> set:
    """Insieme degli `event_type_id` per i nomi sport richiesti (ignota → scartata)."""
    out = set()
    for s in sports or ():
        etid = SPORTS_EVENT_TYPE.get(s)
        if etid:
            out.add(etid)
    return out


def split_participants(event_name):
    """(`participant_1`, `participant_2`) dal nome evento Betfair «Home v Away».

    Betfair separa i due partecipanti con `" v "`. Se non c'è separatore (es. una
    gara/torneo), ritorna (`nome`, ``""``). Input vuoto → (``""``, ``""``)."""
    name = (event_name or "").strip()
    if not name:
        return "", ""
    for sep in (" v ", " vs ", " @ "):
        if sep in name:
            a, b = name.split(sep, 1)
            return a.strip(), b.strip()
    return name, ""


def parse_navigation(menu, allowed_event_type_ids):
    """Estrae dal navigation menu i mercati degli sport ammessi.

    Ritorna una lista di record: ``{event_type, competition, event, market}`` (i
    primi tre possono essere parziali). Cammina ricorsivamente l'albero
    (EVENT_TYPE → GROUP* → COMPETITION? → EVENT → MARKET): i sottoalberi di sport
    non ammessi sono saltati interamente, così si salvano SOLO gli sport scelti."""
    allowed = {str(x) for x in (allowed_event_type_ids or ())}
    records = []

    def walk(node, etype=None, comp=None, event=None):
        if not isinstance(node, dict):
            return
        ntype = node.get("type")
        if ntype == "EVENT_TYPE":
            if str(node.get("id")) not in allowed:
                return  # sport non selezionato: salta tutto il sottoalbero
            etype = {"id": str(node.get("id")), "name": node.get("name")}
        elif ntype == "COMPETITION":
            comp = {"id": str(node.get("id")), "name": node.get("name")}
        elif ntype == "EVENT":
            event = {"id": str(node.get("id")), "name": node.get("name"),
                     "openDate": node.get("openDate")}
        elif ntype == "MARKET":
            if etype is not None:
                records.append({
                    "event_type": etype, "competition": comp, "event": event,
                    "market": {"id": str(node.get("id")), "name": node.get("name"),
                               "marketType": node.get("marketType")},
                })
        for child in node.get("children") or ():
            walk(child, etype, comp, event)

    walk(menu)
    return records


def parse_market_catalogue(catalogue):
    """Normalizza la risposta di `listMarketCatalogue` in una mappa
    ``market_id -> {event, market_type, runners:[{selection_id, runner_name,
    handicap}]}``. Tollerante a campi mancanti."""
    out = {}
    for item in catalogue or ():
        if not isinstance(item, dict):
            continue
        market_id = str(item.get("marketId") or "")
        if not market_id:
            continue
        desc = item.get("description") or {}
        event = item.get("event") or {}
        runners = []
        for r in item.get("runners") or ():
            runners.append({
                "selection_id": str(r.get("selectionId") or ""),
                "runner_name": r.get("runnerName"),
                "handicap": r.get("handicap", 0) or 0,
            })
        out[market_id] = {
            "market_name": item.get("marketName"),
            "market_type": desc.get("marketType"),
            "event": {"id": str(event.get("id") or ""), "name": event.get("name"),
                      "openDate": event.get("openDate")},
            "runners": runners,
        }
    return out


class CatalogueSync:
    """Orchestratore del download palinsesto → dizionario locale (read-only).

    Transport iniettabili per i test: `navigation_transport()` ritorna il JSON del
    menu; `catalogue_transport(market_ids)` ritorna la lista `listMarketCatalogue`.
    Se NON iniettati, vengono costruiti i transport di default (stdlib) che richiedono
    una `session` Betfair loggata e la `app_key` (Delayed): senza, `sync()` fallisce
    in modo esplicito invece di fare silenziosamente nulla (Codex)."""

    def __init__(self, db: BetfairLocalDB, *, session=None, app_key=None,
                 navigation_transport=None, catalogue_transport=None):
        self.db = db
        self.session = session
        self.app_key = app_key
        self._nav = navigation_transport
        self._cat = catalogue_transport

    def _resolve_transports(self):
        """Ritorna (navigation_transport, catalogue_transport). Costruisce i default
        di rete da `session`+`app_key` quando non iniettati; se mancano, alza
        `RuntimeError` (niente sync "a vuoto")."""
        nav, cat = self._nav, self._cat
        if nav is not None and cat is not None:
            return nav, cat
        token = getattr(self.session, "token", None) if self.session else None
        if not token or not self.app_key:
            raise RuntimeError(
                "CatalogueSync non configurato: inietta i transport nei test, "
                "oppure fornisci una sessione Betfair loggata + Delayed App Key.")
        if nav is None:
            nav = lambda: _http_navigation(token, self.app_key)          # noqa: E731
        if cat is None:
            cat = lambda mids: _http_catalogue(mids, token, self.app_key)  # noqa: E731
        return nav, cat

    def sync(self, sports) -> dict:
        """Sincronizza gli sport richiesti nel dizionario locale e ritorna un
        riepilogo safe. Idempotente: rieseguire con gli stessi dati non duplica
        (upsert per chiave naturale) e i record non più visti diventano inattivi.

        Tutte le scritture sono in UNA transazione: se navigation/catalogue falliscono
        a metà, il dizionario NON resta in uno stato parziale (rollback)."""
        # Contratto read-only: entrambe le operazioni NON sono di scommessa.
        safety.assert_read_only(NAVIGATION_OP)
        safety.assert_read_only(CATALOGUE_OP)

        nav_transport, cat_transport = self._resolve_transports()
        marker = self.db.new_sync_marker()   # fuori dalla tx: il contatore resta monotòno
        etids = event_type_ids_for(sports)

        with self.db.transaction():
            menu = nav_transport()
            records = parse_navigation(menu, etids)

            # metadati mercato dal menu (per riscriverli arricchiti dopo il catalogue).
            market_meta = {}
            for rec in records:
                et = rec["event_type"]
                self.db.upsert_sport(et["id"], et.get("name"), seen_at=marker)
                comp = rec.get("competition")
                comp_id = comp["id"] if comp and comp.get("id") else ""
                if comp_id:
                    self.db.upsert_competition(comp_id, et["id"], comp.get("name"),
                                               seen_at=marker)
                ev = rec.get("event")
                mk = rec["market"]
                ev_id = ev["id"] if ev and ev.get("id") else ""
                if ev_id:
                    p1, p2 = split_participants(ev.get("name"))
                    self.db.upsert_event(ev_id, et["id"], comp_id, ev.get("name"),
                                         ev.get("openDate"), p1, p2, seen_at=marker)
                if mk.get("id"):
                    self.db.upsert_market(mk["id"], ev_id, et["id"], mk.get("name"),
                                          mk.get("marketType"), seen_at=marker)
                    market_meta[mk["id"]] = {"event_id": ev_id, "event_type_id": et["id"],
                                             "name": mk.get("name"),
                                             "marketType": mk.get("marketType")}

            market_ids = list(market_meta.keys())

            # Arricchimento con il catalogue: riscrive market_type/market_name reali
            # (il menu può non averli) e upserta le selezioni. NON tocca event_type_id
            # con valori vuoti (resta quello del menu, per lo scoping per sport).
            new_selections = 0
            if market_ids:
                catalogue = parse_market_catalogue(cat_transport(market_ids))
                for market_id, info in catalogue.items():
                    meta = market_meta.get(market_id, {})
                    self.db.upsert_market(
                        market_id, meta.get("event_id", ""),
                        meta.get("event_type_id", ""),
                        info.get("market_name") or meta.get("name"),
                        info.get("market_type") or meta.get("marketType"),
                        seen_at=marker)
                    for r in info.get("runners", []):
                        if r.get("selection_id"):
                            self.db.upsert_selection(market_id, r["selection_id"],
                                                     r.get("runner_name"),
                                                     r.get("handicap", 0), seen_at=marker)
                            new_selections += 1

            # Record non più visti → inattivi. Sport/competizioni/eventi/mercati scoped
            # per sport (event_type_id). Le selezioni vanno disattivate per TUTTI i
            # mercati degli sport sincronizzati (anche quelli SPARITI dal menu), non
            # solo quelli rivisti: altrimenti resterebbero SelectionId stantii attivi.
            for etid in etids:
                self.db.deactivate_unseen("betfair_sports", marker, scope_value=etid)
                self.db.deactivate_unseen("betfair_competitions", marker, scope_value=etid)
                self.db.deactivate_unseen("betfair_events", marker, scope_value=etid)
                self.db.deactivate_unseen("betfair_markets", marker, scope_value=etid)
            for market_id in self.db.market_ids_for_sports(etids):
                self.db.deactivate_unseen("betfair_selections", marker,
                                          scope_value=market_id)

            summary = {
                "sports": sorted(etids),
                "markets": len(market_ids),
                "selections": new_selections,
                "active_events": self.db.count_active("betfair_events"),
                "active_markets": self.db.count_active("betfair_markets"),
            }
            self.db.record_sync_run(started_at=marker, finished_at=marker, status="OK",
                                    summary=json.dumps(summary, ensure_ascii=False))
        return summary
