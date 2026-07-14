"""Test della fonte UNICA degli sport del blocco personale (issue #86 PR-P9).

Copre la mappa canonica sport→event_type_id, la normalizzazione case-insensitive e la
reverse-map event_type_id→sport. Lo sport resta usato dal parser (`event_type_id`) e dalla
risoluzione ID del dizionario locale, anche dopo la rimozione della funzione «Betfair Sync».
"""

from xtrader_bridge import sports


# ── mappa canonica ────────────────────────────────────────────────────────────

def test_sports_event_type_canonico():
    assert sports.SPORTS_EVENT_TYPE == {
        "Calcio": "1", "Tennis": "2", "Basket": "7522", "Rugby Union": "5",
        "Football Americano": "6423",
    }


def test_sports_ordine_visualizzazione():
    # L'ordine (tuple da dict) è quello di visualizzazione in GUI. Football Americano
    # è aggiunto IN CODA (issue #4 PR-1): non riordina gli sport preesistenti.
    assert sports.SPORTS == ("Calcio", "Tennis", "Basket", "Rugby Union", "Football Americano")


# ── normalize_sport ─────────────────────────────────────────────────────────────

def test_normalize_sport_case_insensitive_e_spazi():
    assert sports.normalize_sport("calcio") == "Calcio"
    assert sports.normalize_sport("  TENNIS ") == "Tennis"
    assert sports.normalize_sport("rugby union") == "Rugby Union"
    assert sports.normalize_sport("  football americano ") == "Football Americano"


def test_normalize_sport_vuoto_o_ignoto_none():
    assert sports.normalize_sport("") is None
    assert sports.normalize_sport(None) is None
    assert sports.normalize_sport("Pallavolo") is None


def test_is_supported_sport():
    assert sports.is_supported_sport("Basket") is True
    assert sports.is_supported_sport("basket") is True
    assert sports.is_supported_sport("") is False
    assert sports.is_supported_sport("Cricket") is False


# ── event_type_id_for_sport ─────────────────────────────────────────────────────

def test_event_type_id_for_sport_noto():
    assert sports.event_type_id_for_sport("Calcio") == "1"
    assert sports.event_type_id_for_sport("tennis") == "2"
    assert sports.event_type_id_for_sport("Basket") == "7522"
    assert sports.event_type_id_for_sport("Rugby Union") == "5"
    assert sports.event_type_id_for_sport("Football Americano") == "6423"
    assert sports.event_type_id_for_sport("football americano") == "6423"


def test_event_type_id_for_sport_ignoto_none():
    assert sports.event_type_id_for_sport("") is None
    assert sports.event_type_id_for_sport("Hockey") is None


# ── reverse map event_type_id → sport (harvest nomi squadra #282) ───────────────

def test_sport_for_event_type_id_inverso_esatto():
    # È l'inverso esatto di SPORTS_EVENT_TYPE per tutti gli sport supportati.
    for sport, etid in sports.SPORTS_EVENT_TYPE.items():
        assert sports.sport_for_event_type_id(etid) == sport
    # accetta anche l'id come intero (str() interno)
    assert sports.sport_for_event_type_id(1) == "Calcio"
    # lock esplicito del nuovo mapping (issue #4 PR-1): 6423 → Football Americano
    assert sports.sport_for_event_type_id("6423") == "Football Americano"
    assert sports.sport_for_event_type_id(6423) == "Football Americano"


def test_sport_for_event_type_id_ignoto_none():
    # id non riconosciuto / vuoto / None → None (fail-closed: nessun harvest)
    assert sports.sport_for_event_type_id("999") is None
    assert sports.sport_for_event_type_id("") is None
    assert sports.sport_for_event_type_id(None) is None


# ── anti-drift: bijezione sport ⇄ event_type_id (issue #4) ──────────────────────

def test_event_type_id_unici_nessuna_collisione():
    # Ogni sport DEVE avere un event_type_id distinto: un id duplicato romperebbe
    # silenziosamente la reverse-map (_EVENT_TYPE_TO_SPORT) mappando l'id a UN solo
    # sport. Aggiungendo Football Americano (6423) questo test fallirebbe se il nuovo
    # id collidesse con uno esistente (1/2/5/7522).
    etids = list(sports.SPORTS_EVENT_TYPE.values())
    assert len(etids) == len(set(etids)), f"event_type_id duplicati: {etids}"


def test_sports_e_reverse_map_coprono_gli_stessi_sport():
    # Anti-drift: SPORTS (ordine GUI), le chiavi di SPORTS_EVENT_TYPE e la reverse-map
    # devono descrivere ESATTAMENTE lo stesso insieme di sport. Un nuovo sport aggiunto
    # solo alla mappa ma non riflesso nella reverse-map (o viceversa) è un bug.
    assert set(sports.SPORTS) == set(sports.SPORTS_EVENT_TYPE)
    for sport, etid in sports.SPORTS_EVENT_TYPE.items():
        assert sports.sport_for_event_type_id(etid) == sport      # ida→sport
        assert sports.event_type_id_for_sport(sport) == etid       # sport→id


def test_sport_for_event_type_id_falsy_non_none_non_collassa():
    # Fissa la semantica del check esplicito su None (review GPT-5.5/GLM/Fable): un id
    # FALSY ma NON None (es. `0`) viene cercato come `"0"` — NON collassato a `""` dal
    # vecchio `or ""` — quindi resta `None` perché nessuno sport ha id 0, ma per il motivo
    # giusto (se Betfair introducesse un id `0`, non verrebbe scambiato per «id assente»).
    assert sports.sport_for_event_type_id(0) is None       # int falsy → "0", non ""
    assert sports.sport_for_event_type_id("0") is None      # str "0" → None
    # controprova: gli id reali (anche passati come int) restano risolti
    assert sports.sport_for_event_type_id(1) == "Calcio"
