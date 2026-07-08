"""Test delle CONDIZIONI di gate del Parser Personalizzato (PR-1).

Esercitano il codice reale:
- modello `custom_parser.Condition` / `CustomParserDef` (round-trip, retro-compat, validazione,
  `active_conditions`);
- gate `custom_parser_engine.conditions_pass` e integrazione in `matches_message`.

Obiettivo: il parser scatta SOLO se il messaggio soddisfa le condizioni (contiene / NON contiene,
modo E/O), con match case-insensitive e tollerante agli spazi. Niente GUI, niente rete.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as eng


def _parser(conditions=None, mode="all"):
    """Parser minimo che estrae EventName obbligatorio (così `matches_message` dipende dal testo)."""
    return cp.CustomParserDef(
        name="P",
        rules=[cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True)],
        conditions=list(conditions or []),
        conditions_mode=mode,
    )


# ── modello: round-trip + retro-compatibilità ─────────────────────────────────

def test_round_trip_preserva_condizioni():
    d = _parser([cp.Condition(text="OVER SUCCESSIVO"), cp.Condition(text="BANCA", negate=True)], mode="any")
    again = cp.CustomParserDef.from_dict(d.to_dict())
    assert again.to_dict() == d.to_dict()
    assert [(c.text, c.negate) for c in again.conditions] == [("OVER SUCCESSIVO", False), ("BANCA", True)]
    assert again.conditions_mode == "any"


def test_round_trip_json_condizioni_unicode():
    d = _parser([cp.Condition(text="⚽ 0 - 1")], mode="all")
    txt = d.to_json()
    assert "\\u" not in txt                                   # unicode leggibile
    assert cp.CustomParserDef.from_json(txt).to_dict() == d.to_dict()


def test_retro_compat_file_senza_condizioni():
    """File salvato PRIMA della feature (nessuna chiave `conditions`) → default vuoti, nessun gate."""
    old = cp.CustomParserDef.from_dict({"name": "x", "rules": [{"target": "EventName", "start_after": "a"}]})
    assert old.conditions == [] and old.conditions_mode == "all"


def test_conditions_mode_malformato_fail_closed_all():
    # Un modo ignoto/corrotto da file manomesso → "all" (gate più restrittivo), non un modo a caso.
    d = cp.CustomParserDef.from_dict({
        "name": "x", "rules": [{"target": "EventName", "start_after": "a"}],
        "conditions": [{"text": "X"}], "conditions_mode": "qualcosa"})
    assert d.conditions_mode == "all"


def test_negate_malformato_fail_closed_false():
    d = cp.CustomParserDef.from_dict({
        "name": "x", "rules": [{"target": "EventName", "start_after": "a"}],
        "conditions": [{"text": "X", "negate": "boh"}]})
    assert d.conditions[0].negate is False


def test_active_conditions_ignora_testo_vuoto():
    d = _parser([cp.Condition(text="X"), cp.Condition(text="   "), cp.Condition(text="")])
    assert [c.text for c in d.active_conditions()] == ["X"]


def test_validate_condizione_testo_vuoto_e_modo_invalido():
    d = _parser([cp.Condition(text="  ")], mode="all")
    errs = cp.validate_parser_def(d)
    assert any("testo vuoto" in e for e in errs)
    d2 = _parser([cp.Condition(text="X")], mode="xxx")
    assert any("Modo condizioni non valido" in e for e in cp.validate_parser_def(d2))


def test_validate_parser_valido_con_condizioni():
    d = _parser([cp.Condition(text="OVER SUCCESSIVO"), cp.Condition(text="BANCA", negate=True)], mode="all")
    assert cp.validate_parser_def(d) == []


# ── engine: conditions_pass ───────────────────────────────────────────────────

def test_nessuna_condizione_passa_sempre():
    assert eng.conditions_pass(_parser([]), "qualsiasi") is True


def test_contiene_presente_e_assente():
    d = _parser([cp.Condition(text="OVER SUCCESSIVO")])
    assert eng.conditions_pass(d, "P.Bet. OVER SUCCESSIVO ✅") is True
    assert eng.conditions_pass(d, "P.Bet. PREMACHT 0,5HT") is False


def test_non_contiene():
    d = _parser([cp.Condition(text="BANCA", negate=True)])
    assert eng.conditions_pass(d, "segnale in punta") is True        # BANCA assente → ok
    assert eng.conditions_pass(d, "segnale in BANCA") is False       # BANCA presente → fallisce


def test_case_insensitive_e_spazi_tolleranti():
    d = _parser([cp.Condition(text="over  successivo")])             # doppio spazio + minuscolo
    assert eng.conditions_pass(d, "P.Bet. 70/80 OVER SUCCESSIVO ✅") is True


def test_modo_all_tutte_devono_valere():
    d = _parser([cp.Condition(text="OVER SUCCESSIVO"), cp.Condition(text="⚽ 0 - 1")], mode="all")
    assert eng.conditions_pass(d, "OVER SUCCESSIVO ... ⚽ 0 - 1 ...") is True
    assert eng.conditions_pass(d, "OVER SUCCESSIVO ... ⚽ 0 - 2 ...") is False   # manca la 2ª


def test_modo_any_basta_una():
    d = _parser([cp.Condition(text="0,5HT"), cp.Condition(text="PREMACHT 0,5HT")], mode="any")
    assert eng.conditions_pass(d, "P.Bet. PREMACHT 0,5HT ✅") is True
    assert eng.conditions_pass(d, "P.Bet. 0,5HT ✅") is True
    assert eng.conditions_pass(d, "P.Bet. OVER SUCCESSIVO") is False


def test_condizione_testo_vuoto_non_gatta():
    # Una condizione a testo vuoto è ignorata → non deve far matchare/scartare nulla.
    d = _parser([cp.Condition(text="   ")])
    assert eng.conditions_pass(d, "qualsiasi") is True


# ── engine: integrazione in matches_message ───────────────────────────────────

def test_matches_message_gate_fallito_anche_con_estrazione_valida():
    """Mutation-guard: il gate condizioni deve avere PRIORITÀ. Un messaggio con EventName
    estraibile (che passerebbe il gate di riconoscimento) NON deve matchare se le condizioni
    falliscono. Sul vecchio codice (senza gate) questo tornava True → il test fallirebbe."""
    d = _parser([cp.Condition(text="OVER SUCCESSIVO")])
    ok = "P.Bet. OVER SUCCESSIVO\n🆚 Nottm Forest v Everton\n"
    no = "P.Bet. PREMACHT 0,5HT\n🆚 Al-Hilal v Al-Nassr\n"          # EventName estraibile, ma niente OVER SUCCESSIVO
    assert eng.matches_message(d, ok) is True
    assert eng.matches_message(d, no) is False


def test_matches_message_senza_condizioni_invariato():
    """Nessuna condizione → comportamento identico a prima (il gate non cambia nulla)."""
    d = _parser([])
    assert eng.matches_message(d, "🆚 A v B\n") is True
    assert eng.matches_message(d, "nessun delimitatore") is False
