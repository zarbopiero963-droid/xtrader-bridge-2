"""Test hard #318 — L1-4 (ReDoS parser) + L2-2 (`_is_placeholder` permissivo).

Esercitano il codice reale:
- L1-4: le regex `parser._META_TAIL`/`_TRAILING_EMOJI` avevano backtracking QUADRATICO su input
  ostile (~40KB → 11.7s). Il fix CAPPA l'input al call-site (`_MAX_META_INPUT`) senza toccare le
  regex: un input patologico è respinto/limitato → nessun ReDoS. Qui si prova sia il
  comportamento (cap deterministico) sia il tempo (bound generoso, anti-flaky) sia la
  correttezza invariata sui casi reali.
- L2-2: `value_maps._is_placeholder` usa ora `or` (non `and`): un placeholder PARZIALE/troncato
  è comunque escluso dalla value-map (fail-closed).
"""

import time

from xtrader_bridge import parser as p
from xtrader_bridge import value_maps as vm


# ── L1-4: anti-ReDoS via cap di lunghezza ─────────────────────────────────────

def test_clean_team_side_scarta_input_sovradimensionato():
    # Un «lato» oltre il cap non è una squadra reale → None, senza dare l'input alle regex.
    over = "A" * (p._MAX_META_INPUT + 1)
    assert p._clean_team_side(over) is None
    assert p._clean_team_side(None) is None


def test_clean_team_side_ammette_al_limite_del_cap():
    # Esattamente al cap resta processabile (un nome lungo ma plausibile non va perso).
    ok = "B" * p._MAX_META_INPUT
    assert p._clean_team_side(ok) == ok               # nessuna coda metadati → invariato


def test_clean_team_side_redos_bounded_nel_tempo():
    # Regressione ReDoS: input patologico (coda «90+2 » ripetuta ~50KB) NON deve impiantare il
    # parser. Bound generoso (0.5s) per non essere flaky: senza cap erano ~11.7s.
    evil = "T " + ("90+2 " * 10000) + "!"
    t0 = time.perf_counter()
    p._clean_team_side(evil)
    assert time.perf_counter() - t0 < 0.5


def test_parse_message_vs_line_redos_bounded():
    # La stessa protezione lungo la pipeline reale: riga 🆚 con coda ostile enorme → parse veloce.
    msg = "P.Bet. 1\n🆚 Real Madrid 2 - 1 " + ("90+2 " * 10000) + "!"
    t0 = time.perf_counter()
    p.parse_message(msg)
    assert time.perf_counter() - t0 < 1.0


def test_parse_message_signal_type_emoji_redos_bounded():
    # signal_type con run enorme di emoji → strip cappato, nessun blowup.
    msg = "P.Bet. " + ("\U0001F600 " * 10000) + "x"
    t0 = time.perf_counter()
    p.parse_message(msg)
    assert time.perf_counter() - t0 < 1.0


def test_clean_team_side_correttezza_casi_reali_invariata():
    # Il cap NON cambia il comportamento sui casi reali (code di tempo/stato tolte come prima).
    assert p._clean_team_side("Barcelona 46m FT") == "Barcelona"
    assert p._clean_team_side("Barcelona (HT)") == "Barcelona"
    assert p._clean_team_side("Barcelona(90+2')") == "Barcelona"
    assert p._clean_team_side("Real Madrid") == "Real Madrid"
    assert p._clean_team_side("46m") is None            # solo metadati → non è una squadra


# ── L2-2: `_is_placeholder` fail-closed (`or`, non `and`) ──────────────────────

def test_is_placeholder_riconosce_anche_i_parziali():
    assert vm._is_placeholder("{HOME_TEAM}") is True    # completo
    assert vm._is_placeholder("{HOME_TEAM") is True     # troncato: manca `}` → ora RICONOSCIUTO
    assert vm._is_placeholder("HOME_TEAM}") is True      # manca `{` → riconosciuto
    assert vm._is_placeholder("Milan") is False          # valore reale
    assert vm._is_placeholder("") is False
    assert vm._is_placeholder(None) is False


def test_value_map_esclude_placeholder_parziale():
    # Un valore col placeholder PARZIALE non deve entrare nella value-map come valore reale.
    m = vm.value_map_from_pairs([("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")])
    assert m.get("gg") == "Goal/Goal"
    assert m.get("ok") == "Milan"
    # `value_map_from_pairs` non filtra i placeholder (lo fa il chiamante via `_is_placeholder`):
    # qui verifichiamo che, filtrando come in produzione, il parziale sparisce.
    pairs = [("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")]
    filtered = vm.value_map_from_pairs([(a, v) for a, v in pairs if not vm._is_placeholder(v)])
    assert "bad" not in filtered and filtered.get("gg") == "Goal/Goal"


# ── L1-4 (estensione): riga `P.Bet.` — search di riga + `_STATUS_TAIL` su input non cappato ───

def test_parse_message_pbet_line_redos_bounded():
    # La search di riga `P\.Bet\.\s+(.+?)(?:…|$)` E `_STATUS_TAIL.sub` giravano su input NON
    # cappato → backtracking QUADRATICO (una riga ~40KB di whitespace interno → ~9s solo la
    # search, ~5.8s in `_STATUS_TAIL`). Ora la riga `P.Bet.` è cappata a monte (`_MAX_META_INPUT`):
    # input patologico → parse veloce. Bound generoso (1.0s) vs i ~9s del codice pre-fix.
    msg = "P.Bet. a" + (" " * 40000) + "b"
    t0 = time.perf_counter()
    p.parse_message(msg)
    assert time.perf_counter() - t0 < 1.0


def test_parse_message_status_e_emoji_strip_preservati_su_alias_reale():
    # Il cap di riga NON cambia il comportamento sugli alias reali (corti): LIVE/PRE tolti,
    # emoji finale tolta, alias pulito invariato.
    assert p.parse_message("P.Bet. GG LIVE")["signal_type"] == "GG"
    assert p.parse_message("P.Bet. Over 2.5 pre")["signal_type"] == "Over 2.5"
    assert p.parse_message("P.Bet. GG \U0001F525")["signal_type"] == "GG"       # 🔥 finale rimossa
    assert p.parse_message("P.Bet. Goal")["signal_type"] == "Goal"


def test_parse_message_alias_sovracap_non_e_piazzabile():
    # Un alias oltre il cap non passa per le regex → nessun signal_type piazzabile (fail-closed):
    # non resta l'alias grezzo (che non mapperebbe comunque) e non innesca le regex quadratiche.
    big = "x" * (p._MAX_META_INPUT + 50)
    st = p.parse_message("P.Bet. " + big).get("signal_type", "")
    assert st == "" and st != big


def test_parse_message_pbet_riga_al_limite_del_cap():
    # Boundary (review GLM 5.2): una riga `P.Bet.` lunga ESATTAMENTE `_MAX_META_INPUT` è ancora
    # processata (guard `len(line) <= cap`); a cap+1 viene scartata (fail-closed). Verifica il confine.
    alias_len = p._MAX_META_INPUT - len("P.Bet. ")
    at_cap = "P.Bet. " + ("G" * alias_len)
    assert len(at_cap) == p._MAX_META_INPUT
    assert p.parse_message(at_cap)["signal_type"] == "G" * alias_len       # al limite → processata
    over = "P.Bet. " + ("G" * (alias_len + 1))
    assert len(over) == p._MAX_META_INPUT + 1
    assert p.parse_message(over).get("signal_type", "") == ""              # oltre il limite → scartata
