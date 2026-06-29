"""Test hard del sync palinsesto Betfair (issue #86 PR-P6).

Parsing del navigation menu (filtro sport) e del listMarketCatalogue, e sync nel
dizionario locale con transport finti (offline): per sport, idempotente (due volte
non duplica), read-only. Nessuna chiamata di rete, nessun XTrader.
"""

import pytest

from xtrader_bridge.betfair import safety
from xtrader_bridge.betfair.catalogue_client import (
    CatalogueSync,
    SPORTS_EVENT_TYPE,
    event_type_ids_for,
    parse_market_catalogue,
    parse_navigation,
    split_participants,
)
from xtrader_bridge.betfair.local_db import BetfairLocalDB


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


# ── helpers di parsing ────────────────────────────────────────────────────────

def test_event_type_ids_for():
    assert event_type_ids_for(["Calcio", "Tennis"]) == {"1", "2"}
    assert event_type_ids_for(["Sconosciuto"]) == set()
    assert SPORTS_EVENT_TYPE["Rugby Union"] == "5"


def test_split_participants():
    assert split_participants("Inter v Milan") == ("Inter", "Milan")
    assert split_participants("Sinner vs Alcaraz") == ("Sinner", "Alcaraz")
    assert split_participants("ATP Finals") == ("ATP Finals", "")
    assert split_participants("") == ("", "")


# ── navigation menu ───────────────────────────────────────────────────────────

def _menu():
    return {
        "type": "GROUP", "name": "ROOT", "children": [
            {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": [
                {"type": "COMPETITION", "id": "c1", "name": "Serie A", "children": [
                    {"type": "EVENT", "id": "e1", "name": "Inter v Milan",
                     "openDate": "2026-07-01T18:00:00Z", "children": [
                        {"type": "MARKET", "id": "1.101", "name": "Match Odds",
                         "marketType": "MATCH_ODDS"}]}]}]},
            {"type": "EVENT_TYPE", "id": "2", "name": "Tennis", "children": [
                {"type": "EVENT", "id": "e2", "name": "Sinner v Alcaraz", "children": [
                    {"type": "MARKET", "id": "1.202", "name": "Match Odds",
                     "marketType": "MATCH_ODDS"}]}]},
            {"type": "EVENT_TYPE", "id": "999", "name": "Cricket", "children": [
                {"type": "EVENT", "id": "e9", "name": "X v Y", "children": [
                    {"type": "MARKET", "id": "1.900", "name": "Match Odds"}]}]},
        ]}


def test_parse_navigation_filtra_sport():
    # Solo Calcio (1): niente Tennis, niente Cricket.
    recs = parse_navigation(_menu(), {"1"})
    assert len(recs) == 1
    r = recs[0]
    assert r["event_type"]["id"] == "1"
    assert r["competition"]["name"] == "Serie A"
    assert r["event"]["id"] == "e1"
    assert r["market"]["id"] == "1.101"


def test_parse_navigation_sport_non_ammessi_scartati():
    # Calcio+Tennis ammessi, Cricket (999) scartato.
    recs = parse_navigation(_menu(), {"1", "2"})
    ids = {r["market"]["id"] for r in recs}
    assert ids == {"1.101", "1.202"}


# ── market catalogue ──────────────────────────────────────────────────────────

def _catalogue():
    return [
        {"marketId": "1.101", "marketName": "Match Odds",
         "description": {"marketType": "MATCH_ODDS"},
         "event": {"id": "e1", "name": "Inter v Milan"},
         "runners": [
             {"selectionId": 47972, "runnerName": "Inter", "handicap": 0},
             {"selectionId": 47973, "runnerName": "Milan", "handicap": 0},
             {"selectionId": 58805, "runnerName": "The Draw", "handicap": 0}]},
    ]


def test_parse_market_catalogue():
    out = parse_market_catalogue(_catalogue())
    assert "1.101" in out
    info = out["1.101"]
    assert info["market_type"] == "MATCH_ODDS"
    assert len(info["runners"]) == 3
    assert info["runners"][0]["selection_id"] == "47972"


# ── sync end-to-end nel DB locale ─────────────────────────────────────────────

def _sync(db):
    return CatalogueSync(db, navigation_transport=lambda: _menu(),
                         catalogue_transport=lambda mids: _catalogue())


def test_sync_persiste_sport_evento_mercato_selezioni(db):
    summary = _sync(db).sync(["Calcio"])
    assert db.count_active("betfair_sports") == 1
    assert db.count_active("betfair_events") == 1
    assert db.count_active("betfair_markets") == 1
    assert db.count_active("betfair_selections") == 3   # Inter/Milan/The Draw
    # participant_1/participant_2 salvati dall'evento "Inter v Milan"
    ev = db.get_events()[0]
    assert ev["participant_1"] == "Inter" and ev["participant_2"] == "Milan"
    assert summary["selections"] == 3


def test_sync_due_volte_non_duplica(db):
    s = _sync(db)
    s.sync(["Calcio"])
    s.sync(["Calcio"])                       # stessa identica risposta
    assert db.count_active("betfair_sports") == 1
    assert db.count_active("betfair_events") == 1
    assert db.count_active("betfair_markets") == 1
    assert db.count_active("betfair_selections") == 3


def test_sync_tennis(db):
    CatalogueSync(db, navigation_transport=lambda: _menu(),
                  catalogue_transport=lambda mids: []).sync(["Tennis"])
    # Solo Tennis: l'evento e2 c'è, il Calcio no.
    ids = {e["event_id"] for e in db.get_events()}
    assert ids == {"e2"}


def _menu_basket_rugby():
    """Menu con Basket (event_type 7522) e Rugby Union (5), per i due sport del
    blocco che mancavano di un test di sync end-to-end (issue #178 §3)."""
    return {
        "type": "GROUP", "name": "ROOT", "children": [
            {"type": "EVENT_TYPE", "id": "7522", "name": "Basketball", "children": [
                {"type": "EVENT", "id": "eb", "name": "Lakers v Celtics", "children": [
                    {"type": "MARKET", "id": "1.700", "name": "Moneyline",
                     "marketType": "MATCH_ODDS"}]}]},
            {"type": "EVENT_TYPE", "id": "5", "name": "Rugby Union", "children": [
                {"type": "EVENT", "id": "er", "name": "England v Wales", "children": [
                    {"type": "MARKET", "id": "1.500", "name": "Match Odds",
                     "marketType": "MATCH_ODDS"}]}]},
        ]}


# Catalogue keyed sui market_id richiesti: così i test esercitano DAVVERO la fase
# listMarketCatalogue (mercati/selezioni persistiti), non solo la navigation (Codex #178 §3).
_BR_CATALOGUE = {
    "1.700": {"marketId": "1.700", "marketName": "Moneyline",
              "description": {"marketType": "MATCH_ODDS"},
              "event": {"id": "eb", "name": "Lakers v Celtics"},
              "runners": [{"selectionId": 700001, "runnerName": "Lakers", "handicap": 0},
                          {"selectionId": 700002, "runnerName": "Celtics", "handicap": 0}]},
    "1.500": {"marketId": "1.500", "marketName": "Match Odds",
              "description": {"marketType": "MATCH_ODDS"},
              "event": {"id": "er", "name": "England v Wales"},
              "runners": [{"selectionId": 500001, "runnerName": "England", "handicap": 0},
                          {"selectionId": 500002, "runnerName": "Wales", "handicap": 0}]},
}


def _catalogue_br(mids):
    return [_BR_CATALOGUE[m] for m in mids if m in _BR_CATALOGUE]


def _sync_br(db):
    return CatalogueSync(db, navigation_transport=lambda: _menu_basket_rugby(),
                         catalogue_transport=_catalogue_br)


def test_sync_basket(db):
    # Solo Basket (7522): persiste sport/evento E mercato/selezioni dal catalogue.
    _sync_br(db).sync(["Basket"])
    assert db.count_active("betfair_sports") == 1
    ids = {e["event_id"] for e in db.get_events()}
    assert ids == {"eb"}                       # niente Rugby (fuori scope)
    ev = db.get_events()[0]
    assert ev["event_type_id"] == "7522"
    assert ev["participant_1"] == "Lakers" and ev["participant_2"] == "Celtics"
    # fase catalogue esercitata: mercato 1.700 e le sue 2 selezioni persistiti
    assert db.count_active("betfair_markets") == 1
    assert db.count_active("betfair_selections") == 2
    assert {s["runner_name"] for s in db.get_selections("1.700")} == {"Lakers", "Celtics"}


def test_sync_rugby(db):
    # Solo Rugby Union (5): evento + mercato/selezioni dal catalogue.
    _sync_br(db).sync(["Rugby Union"])
    ids = {e["event_id"] for e in db.get_events()}
    assert ids == {"er"}                        # niente Basket (fuori scope)
    assert db.get_events()[0]["event_type_id"] == "5"
    assert db.count_active("betfair_markets") == 1
    assert {s["runner_name"] for s in db.get_selections("1.500")} == {"England", "Wales"}


def test_sync_basket_rugby_insieme_non_interferiscono(db):
    # Sincronizzare entrambi mantiene entrambi attivi (scope per event_type_id).
    _sync_br(db).sync(["Basket", "Rugby Union"])
    ids = {e["event_id"] for e in db.get_events()}
    assert ids == {"eb", "er"}
    assert db.count_active("betfair_events") == 2
    assert db.count_active("betfair_markets") == 2
    assert db.count_active("betfair_selections") == 4


def test_sync_un_solo_sport_non_disattiva_altro_basket_rugby(db):
    # Esercita la DEACTIVATION-SCOPING (deactivate_unseen scoped per event_type_id) sui due
    # nuovi sport: sync entrambi, poi solo Basket → il Rugby resta attivo (CodeRabbit #178 §3).
    s = _sync_br(db)
    s.sync(["Basket", "Rugby Union"])
    assert db.count_active("betfair_events") == 2
    s.sync(["Basket"])                          # ri-sincronizza SOLO Basket
    by_id = {e["event_id"]: e["active"] for e in db.get_events()}
    assert by_id["eb"] == 1                     # Basket rivisto → attivo
    assert by_id["er"] == 1                     # Rugby NON toccato (fuori scope) → ancora attivo
    # e le selezioni del Rugby (mercato 1.500) restano attive (scope per market_id)
    assert all(s_["active"] == 1 for s_ in db.get_selections("1.500"))


def test_sync_marker_avanza_e_disattiva_record_spariti(db):
    s = _sync(db)
    s.sync(["Calcio"])
    # seconda sync: il menu non ha più il mercato 1.101 (evento sparito)
    empty = CatalogueSync(db, navigation_transport=lambda: {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": []}]},
        catalogue_transport=lambda mids: [])
    empty.sync(["Calcio"])
    assert db.count_active("betfair_events") == 0      # evento non più visto → inattivo
    assert db.count_active("betfair_markets") == 0


def test_sync_un_solo_sport_non_disattiva_altri(db):
    # Sync Calcio+Tennis, poi sync solo Calcio: il Tennis resta attivo.
    _sync(db).sync(["Calcio", "Tennis"])
    assert db.count_active("betfair_events") == 2
    _sync(db).sync(["Calcio"])               # ri-sincronizza solo Calcio
    ids = {e["event_id"]: e["active"] for e in db.get_events()}
    assert ids["e1"] == 1     # Calcio rivisto
    assert ids["e2"] == 1     # Tennis NON toccato (fuori scope)


# ── read-only: nessuna operazione di scommessa ────────────────────────────────

def test_sync_operazioni_sono_read_only():
    # Le operazioni dichiarate dal client non sono di scommessa.
    from xtrader_bridge.betfair import catalogue_client as cc
    assert safety.is_forbidden_betting_op(cc.NAVIGATION_OP) is False
    assert safety.is_forbidden_betting_op(cc.CATALOGUE_OP) is False


def test_sync_passa_dal_guard_read_only(db, monkeypatch):
    # Se il guard iniziasse a considerare vietata un'operazione del sync, sync alza.
    monkeypatch.setattr(safety, "is_forbidden_betting_op", lambda op: True)
    with pytest.raises(safety.ReadOnlyViolation):
        _sync(db).sync(["Calcio"])


# ── selezioni di un mercato sparito vengono disattivate (Codex) ───────────────

def test_selezioni_di_mercato_sparito_disattivate(db):
    _sync(db).sync(["Calcio"])
    assert db.count_active("betfair_selections") == 3
    # seconda sync: il mercato 1.101 non c'è più nel menu
    empty = CatalogueSync(db, navigation_transport=lambda: {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": []}]},
        catalogue_transport=lambda mids: [])
    empty.sync(["Calcio"])
    assert db.count_active("betfair_markets") == 0
    assert db.count_active("betfair_selections") == 0   # niente SelectionId stantii


# ── transport di default: niente sync "a vuoto" (Codex) ───────────────────────

def test_sync_senza_transport_ne_sessione_fallisce(db):
    # Nessun transport iniettato e nessuna sessione/app_key → errore esplicito.
    with pytest.raises(RuntimeError):
        CatalogueSync(db).sync(["Calcio"])


# ── rollback su fallimento del catalogue (Codex) ──────────────────────────────

def test_catalogue_fallito_fa_rollback(db):
    _sync(db).sync(["Calcio"])                       # stato iniziale: e1 attivo
    before_events = {e["event_id"] for e in db.get_events()}

    def _boom(mids):
        raise RuntimeError("catalogue di rete fallito (simulato)")

    # nuova sync con un EVENTO NUOVO ma catalogue che esplode a metà
    menu2 = {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": [
            {"type": "EVENT", "id": "e_new", "name": "Roma v Lazio", "children": [
                {"type": "MARKET", "id": "1.999", "name": "Match Odds",
                 "marketType": "MATCH_ODDS"}]}]}]}
    failing = CatalogueSync(db, navigation_transport=lambda: menu2,
                            catalogue_transport=_boom)
    with pytest.raises(RuntimeError):
        failing.sync(["Calcio"])
    # rollback: l'evento nuovo NON è stato scritto e quello vecchio resta com'era
    after_events = {e["event_id"] for e in db.get_events()}
    assert after_events == before_events
    assert "e_new" not in after_events
    assert db.count_active("betfair_events") == 1   # e1 ancora attivo (non disattivato)


# ── metadati mercato dal catalogue persistiti (Codex) ─────────────────────────

def test_market_type_dal_catalogue_persistito(db):
    # Il menu non porta marketType; il catalogue sì → deve finire nel DB.
    menu = {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": [
            {"type": "EVENT", "id": "e1", "name": "Inter v Milan", "children": [
                {"type": "MARKET", "id": "1.101", "name": "Match Odds"}]}]}]}  # niente marketType
    cat = [{"marketId": "1.101", "marketName": "Match Odds",
            "description": {"marketType": "MATCH_ODDS"},
            "event": {"id": "e1", "name": "Inter v Milan"},
            "runners": [{"selectionId": 1, "runnerName": "Inter", "handicap": 0}]}]
    CatalogueSync(db, navigation_transport=lambda: menu,
                  catalogue_transport=lambda mids: cat).sync(["Calcio"])
    market = db.fetchall("betfair_markets")[0]
    assert market["market_type"] == "MATCH_ODDS"


# ── endpoint italiani (Codex) ─────────────────────────────────────────────────

def test_endpoint_navigation_it_catalogue_com():
    # NAV sull'host .it; CATALOGUE su api.betfair.com (docs Betfair Italy).
    from xtrader_bridge.betfair import catalogue_client as cc
    assert "api.betfair.it" in cc._NAV_URL and "/it/" in cc._NAV_URL
    assert cc._CATALOGUE_URL == "https://api.betfair.com/exchange/betting/json-rpc/v1"


# ── #184 M11: contesto TLS esplicito sui transport di default ─────────────────

class _FakeResp:
    """Risposta fittizia per urlopen nei test (context manager)."""

    def __init__(self, body=b'{"ok": true}'):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _patch_urlopen(monkeypatch):
    """Patcha urllib.request.urlopen catturando i kwargs (context/timeout)."""
    import urllib.request
    captured = {}

    def _fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        captured["timeout"] = timeout
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return captured


def _assert_verified_tls(ctx):
    import ssl
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED      # verifica certificato server attiva
    assert ctx.check_hostname is True                # hostname verificato


def test_http_post_json_usa_tls_context_esplicito(monkeypatch):
    """#184 M11: il POST read-only passa un `ssl.SSLContext` ESPLICITO (verificato) a urlopen, così
    un eventuale override globale del default non indebolisce la chiamata con credenziali.

    Fail-first: senza `context=`, urlopen riceveva None."""
    from xtrader_bridge.betfair import catalogue_client as cc
    captured = _patch_urlopen(monkeypatch)
    out = cc._http_post_json("https://api.betfair.it/x", {"a": 1}, "tok", "key")
    assert out == {"ok": True}
    assert captured["timeout"] == cc._HTTP_TIMEOUT
    _assert_verified_tls(captured["context"])


def test_http_navigation_usa_tls_context_esplicito(monkeypatch):
    """#184 M11: anche il GET del navigation menu passa un `ssl.SSLContext` esplicito (verificato).

    Fail-first: senza `context=`, urlopen riceveva None."""
    from xtrader_bridge.betfair import catalogue_client as cc
    captured = _patch_urlopen(monkeypatch)
    out = cc._http_navigation("tok", "key")
    assert out == {"ok": True}
    assert captured["timeout"] == cc._HTTP_TIMEOUT
    _assert_verified_tls(captured["context"])


# ── default transport catalogue: errori e chunking (Codex) ────────────────────

def test_jsonrpc_result_solleva_su_errore_e_result_mancante():
    from xtrader_bridge.betfair import catalogue_client as cc
    with pytest.raises(RuntimeError):
        cc._jsonrpc_result({"error": {"code": -32099,
                                      "data": {"APINGException": {"errorCode": "TOO_MUCH_DATA"}}}})
    with pytest.raises(RuntimeError):
        cc._jsonrpc_result({})                      # niente result
    with pytest.raises(RuntimeError):
        cc._jsonrpc_result("non un dict")
    assert cc._jsonrpc_result({"result": [{"marketId": "1.1"}]}) == [{"marketId": "1.1"}]


def test_http_catalogue_chunk_e_aggrega():
    from xtrader_bridge.betfair import catalogue_client as cc
    calls = []

    def _poster(url, payload, token, app_key):
        chunk = payload["params"]["filter"]["marketIds"]
        calls.append(len(chunk))
        # ogni market torna un item con quel marketId
        return {"result": [{"marketId": m} for m in chunk]}

    ids = [f"1.{i}" for i in range(250)]            # 250 market → 3 chunk (100,100,50)
    out = cc._http_catalogue(ids, "tok", "key", _poster=_poster)
    assert calls == [100, 100, 50]
    assert len(out) == 250


def test_http_catalogue_solleva_su_errore_api():
    from xtrader_bridge.betfair import catalogue_client as cc

    def _poster(url, payload, token, app_key):
        return {"error": {"code": -32099}}

    with pytest.raises(RuntimeError):
        cc._http_catalogue(["1.1"], "tok", "key", _poster=_poster)


# ── fail-closed su selezione sport vuota (Codex) ──────────────────────────────

def test_sync_sport_vuoti_o_ignoti_fallisce(db):
    with pytest.raises(ValueError):
        _sync(db).sync([])                      # lista vuota
    with pytest.raises(ValueError):
        _sync(db).sync(["Cricket", "Freccette"])  # nomi non riconosciuti
    # e non deve aver registrato alcuna sync run
    assert db.fetchall("betfair_sync_runs") == []


# ── marker allocato dentro la transazione: serializzazione (Codex) ────────────

def test_marker_allocato_dentro_la_transazione(db):
    seen = {}

    def _nav():
        seen["tx_depth"] = db._tx_depth      # la sync gira dentro la transazione
        return _menu()

    CatalogueSync(db, navigation_transport=_nav,
                  catalogue_transport=lambda mids: _catalogue()).sync(["Calcio"])
    assert seen["tx_depth"] >= 1


# ── dettagli evento dal catalogue persistiti (Codex) ──────────────────────────

def test_evento_arricchito_dal_catalogue(db):
    # Il menu ha l'evento SENZA nome; il catalogue porta nome/partecipanti.
    menu = {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": [
            {"type": "EVENT", "id": "e1", "children": [
                {"type": "MARKET", "id": "1.101", "name": "Match Odds"}]}]}]}
    cat = [{"marketId": "1.101", "marketName": "Match Odds",
            "description": {"marketType": "MATCH_ODDS"},
            "event": {"id": "e1", "name": "Inter v Milan",
                      "openDate": "2026-07-01T18:00:00Z"},
            "runners": [{"selectionId": 1, "runnerName": "Inter", "handicap": 0}]}]
    CatalogueSync(db, navigation_transport=lambda: menu,
                  catalogue_transport=lambda mids: cat).sync(["Calcio"])
    ev = db.get_events()[0]
    assert ev["name"] == "Inter v Milan"
    assert ev["participant_1"] == "Inter" and ev["participant_2"] == "Milan"
    assert ev["event_type_id"] == "1"        # sport preservato dal menu


# ── #184 LOW: sync che incontra un token scaduto pulisce la sessione ──────────

def _expired_apierror():
    from xtrader_bridge.betfair.catalogue_client import BetfairApiError
    return BetfairApiError("Errore listMarketCatalogue (code=-32099 INVALID_SESSION_INFORMATION).",
                           error_code="INVALID_SESSION_INFORMATION")


def test_sync_su_sessione_scaduta_slogga_la_sessione(db):
    from xtrader_bridge.betfair.catalogue_client import BetfairApiError
    from xtrader_bridge.betfair.session import BetfairSession

    sess = BetfairSession()
    sess.set_token("token-ancora-in-ram")
    assert sess.is_logged_in is True

    def _nav_scaduto():
        raise _expired_apierror()

    cs = CatalogueSync(db, session=sess, navigation_transport=_nav_scaduto,
                       catalogue_transport=lambda mids: [])
    with pytest.raises(BetfairApiError):
        cs.sync(["Calcio"])
    # la sessione è stata pulita: is_logged_in torna False (la GUI mostrerà 'disconnesso')
    assert sess.is_logged_in is False
    assert sess.token is None
    # rollback: nessuna sync run registrata
    assert db.fetchall("betfair_sync_runs") == []


def test_sync_su_errore_api_non_di_scadenza_non_slogga(db):
    from xtrader_bridge.betfair.catalogue_client import BetfairApiError
    from xtrader_bridge.betfair.session import BetfairSession

    sess = BetfairSession()
    sess.set_token("token-vivo")

    def _nav_too_much():
        raise BetfairApiError("Errore (code=-32099 TOO_MUCH_DATA).", error_code="TOO_MUCH_DATA")

    cs = CatalogueSync(db, session=sess, navigation_transport=_nav_too_much,
                       catalogue_transport=lambda mids: [])
    with pytest.raises(BetfairApiError):
        cs.sync(["Calcio"])
    # errore generico: la sessione NON va toccata (resta loggata)
    assert sess.is_logged_in is True
    assert sess.token == "token-vivo"


def test_sync_errore_non_api_non_tocca_la_sessione(db):
    # Un RuntimeError "puro" (non BetfairApiError, es. rete) non è un segnale di scadenza:
    # la sessione resta invariata.
    from xtrader_bridge.betfair.session import BetfairSession

    sess = BetfairSession()
    sess.set_token("token-vivo")

    def _nav_rete():
        raise RuntimeError("connessione interrotta (simulata)")

    cs = CatalogueSync(db, session=sess, navigation_transport=_nav_rete,
                       catalogue_transport=lambda mids: [])
    with pytest.raises(RuntimeError):
        cs.sync(["Calcio"])
    assert sess.is_logged_in is True


def test_jsonrpc_result_porta_lerror_code_su_scadenza():
    # _jsonrpc_result solleva un BetfairApiError che ESPONE l'errorCode APING grezzo,
    # così il livello sopra può riconoscere la scadenza.
    from xtrader_bridge.betfair import catalogue_client as cc
    with pytest.raises(cc.BetfairApiError) as ei:
        cc._jsonrpc_result({"error": {"code": -32099,
                                      "data": {"APINGException":
                                               {"errorCode": "INVALID_SESSION_INFORMATION"}}}})
    assert ei.value.error_code == "INVALID_SESSION_INFORMATION"
