"""Test del dizionario mappatura mercati (`market_mapping_store`).

Funzioni pure: nessuna GUI, nessun I/O. Coprono CRUD profili + il resolver a frase
con le decisioni del design (D2 ambiguità fail-closed, D3 testo grezzo a confini di
parola). Vedi `docs/audit/mercati_mapping_design.md`.
"""

from xtrader_bridge import market_mapping_store as mms


# Coppie Mercato/Selezione REALI del Catalogo XTrader (resolve_market valida la coerenza
# contro il catalogo, design §5.3): usare valori inesistenti darebbe sempre "none".
def _entry(phrase, market="Entrambe le squadre a segno", selection="Sì", mtype="GOAL_NOGOAL"):
    return {"phrase": phrase, "market_type": mtype,
            "market_name": market, "selection_name": selection}


# ── resolve_market ────────────────────────────────────────────────────────────

def test_resolve_match_univoco():
    profiles = [[_entry("goal prima di 70")]]
    res = mms.resolve_market("Consiglio: goal prima di 70, quota 1.8", profiles)
    assert res.status == "ok"
    # market_type CANONICO dal catalogo (non quello passato in _entry): canonicalizzazione.
    assert res.market == {"market_type": "BOTH_TEAMS_TO_SCORE",
                          "market_name": "Entrambe le squadre a segno",
                          "selection_name": "Sì"}


def test_resolve_canonicalizza_type_e_nomi():
    # config con market_type STANTIO e nomi non-canonici (case/spazi): resolve ritorna
    # SEMPRE la tupla canonica del catalogo — niente type stantio, niente nomi grezzi (Codex).
    profiles = [[{"phrase": "ggol",
                  "market_type": "MATCH_ODDS",                       # stantio/errato
                  "market_name": "entrambe   le  squadre a segno",   # spazi/case non-canonici
                  "selection_name": "sì"}]]
    res = mms.resolve_market("punta ggol", profiles)
    assert res.status == "ok"
    assert res.market == {"market_type": "BOTH_TEAMS_TO_SCORE",
                          "market_name": "Entrambe le squadre a segno",
                          "selection_name": "Sì"}


def test_resolve_frase_corta_non_dentro_codici_slash():
    # frase corta "x" non deve combaciare dentro codici tipo "1/x", "x/x", "1-x" (Codex):
    # / e - non sono confini di token.
    profiles = [[_entry("x")]]
    for txt in ("doppio esito 1/x", "x/x ht-ft", "segna 1-x"):
        assert mms.resolve_market(txt, profiles).status == "none", txt
    assert mms.resolve_market("punta x adesso", profiles).status == "ok"


def test_resolve_nessun_match():
    profiles = [[_entry("goal prima di 70")]]
    assert mms.resolve_market("Nessun mercato qui", profiles).status == "none"


def test_resolve_testo_vuoto():
    profiles = [[_entry("goal prima di 70")]]
    assert mms.resolve_market("", profiles).status == "none"
    assert mms.resolve_market(None, profiles).status == "none"


def test_resolve_case_insensitive():
    profiles = [[_entry("Goal Prima Di 70")]]
    assert mms.resolve_market("GOAL PRIMA DI 70 nel match", profiles).status == "ok"


def test_resolve_confine_di_parola_no_falso_positivo():
    # "over" non deve combaciare dentro "overflow"/"discover". Coppia reale del catalogo.
    profiles = [[_entry("over", market="1º tempo - Totale goal 0,5",
                        selection="Over 0,5 goal")]]
    assert mms.resolve_market("data overflow discover", profiles).status == "none"
    # ma combacia come parola a sé
    assert mms.resolve_market("punta over adesso", profiles).status == "ok"


def test_resolve_frase_con_numeri_e_punteggiatura():
    profiles = [[_entry("over 0,5", market="1º tempo - Totale goal 0,5",
                        selection="Over 0,5 goal")]]
    assert mms.resolve_market("vai di over 0,5!", profiles).status == "ok"
    # "over 0,55" non deve combaciare con la frase "over 0,5" (confine dopo il 5)
    assert mms.resolve_market("over 0,55", profiles).status == "none"


def test_resolve_ambiguo_mercati_diversi_failclosed():
    # Due frasi diverse combaciano e indicano selezioni DIVERSE → ambiguous (D2).
    profiles = [[
        _entry("gol gol", market="Entrambe le squadre a segno", selection="Sì"),
        _entry("no gol", market="Entrambe le squadre a segno", selection="No"),
    ]]
    res = mms.resolve_market("scommetti gol gol e no gol", profiles)
    assert res.status == "ambiguous"
    assert res.market is None


def test_resolve_match_doppio_stesso_mercato_non_ambiguo():
    # Due frasi diverse ma con LA STESSA selezione → ok (non ambiguo).
    profiles = [[
        _entry("gol gol", market="Entrambe le squadre a segno", selection="Sì"),
        _entry("entrambe segnano", market="Entrambe le squadre a segno", selection="Sì"),
    ]]
    res = mms.resolve_market("gol gol e entrambe segnano", profiles)
    assert res.status == "ok"
    assert res.market["selection_name"] == "Sì"


def test_resolve_voce_incoerente_col_catalogo_ignorata():
    # Mercato/Selezione NON nel catalogo XTrader → la voce è ignorata anche se la frase
    # combacia: mai scrivere un mercato non riconoscibile (design §5.3).
    profiles = [[_entry("frase x", market="Mercato Inventato", selection="Selezione X")]]
    assert mms.resolve_market("frase x", profiles).status == "none"
    # Coppia reale ma INCOERENTE (selezione di un altro mercato) → ignorata.
    bad = [[_entry("frase y", market="Entrambe le squadre a segno", selection="Over 0,5 goal")]]
    assert mms.resolve_market("frase y", bad).status == "none"


def test_resolve_catalogo_iniettato_nei_test():
    # `rows` permette di iniettare un catalogo (purezza/testabilità): qui un catalogo
    # finto minimale rende coerente una coppia altrimenti inesistente.
    fake_rows = [{"MarketType_XTrader": "T", "MarketName_XTrader": "Mercato Finto",
                  "SelectionRole": "", "SelectionName_XTrader": "Sel Finta",
                  "Linea": "", "Handicap": "", "BetType_XTrader": "", "Lingua": ""}]
    profiles = [[_entry("xyz", market="Mercato Finto", selection="Sel Finta")]]
    assert mms.resolve_market("gioca xyz", profiles, rows=fake_rows).status == "ok"


def test_resolve_multi_profilo():
    # La frase è nel secondo profilo.
    profiles = [[_entry("altra cosa")], [_entry("goal prima di 70")]]
    assert mms.resolve_market("goal prima di 70", profiles).status == "ok"


def test_resolve_profili_vuoti_o_none():
    assert mms.resolve_market("qualcosa", []).status == "none"
    assert mms.resolve_market("qualcosa", None).status == "none"


# ── CRUD profili ──────────────────────────────────────────────────────────────

def test_add_get_set_entries():
    cfg = {}
    cfg = mms.add_profile(cfg, "Pandorabet")
    assert mms.profile_names(cfg) == ["Pandorabet"]
    assert mms.get_entries(cfg, "Pandorabet") == []
    cfg = mms.set_entries(cfg, "Pandorabet", [_entry("goal prima di 70")])
    entries = mms.get_entries(cfg, "Pandorabet")
    assert len(entries) == 1 and entries[0]["phrase"] == "goal prima di 70"


def test_clean_entry_scarta_incomplete():
    # Mancano market_name o selection_name o phrase → voce scartata.
    cfg = mms.set_entries({}, "P", [
        {"phrase": "x", "market_name": "M", "selection_name": "S", "market_type": "T"},
        {"phrase": "", "market_name": "M", "selection_name": "S"},        # no phrase
        {"phrase": "y", "market_name": "", "selection_name": "S"},        # no market
        {"phrase": "z", "market_name": "M", "selection_name": ""},        # no selection
        "non-dict",
    ])
    entries = mms.get_entries(cfg, "P")
    assert [e["phrase"] for e in entries] == ["x"]


def test_market_type_opzionale_preservato():
    cfg = mms.set_entries({}, "P", [
        {"phrase": "p1", "market_name": "M", "selection_name": "S"},                 # no type
        {"phrase": "p2", "market_name": "M", "selection_name": "S", "market_type": "T"},
    ])
    entries = mms.get_entries(cfg, "P")
    assert entries[0]["market_type"] == ""
    assert entries[1]["market_type"] == "T"


def test_profile_names_ordinati_case_insensitive():
    cfg = mms.add_profile(mms.add_profile(mms.add_profile({}, "zeta"), "Alfa"), "beta")
    assert mms.profile_names(cfg) == ["Alfa", "beta", "zeta"]


def test_rename_profile():
    cfg = mms.set_entries({}, "old", [_entry("p")])
    cfg = mms.rename_profile(cfg, "old", "new")
    assert mms.profile_names(cfg) == ["new"]
    assert len(mms.get_entries(cfg, "new")) == 1
    # no-op se new esiste già (niente sovrascrittura silenziosa)
    cfg = mms.set_entries(cfg, "altro", [_entry("q")])
    cfg2 = mms.rename_profile(cfg, "new", "altro")
    assert set(mms.profile_names(cfg2)) == {"new", "altro"}


def test_delete_profile_idempotente():
    cfg = mms.add_profile({}, "P")
    cfg = mms.delete_profile(cfg, "P")
    assert mms.profile_names(cfg) == []
    # idempotente
    assert mms.profile_names(mms.delete_profile(cfg, "P")) == []


def test_entries_for_profiles():
    cfg = mms.set_entries(mms.set_entries({}, "A", [_entry("a")]), "B", [_entry("b")])
    lol = mms.entries_for_profiles(cfg, ["A", "B", "manca"])
    assert len(lol) == 3
    assert lol[0][0]["phrase"] == "a"
    assert lol[1][0]["phrase"] == "b"
    assert lol[2] == []   # profilo mancante → lista vuota


def test_chiavi_profilo_con_spazi_legacy():
    # config.json editata a mano: chiave con spazi attorno. profile_names la mostra
    # ripulita e get/add/delete/rename/set la ritrovano (no mappatura persa, no doppioni).
    cfg = {"market_mappings": {"  Pandorabet  ": [_entry("goal prima di 70")]}}
    assert mms.profile_names(cfg) == ["Pandorabet"]
    assert len(mms.get_entries(cfg, "Pandorabet")) == 1
    # add con nome normalizzato NON crea un doppione
    assert mms.profile_names(mms.add_profile(cfg, "Pandorabet")) == ["Pandorabet"]
    # rename/delete ritrovano la chiave legacy
    cfg_r = mms.rename_profile(cfg, "Pandorabet", "Nuovo")
    assert mms.profile_names(cfg_r) == ["Nuovo"] and len(mms.get_entries(cfg_r, "Nuovo")) == 1
    assert mms.profile_names(mms.delete_profile(cfg, "Pandorabet")) == []
    # set_entries migra la chiave legacy al nome normalizzato (una sola chiave)
    cfg_s = mms.set_entries(cfg, "Pandorabet", [_entry("over")])
    assert list(cfg_s["market_mappings"].keys()) == ["Pandorabet"]


def test_immutabilita_config_originale():
    cfg = {"market_mappings": {"P": [_entry("p")]}}
    snapshot = {"market_mappings": {"P": [dict(_entry("p"))]}}
    mms.add_profile(cfg, "Q")
    mms.set_entries(cfg, "P", [])
    mms.delete_profile(cfg, "P")
    mms.rename_profile(cfg, "P", "R")
    assert cfg == snapshot   # nessuna funzione muta l'originale
