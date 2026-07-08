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

from . import credential_store, safety
from .local_db import BetfairLocalDB
# Sport del blocco personale → event_type_id ufficiale Betfair. Fonte UNICA in
# `xtrader_bridge.sports` (riusata anche dal parser personalizzato, PR-P9); qui la
# ri-esportiamo per non spezzare l'API pubblica di questo client.
from ..sports import SPORTS_EVENT_TYPE, sport_for_event_type_id

# Operazioni Betfair usate da questo client: SOLO lettura (nomi per il guard/log).
NAVIGATION_OP = "navigationMenu"
CATALOGUE_OP = "listMarketCatalogue"

# Allowlist SAFETY-CRITICAL (#283): market_type i cui esiti (runner) sono UNIVERSALI —
# stesse parole per OGNI partita (Over/Under, Sì/No, Pari/Dispari) — quindi harvestabili
# come SelectionName permanenti «diretti». I mercati TEAM-DIPENDENTI (MATCH_ODDS,
# *_HANDICAP, CORRECT_SCORE, DRAW_NO_BET, SET_BETTING, DOUBLE_CHANCE, …) hanno come esiti
# NOMI SQUADRA / valori per-partita: NON contribuiscono selezioni (fissarne uno come
# SelectionName scriverebbe una riga CSV sbagliata = scommessa sbagliata). Danno
# comunque MarketType/MarketName (universali). Lista **conservativa** e fail-closed:
# nel dubbio un mercato resta FUORI (nessuna selezione) — il proprietario può estenderla.
# NB: DOUBLE_CHANCE è ESCLUSO di proposito — su Betfair i suoi runner sono team-dipendenti
# («{Home} o Pareggio», «Pareggio o {Away}», «{Home} o {Away}»), non «1X/12/X2» (Fable #326).
_UNIVERSAL_SELECTION_MARKET_TYPES = frozenset({
    "BOTH_TEAMS_TO_SCORE",   # Sì / No
    "ODD_OR_EVEN",           # Dispari / Pari
})


def _is_universal_selection_market(market_type) -> bool:
    """``True`` se le selezioni del `market_type` sono universali (harvestabili come
    SelectionName permanenti, #283). Gli Over/Under di qualunque soglia (gol/corner/…)
    sono universali per costruzione (l'esito è sempre «Over/Under N», mai una squadra);
    per gli altri vale l'allowlist esatta. Sconosciuto/vuoto → ``False`` (fail-closed)."""
    mt = str(market_type or "").strip().upper()
    if not mt:
        return False
    if mt.startswith("OVER_UNDER"):
        return True
    return mt in _UNIVERSAL_SELECTION_MARKET_TYPES


class BetfairApiError(RuntimeError):
    """Errore applicativo dell'Exchange (campo ``error`` di una risposta JSON-RPC).

    È un ``RuntimeError`` (i chiamanti che catturano `RuntimeError`/`Exception` non
    cambiano comportamento), ma porta in più il **codice APING grezzo** in `error_code`,
    così il livello sopra può fare triage — es. una sessione scaduta
    (`INVALID_SESSION_INFORMATION`) → pulizia della sessione (#184 LOW). Il messaggio
    resta safe (solo codici, mai contenuti sensibili)."""

    def __init__(self, message, *, error_code=None):
        super().__init__(message)
        self.error_code = error_code

# Flusso Betfair.it: il navigation menu sta sull'host ITALIANO (.it, locale /it/),
# ma — come da docs Betfair Italy — dopo il login .it le chiamate betting JSON-RPC
# (es. listMarketCatalogue) vanno all'host api.betfair.com e ritornano comunque i
# mercati dell'Exchange italiano. Quindi NAV su .it, CATALOGUE su .com.
_NAV_URL = "https://api.betfair.it/exchange/betting/rest/v1/it/navigation/menu.json"
_CATALOGUE_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
_HTTP_TIMEOUT = 30
# Quanti market per chiamata listMarketCatalogue: `maxResults` è un CAP sul totale
# restituito, quindi i market vanno spezzati in chunk (oltre il cap non tornerebbero
# i runner e la deattivazione li marcherebbe stantii per errore).
_CATALOGUE_BATCH = 100


def _tls_context():
    """Contesto TLS ESPLICITO per le chiamate read-only all'Exchange (#184 M11): verifica del
    certificato server attiva (CERT_REQUIRED + check_hostname). Come in `auth_client`, passarlo
    esplicito a `urlopen` evita che un eventuale override globale del default
    (`ssl._create_default_https_context`) indebolisca in silenzio queste chiamate con credenziali."""
    import ssl
    return ssl.create_default_context()


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
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_tls_context()) as resp:
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
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_tls_context()) as resp:
        return _json.loads(resp.read().decode("utf-8", "replace"))


def _jsonrpc_result(data):
    """Estrae `result` da una risposta JSON-RPC, **sollevando** su `error` o su
    `result` mancante (es. sessione scaduta, app key errata, `TOO_MUCH_DATA`).

    Trattare l'errore come catalogue vuoto sarebbe pericoloso: la sync registrerebbe
    un run OK e poi disattiverebbe le selezioni perché «non riviste» (Codex). Il
    messaggio riporta solo il codice di errore, mai contenuti sensibili."""
    if not isinstance(data, dict):
        raise RuntimeError("Risposta listMarketCatalogue non valida (formato).")
    err = data.get("error")
    if err:
        # #318 L1-3 (review CodeRabbit): un `error` NON-dict (str/list malformato) NON deve finire
        # grezzo nel messaggio d'errore — la docstring garantisce «solo il codice, mai contenuti».
        # Si tronca a 64 char come segnaposto bounded.
        code = err.get("code") if isinstance(err, dict) else str(err)[:64]
        detail = ""
        if isinstance(err, dict):
            # #318 L1-3: `data`/`APINGException` potrebbero arrivare come str/list (forma anomala
            # o encoding insolito) → `.get(...)` su un non-dict solleverebbe `AttributeError`. Con
            # gli isinstance guard un errore con forma inattesa resta classificato (BetfairApiError
            # sollevato), solo senza il dettaglio `errorCode` — fail-closed, mai crash.
            data_field = err.get("data")
            aping = data_field.get("APINGException") if isinstance(data_field, dict) else None
            detail = aping.get("errorCode") if isinstance(aping, dict) else ""
            detail = detail or ""
        raise BetfairApiError(
            f"Errore listMarketCatalogue dall'Exchange (code={code} {detail}).".strip(),
            error_code=detail or None)
    if "result" not in data:
        raise RuntimeError("Risposta listMarketCatalogue priva di 'result'.")
    return data["result"] or []


def _http_catalogue(market_ids, session_token, app_key, *, _poster=None):
    """Default transport di listMarketCatalogue via JSON-RPC read-only (host .com).

    Spezza i market in chunk da `_CATALOGUE_BATCH` (`maxResults` è un cap sul totale)
    e aggrega i risultati; solleva su errore dell'API (`_jsonrpc_result`). `_poster`
    è iniettabile per i test (default: chiamata HTTP reale)."""
    poster = _poster or _http_post_json
    ids = [str(m) for m in market_ids]
    results = []
    for i in range(0, len(ids), _CATALOGUE_BATCH):
        chunk = ids[i:i + _CATALOGUE_BATCH]
        payload = {
            "jsonrpc": "2.0",
            "method": "SportsAPING/v1.0/listMarketCatalogue",
            "params": {
                "filter": {"marketIds": chunk},
                "marketProjection": ["EVENT", "MARKET_DESCRIPTION", "RUNNER_DESCRIPTION"],
                "maxResults": len(chunk),
                # locale ITALIANO esplicito: senza, se la lingua di default dell'account
                # non è l'italiano, listMarketCatalogue tornerebbe nomi mercato/runner in
                # un'altra lingua (es. "The Draw") sovrascrivendo i nomi /it/ del navigation,
                # e il name-mapping/CSV (che richiede nomi IT) si romperebbe (Codex).
                "locale": "it",
            },
            "id": 1,
        }
        data = poster(_CATALOGUE_URL, payload, session_token, app_key)
        results.extend(_jsonrpc_result(data))
    return results


def _node_id(node) -> str:
    """ID di un nodo del navigation menu come stringa, o ``""`` se assente.

    `str(node.get("id"))` darebbe il valore **truthy** ``"None"`` quando l'id manca
    (payload navigation malformato/parziale): a valle ciò farebbe scrivere un record
    fasullo (es. `market_id='None'`) nel dizionario o chiamare `listMarketCatalogue`
    con un id inesistente (Codex). Un id mancante deve restare vuoto, così le guardie
    `if mk.get("id")` / `if ev.get("id")` saltano quel record."""
    v = node.get("id")
    return str(v) if v is not None else ""


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
            if _node_id(node) not in allowed:
                return  # sport non selezionato (o id assente): salta tutto il sottoalbero
            etype = {"id": _node_id(node), "name": node.get("name")}
        elif ntype == "COMPETITION":
            comp = {"id": _node_id(node), "name": node.get("name")}
        elif ntype == "EVENT":
            event = {"id": _node_id(node), "name": node.get("name"),
                     "openDate": node.get("openDate")}
        elif ntype == "MARKET":
            mkid = _node_id(node)
            # Solo un MARKET con id reale genera un record: un id mancante non deve
            # lasciare un EVENTO/SPORT *orfano* attivo nel dizionario (Codex #263) — il
            # loop di sync upserta sport/evento PRIMA del market, quindi se saltassimo
            # solo il market a valle l'evento resterebbe attivo senza alcun mercato valido.
            if etype is not None and mkid:
                records.append({
                    "event_type": etype, "competition": comp, "event": event,
                    "market": {"id": mkid, "name": node.get("name"),
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
        # #318 L1-2: campi che il parser tratta come dict ma che una risposta API malformata
        # (o manomessa) potrebbe consegnare come stringa/lista truthy → `.get(...)` solleverebbe
        # `AttributeError`, che crasherebbe il thread di sync invece di degradare fail-closed. Si
        # coerciscono a `{}` i non-dict (description/event) e si saltano i runner non-dict.
        desc = item.get("description")
        desc = desc if isinstance(desc, dict) else {}
        event = item.get("event")
        event = event if isinstance(event, dict) else {}
        # `runners` deve essere una lista/tupla: un valore NON-iterabile truthy (es. `runners: 123`)
        # farebbe fallire `for r in ...` con `TypeError`; una stringa/dict itererebbe caratteri/chiavi.
        # Si accetta solo list/tuple, altrimenti nessun runner (fail-closed, #318 L1-2).
        raw_runners = item.get("runners")
        if not isinstance(raw_runners, (list, tuple)):
            raw_runners = ()
        runners = []
        for r in raw_runners:
            if not isinstance(r, dict):
                continue                    # runner non-dict (input malformato) → skip, non crash
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
        # App key: quella passata o, in mancanza, la Delayed App Key salvata localmente
        # (così l'engine può essere costruito una volta e prendere la chiave corrente).
        app_key = self.app_key or credential_store.load_credentials().app_key
        if not token or not app_key:
            raise RuntimeError(
                "CatalogueSync non configurato: inietta i transport nei test, "
                "oppure fornisci una sessione Betfair loggata + Delayed App Key.")
        if nav is None:
            nav = lambda: _http_navigation(token, app_key)          # noqa: E731
        if cat is None:
            cat = lambda mids: _http_catalogue(mids, token, app_key)  # noqa: E731
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
        etids = event_type_ids_for(sports)
        # Fail-closed: nessuno sport valido → NON eseguire una sync "vuota" che
        # registrerebbe OK senza disattivare nulla, lasciando attivi record stantii.
        if not etids:
            raise ValueError(
                "Nessuno sport valido selezionato per la sync Betfair "
                "(lista vuota o nomi non riconosciuti).")

        # La transazione tiene il lock del DB per TUTTA la sync: allocare il marker
        # QUI dentro serializza le sync concorrenti sullo stesso DB e garantisce che
        # l'ordine dei marker coincida con l'ordine di commit (Codex). Su rollback il
        # marker viene annullato con il resto: i marker committati restano monotòni.
        try:
            return self._sync_in_transaction(nav_transport, cat_transport, etids)
        except BetfairApiError as ex:
            # Token scaduto/invalido → pulisci la sessione così la GUI torna 'disconnesso'
            # e l'utente rilogga, invece di restare loggati con un token morto (#184 LOW).
            # Solo i codici di scadenza sloggano; gli altri errori API NON toccano la
            # sessione. La sessione è opzionale (transport iniettati nei test).
            if self.session is not None and hasattr(self.session, "clear_if_expired"):
                self.session.clear_if_expired(ex.error_code)
            raise

    def _harvest_teams(self, event_type_id, participant_1, participant_2, seen_at) -> int:
        """Harvest #282: accumula i nomi squadra **permanenti** (`betfair_known_teams`).

        Solo i match reali con DUE partecipanti («Home v Away»): un evento a un solo nome
        (torneo/outright, es. «ATP Finals») NON è una squadra e viene saltato, per non
        inquinare la tabella permanente. Lo sport è salvato col **nome** canonico (la
        chiave con cui la mappatura nomi li consulta), derivato dall'`event_type_id`; uno
        sport ignoto → nessun harvest. Idempotente: nomi già noti non duplicano
        (chiave `sport` + `normalized_name`). Ritorna quanti nomi ha scritto (0/1/2)."""
        p1 = (participant_1 or "").strip()
        p2 = (participant_2 or "").strip()
        if not (p1 and p2):
            return 0
        sport = sport_for_event_type_id(event_type_id)
        if not sport:
            return 0
        written = 0
        for name in (p1, p2):
            if self.db.upsert_known_team(sport, name, seen_at=seen_at):
                written += 1
        return written

    def _harvest_market_terms(self, event_type_id, market_name, market_type,
                              runners, seen_at) -> int:
        """Harvest #283: accumula i valori PERMANENTI di mercato/selezione
        (`betfair_known_market_terms`), «diretti» (nessuna mappatura). Salva SEMPRE la
        riga àncora del mercato (MarketType + MarketName, universali) e — SOLO per i
        market_type a selezioni universali (`_is_universal_selection_market`) — una riga
        per ogni SelectionName. I mercati team-dipendenti (MATCH_ODDS, *_HANDICAP,
        CORRECT_SCORE, …) danno MarketType/MarketName ma NESSUNA selezione: un runner
        per-partita (nome squadra/risultato) fissato romperebbe il CSV/scommessa
        (fail-closed, allowlist). Sport dal nome canonico via `event_type_id`; sport
        ignoto → skip. Non tocca gli ID effimeri. Ritorna quante righe ha scritto."""
        sport = sport_for_event_type_id(event_type_id)
        if not sport:
            return 0
        if not str(market_name or "").strip():
            return 0
        written = 0
        # Riga àncora: il mercato esiste (MarketType/MarketName selezionabili anche per i
        # mercati team-dipendenti, che però non contribuiscono selezioni).
        if self.db.upsert_market_term(sport, market_type, market_name, seen_at=seen_at):
            written += 1
        if _is_universal_selection_market(market_type):
            for r in runners or ():
                name = r.get("runner_name")
                if str(name or "").strip() and self.db.upsert_market_term(
                        sport, market_type, market_name, name, seen_at=seen_at):
                    written += 1
        return written

    def _sync_in_transaction(self, nav_transport, cat_transport, etids) -> dict:
        """Corpo transazionale della sync (estratto da `sync` per il triage degli errori
        di scadenza sessione). Tutte le scritture stanno in UNA transazione: un fallimento
        a metà NON lascia il dizionario parziale (rollback)."""
        with self.db.transaction():
            marker = self.db.new_sync_marker()
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
                    # Harvest permanente dei nomi squadra (#282): non tocca gli ID.
                    self._harvest_teams(et["id"], p1, p2, marker)
                if mk.get("id"):
                    self.db.upsert_market(mk["id"], ev_id, et["id"], mk.get("name"),
                                          mk.get("marketType"), seen_at=marker)
                    market_meta[mk["id"]] = {"event_id": ev_id, "event_type_id": et["id"],
                                             "competition_id": comp_id,
                                             "name": mk.get("name"),
                                             "marketType": mk.get("marketType"),
                                             # openDate dal MENU: serve come fallback se il
                                             # catalogue ometterà l'orario (Codex), per non
                                             # azzerarlo nel re-upsert dell'evento.
                                             "open_date": ev.get("openDate") if ev else None}

            market_ids = list(market_meta.keys())

            # Arricchimento con il catalogue: riscrive market_type/market_name reali e
            # ri-upserta l'EVENTO con nome/openDate/partecipanti autorevoli del catalogue
            # (preservando event_type_id/competition_id dal menu, per lo scoping). Poi
            # upserta le selezioni.
            new_selections = 0
            if market_ids:
                catalogue = parse_market_catalogue(cat_transport(market_ids))
                for market_id, info in catalogue.items():
                    meta = market_meta.get(market_id, {})
                    cat_ev = info.get("event") or {}
                    # event_id risolto: dal menu o, se il market non aveva un evento
                    # parente, dall'evento del catalogue (Codex). `""` se nessuno dei due.
                    ev_id = meta.get("event_id") or cat_ev.get("id") or ""
                    if ev_id and cat_ev.get("name"):
                        p1, p2 = split_participants(cat_ev.get("name"))
                        # openDate: il catalogue può ometterlo (parse_market_catalogue lo
                        # tollera); in quel caso NON sovrascrivere con None l'orario già
                        # salvato dal navigation — fallback all'openDate del menu (Codex).
                        open_date = cat_ev.get("openDate") or meta.get("open_date")
                        self.db.upsert_event(
                            ev_id, meta.get("event_type_id", ""),
                            meta.get("competition_id", ""), cat_ev.get("name"),
                            open_date, p1, p2, seen_at=marker)
                        # Harvest permanente dei nomi squadra dai nomi autorevoli del
                        # catalogue (#282): idempotente col navigation, non tocca gli ID.
                        self._harvest_teams(meta.get("event_type_id", ""), p1, p2, marker)
                    self.db.upsert_market(
                        market_id, ev_id,   # ev_id RISOLTO, non il solo event_id del menu (Codex)
                        meta.get("event_type_id", ""),
                        info.get("market_name") or meta.get("name"),
                        info.get("market_type") or meta.get("marketType"),
                        seen_at=marker)
                    # Harvest permanente dei valori mercato/selezione (#283): diretti,
                    # SelectionName solo dai mercati a esiti universali (allowlist). Non
                    # tocca gli ID effimeri.
                    self._harvest_market_terms(
                        meta.get("event_type_id", ""),
                        info.get("market_name") or meta.get("name"),
                        info.get("market_type") or meta.get("marketType"),
                        info.get("runners", []), marker)
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
            deactivated = 0
            for etid in etids:
                deactivated += self.db.deactivate_unseen("betfair_sports", marker, scope_value=etid)
                deactivated += self.db.deactivate_unseen("betfair_competitions", marker, scope_value=etid)
                deactivated += self.db.deactivate_unseen("betfair_events", marker, scope_value=etid)
                deactivated += self.db.deactivate_unseen("betfair_markets", marker, scope_value=etid)
            for market_id in self.db.market_ids_for_sports(etids):
                deactivated += self.db.deactivate_unseen("betfair_selections", marker,
                                                         scope_value=market_id)

            summary = {
                "sports": sorted(etids),
                "markets": len(market_ids),
                "selections": new_selections,
                "deactivated": deactivated,
                "active_events": self.db.count_active("betfair_events"),
                "active_markets": self.db.count_active("betfair_markets"),
                # Nomi squadra permanenti totali dopo la sync (#282): accumulano nel
                # tempo, NON calano quando gli eventi/ID scadono.
                "known_teams": self.db.count_known_teams(),
                # Valori mercato/selezione permanenti totali dopo la sync (#283): idem,
                # accumulano nel tempo (righe àncora mercato + selezioni universali).
                "known_market_terms": self.db.count_market_terms(),
            }
            self.db.record_sync_run(started_at=marker, finished_at=marker, status="OK",
                                    summary=json.dumps(summary, ensure_ascii=False))
        return summary
