"""Test delle CONDIZIONI di gate del Parser Personalizzato (PR-1).

Esercitano il codice reale:
- modello `custom_parser.Condition` / `CustomParserDef` (round-trip, retro-compat, validazione,
  `active_conditions`);
- gate `custom_parser_engine.conditions_pass` e integrazione in `matches_message`.

Obiettivo: il parser scatta SOLO se il messaggio soddisfa le condizioni (contiene / NON contiene,
modo E/O), con match case-insensitive e tollerante agli spazi. Niente GUI, niente rete.
"""

import dataclasses

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

def _non_default(value):
    """Restituisce un valore DIVERSO dal `value` di default passato, ispezionando il valore
    RUNTIME (non l'annotazione `Field.type`): così è immune a `from __future__ import
    annotations` (dove `f.type` sarebbe una stringa) e non dipende dai nomi dei campi. Un tipo
    di default non ancora gestito fa fallire il test ESPLICITAMENTE, forzando ad aggiornarlo
    quando `Condition` guadagna un campo di tipo nuovo (guardia «campo futuro non coperto»)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return (value or "") + "_SENTINELLA"
    if isinstance(value, (int, float)):
        return value + 1
    raise AssertionError(
        f"_non_default non gestisce il tipo del default {value!r}: aggiorna il test per il "
        "nuovo campo di Condition (copertura round-trip field-exhaustive).")


def test_condition_round_trip_field_exhaustive():
    """Nota GPT-5.5/GLM #390: guardia FIELD-EXHAUSTIVE sul round-trip di `Condition`, robusta.

    Sintesi delle due note di review: itera i campi PER NOME (`dataclasses.fields`) e assegna
    a ciascuno un valore NON-default derivato dal default RUNTIME (`_non_default`, via
    `isinstance` sul valore — NON su `Field.type`, quindi niente falsi rossi con annotazioni
    stringa). Copre così TUTTI i campi attuali con valori non-default, e un campo futuro non
    coperto da `to_dict`/`from_dict` (o di tipo non gestito) fa fallire il test invece di
    perdere dati in silenzio. Oggi `Condition` ha `text` e `negate`; entrambi sono esercitati
    con valori non-default e verificati dal round-trip (dataclass `__eq__`)."""
    base = cp.Condition()
    kwargs = {f.name: _non_default(getattr(base, f.name)) for f in dataclasses.fields(cp.Condition)}
    original = cp.Condition(**kwargs)
    # to_dict serializza OGNI campo del dataclass (un campo assente qui = perdita silenziosa)…
    assert set(original.to_dict()) == {f.name for f in dataclasses.fields(cp.Condition)}
    # …e il round-trip preserva il valore non-default di OGNI campo.
    assert cp.Condition.from_dict(original.to_dict()) == original


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


def test_nessuna_condizione_passa_sempre_anche_in_modo_any():
    # Gap GLM #390: lista vuota → True a prescindere dal modo (il gate esce PRIMA del
    # controllo E/O). Guardia: se un domani il modo venisse letto prima del check-vuoto,
    # `any([])` tornerebbe False e questo test lo bloccherebbe.
    assert eng.conditions_pass(_parser([], mode="any"), "qualsiasi") is True
    # anche con condizioni tutte a testo vuoto (ignorate) → nessun gate.
    assert eng.conditions_pass(_parser([cp.Condition(text="  ")], mode="any"), "x") is True


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
