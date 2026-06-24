"""Test del dizionario mappatura mercati (`market_mapping_store`).

Funzioni pure: nessuna GUI, nessun I/O. Il mercato si legge **da una posizione precisa** del
messaggio (delimitatori `Inizia dopo`/`Finisce prima`, stesso motore del Parser) e si traduce
nella coppia canonica del Catalogo XTrader. Coprono CRUD profili + il resolver a estrazione
con le decisioni del design (D2 ambiguità fail-closed, banner ignorato, confini di token).
Vedi `docs/audit/mercati_mapping_design.md`.
"""

from xtrader_bridge import market_mapping_store as mms


# Coppie Mercato/Selezione REALI del Catalogo XTrader (resolve_market valida la coerenza
# contro il catalogo, §5.3): usare valori inesistenti darebbe sempre "none". Una voce ha
# SEMPRE almeno un delimitatore, altrimenti è scartata (la modalità "frase su tutto il
# messaggio" è stata rimossa).
def _entry(phrase, start_after="Mercato:", end_before="\n",
           market="Entrambe le squadre a segno", selection="Sì", mtype="GOAL_NOGOAL"):
    return {"start_after": start_after, "end_before": end_before, "phrase": phrase,
            "market_type": mtype, "market_name": market, "selection_name": selection}


# ── resolve_market (a estrazione) ───────────────────────────────────────────

def test_resolve_match_dal_campo_estratto():
    profiles = [[_entry("gol gol", start_after="Mercato:", end_before="\n")]]
    res = mms.resolve_market("Inter v Milan\nMercato: gol gol\nQuota 1.8", profiles)
    assert res.status == "ok"
    # market_type CANONICO dal catalogo (non quello passato in _entry): canonicalizzazione.
    assert res.market == {"market_type": "BOTH_TEAMS_TO_SCORE",
                          "market_name": "Entrambe le squadre a segno",
                          "selection_name": "Sì"}


def test_resolve_banner_ignorato():
    # Caso reale P.Bet.: in testa un banner-menu con più mercati; il mercato VERO sta tra
    # «Quota» e «Prematch». Leggendo solo quel campo, il banner non crea ambiguità.
    profiles = [[
        _entry("0,5 HT", start_after="Quota", end_before="Prematch",
               market="1º tempo - Totale goal 0,5", selection="Over 0,5 goal", mtype=""),
        _entry("1,5 HT", start_after="Quota", end_before="Prematch",
               market="1º tempo - Totale goal 1,5", selection="Over 1,5 goal", mtype=""),
    ]]
    msg = ("P.Bet. PREMACHT 30/0,5HT/1,5HT/1 ASIATICO\n"
           "Mahar United FC v Hanthawaddy United FC\n"
           "Quota 0,5 HT Prematch:0\n74.33%")
    res = mms.resolve_market(msg, profiles)
    assert res.status == "ok"
    assert res.market["market_name"] == "1º tempo - Totale goal 0,5"
    assert res.market["market_type"] == "FIRST_HALF_GOALS_05"


def test_resolve_canonicalizza_type_e_nomi():
    # config con market_type STANTIO e nomi non-canonici (case/spazi): resolve ritorna
    # SEMPRE la tupla canonica del catalogo — niente type stantio, niente nomi grezzi.
    profiles = [[{"start_after": "Mercato:", "end_before": "\n", "phrase": "ggol",
                  "market_type": "MATCH_ODDS",                       # stantio/errato
                  "market_name": "entrambe   le  squadre a segno",   # spazi/case non-canonici
                  "selection_name": "sì"}]]
    res = mms.resolve_market("punta\nMercato: ggol\n", profiles)
    assert res.status == "ok"
    assert res.market == {"market_type": "BOTH_TEAMS_TO_SCORE",
                          "market_name": "Entrambe le squadre a segno",
                          "selection_name": "Sì"}


def test_resolve_none_se_delimitatore_assente():
    # Il testo mercato c'è, ma il delimitatore «Mercato:» no → niente estrazione → "none"
    # (non si scansiona tutto il messaggio: modalità rimossa).
    profiles = [[_entry("gol gol", start_after="Mercato:", end_before="\n")]]
    assert mms.resolve_market("Consiglio: gol gol senza etichetta", profiles).status == "none"


def test_resolve_end_before_vuoto_fino_a_fine_riga():
    # end_before "" → estrae fino a fine riga (o fine messaggio).
    profiles = [[_entry("gol gol", start_after="Mercato:", end_before="")]]
    assert mms.resolve_market("Mercato: gol gol", profiles).status == "ok"
    assert mms.resolve_market("Mercato: gol gol\naltro", profiles).status == "ok"
    # Regressione (CodeRabbit): l'estrazione deve FERMARSI a fine riga — il testo della riga
    # 2 non deve combaciare (se "spillasse" oltre il newline, "no gol" matcherebbe).
    p2 = [[_entry("no gol", start_after="Mercato:", end_before="")]]
    assert mms.resolve_market("Mercato: gol gol\nbanner: no gol", p2).status == "none"


def test_resolve_voce_legacy_senza_delimitatori_preservata_ma_inerte():
    # Una voce vecchia (solo phrase, niente delimitatori) NON va persa al round-trip
    # set/get (CodeRabbit), ma il resolver non la applica (fail-closed).
    legacy = {"phrase": "gol gol", "market_type": "",
              "market_name": "Entrambe le squadre a segno", "selection_name": "Sì"}
    cfg = mms.set_entries({}, "P", [legacy])
    assert len(mms.get_entries(cfg, "P")) == 1            # preservata
    # ...ma non applicata: nessun delimitatore → saltata.
    assert mms.resolve_market("ovunque gol gol nel testo",
                              mms.entries_for_profiles(cfg, ["P"])).status == "none"


def test_resolve_delimitatore_con_newline_preservato():
    # Codex: un delimitatore con newline ("\nQuota") deve restare ancorato a inizio riga —
    # i newline NON vengono tolti (solo spazi/tab ai bordi, come nel Parser).
    cfg = mms.set_entries({}, "P", [_entry(
        "0,5 HT", start_after="\nQuota ", end_before="Prematch",
        market="1º tempo - Totale goal 0,5", selection="Over 0,5 goal", mtype="")])
    e = mms.get_entries(cfg, "P")[0]
    assert e["start_after"] == "\nQuota"                  # newline preservato, spazi tolti
    prof = mms.entries_for_profiles(cfg, ["P"])
    # "Quota" a inizio riga → combacia; "Quota" inline nel banner non basta da solo.
    assert mms.resolve_market("Tip\nQuota 0,5 HT Prematch:0", prof).status == "ok"
    assert mms.resolve_market("banner Quota 0,5 HT Prematch inline", prof).status == "none"


def test_resolve_nessun_match_testo_diverso():
    profiles = [[_entry("gol gol", start_after="Mercato:", end_before="\n")]]
    assert mms.resolve_market("Mercato: pareggio\n", profiles).status == "none"


def test_resolve_testo_vuoto():
    profiles = [[_entry("gol gol")]]
    assert mms.resolve_market("", profiles).status == "none"
    assert mms.resolve_market(None, profiles).status == "none"


def test_resolve_case_insensitive():
    # Il testo mercato è case-insensitive nel campo estratto (il delimitatore resta
    # case-sensitive come nel Parser: «Mercato:» combacia con «Mercato:»).
    profiles = [[_entry("Gol Gol", start_after="Mercato:", end_before="\n")]]
    assert mms.resolve_market("Mercato: GOL GOL adesso\n", profiles).status == "ok"


def test_resolve_confine_di_token_no_falso_positivo():
    # "over" non deve combaciare dentro "overflow" nel campo estratto. Coppia reale.
    profiles = [[_entry("over", start_after="M:", end_before="\n",
                        market="1º tempo - Totale goal 0,5",
                        selection="Over 0,5 goal", mtype="")]]
    assert mms.resolve_market("M: data overflow discover\n", profiles).status == "none"
    assert mms.resolve_market("M: punta over adesso\n", profiles).status == "ok"


def test_resolve_testo_con_numeri_e_punteggiatura():
    profiles = [[_entry("over 0,5", start_after="M:", end_before="\n",
                        market="1º tempo - Totale goal 0,5",
                        selection="Over 0,5 goal", mtype="")]]
    assert mms.resolve_market("M: vai di over 0,5!\n", profiles).status == "ok"
    # "over 0,55" non deve combaciare con "over 0,5" (confine dopo il 5)
    assert mms.resolve_market("M: over 0,55\n", profiles).status == "none"


def test_resolve_ambiguo_failclosed():
    # Due voci con gli STESSI delimitatori combaciano nel campo estratto e indicano
    # selezioni DIVERSE → ambiguous (D2): niente riga.
    profiles = [[
        _entry("gol gol", start_after="Mercato:", end_before="\n", selection="Sì"),
        _entry("no gol", start_after="Mercato:", end_before="\n", selection="No"),
    ]]
    res = mms.resolve_market("Mercato: gol gol e no gol\nQuota 1.5", profiles)
    assert res.status == "ambiguous"
    assert res.market is None


def test_resolve_match_doppio_stessa_selezione_non_ambiguo():
    # Due voci diverse ma con LA STESSA selezione canonica → ok (non ambiguo).
    profiles = [[
        _entry("gol gol", start_after="Mercato:", end_before="\n", selection="Sì"),
        _entry("entrambe segnano", start_after="Mercato:", end_before="\n", selection="Sì"),
    ]]
    res = mms.resolve_market("Mercato: gol gol e entrambe segnano\n", profiles)
    assert res.status == "ok"
    assert res.market["selection_name"] == "Sì"


def test_resolve_voce_incoerente_col_catalogo_ignorata():
    # Mercato/Selezione NON nel catalogo → la voce è ignorata anche se il testo combacia.
    profiles = [[_entry("frase x", start_after="M:", end_before="\n",
                        market="Mercato Inventato", selection="Selezione X")]]
    assert mms.resolve_market("M: frase x\n", profiles).status == "none"
    # Coppia reale ma INCOERENTE (selezione di un altro mercato) → ignorata.
    bad = [[_entry("frase y", start_after="M:", end_before="\n",
                   market="Entrambe le squadre a segno", selection="Over 0,5 goal")]]
    assert mms.resolve_market("M: frase y\n", bad).status == "none"


def test_resolve_catalogo_iniettato_nei_test():
    # `rows` permette di iniettare un catalogo (purezza/testabilità).
    fake_rows = [{"MarketType_XTrader": "T", "MarketName_XTrader": "Mercato Finto",
                  "SelectionRole": "", "SelectionName_XTrader": "Sel Finta",
                  "Linea": "", "Handicap": "", "BetType_XTrader": "", "Lingua": ""}]
    profiles = [[_entry("xyz", start_after="M:", end_before="\n",
                        market="Mercato Finto", selection="Sel Finta")]]
    assert mms.resolve_market("M: gioca xyz\n", profiles, rows=fake_rows).status == "ok"


def test_resolve_multi_profilo():
    profiles = [[_entry("altra cosa")], [_entry("gol gol")]]
    assert mms.resolve_market("Mercato: gol gol\n", profiles).status == "ok"


def test_resolve_profili_vuoti_o_none():
    assert mms.resolve_market("qualcosa", []).status == "none"
    assert mms.resolve_market("qualcosa", None).status == "none"


def test_resolve_difesa_runtime_voce_grezza_senza_delimitatori():
    # Difesa sul percorso runtime (profili passati GREZZI, non ripuliti da _clean_entry):
    # una voce senza delimitatori non deve combaciare su tutto il messaggio (Sourcery).
    bad = [[{"start_after": "", "end_before": "", "phrase": "gol gol",
             "market_type": "", "market_name": "Entrambe le squadre a segno",
             "selection_name": "Sì"}]]
    assert mms.resolve_market("ovunque gol gol nel testo", bad).status == "none"
    # Voce con delimitatori ma Testo mercato vuoto → ignorata.
    empty_phrase = [[{"start_after": "Mercato:", "end_before": "\n", "phrase": "",
                      "market_type": "", "market_name": "Entrambe le squadre a segno",
                      "selection_name": "Sì"}]]
    assert mms.resolve_market("Mercato: qualcosa\n", empty_phrase).status == "none"


# ── CRUD profili ──────────────────────────────────────────────────────────────

def test_add_get_set_entries():
    cfg = {}
    cfg = mms.add_profile(cfg, "Pandorabet")
    assert mms.profile_names(cfg) == ["Pandorabet"]
    assert mms.get_entries(cfg, "Pandorabet") == []
    cfg = mms.set_entries(cfg, "Pandorabet", [_entry("gol gol")])
    entries = mms.get_entries(cfg, "Pandorabet")
    assert len(entries) == 1 and entries[0]["phrase"] == "gol gol"
    assert entries[0]["start_after"] == "Mercato:"


def test_clean_entry_scarta_incomplete():
    # Mancano phrase / market_name / selection_name → voce scartata. La voce SENZA
    # delimitatori è invece PRESERVATA (no perdita dati): sarà il resolver a non applicarla.
    cfg = mms.set_entries({}, "P", [
        {"start_after": "M:", "end_before": "", "phrase": "x",
         "market_name": "M", "selection_name": "S", "market_type": "T"},      # ok
        {"start_after": "M:", "phrase": "", "market_name": "M", "selection_name": "S"},  # no phrase
        {"start_after": "M:", "phrase": "y", "market_name": "", "selection_name": "S"},  # no market
        {"start_after": "M:", "phrase": "z", "market_name": "M", "selection_name": ""},  # no selection
        {"phrase": "w", "market_name": "M", "selection_name": "S"},   # nessun delimitatore → PRESERVATA
        "non-dict",
    ])
    entries = mms.get_entries(cfg, "P")
    assert [e["phrase"] for e in entries] == ["x", "w"]
    # La voce legacy è preservata con delimitatori vuoti.
    w = entries[1]
    assert w["start_after"] == "" and w["end_before"] == ""


def test_market_type_opzionale_preservato():
    cfg = mms.set_entries({}, "P", [
        {"start_after": "M:", "phrase": "p1", "market_name": "M", "selection_name": "S"},   # no type
        {"start_after": "M:", "phrase": "p2", "market_name": "M", "selection_name": "S",
         "market_type": "T"},
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
    cfg = {"market_mappings": {"  Pandorabet  ": [_entry("gol gol")]}}
    assert mms.profile_names(cfg) == ["Pandorabet"]
    assert len(mms.get_entries(cfg, "Pandorabet")) == 1
    assert mms.profile_names(mms.add_profile(cfg, "Pandorabet")) == ["Pandorabet"]
    cfg_r = mms.rename_profile(cfg, "Pandorabet", "Nuovo")
    assert mms.profile_names(cfg_r) == ["Nuovo"] and len(mms.get_entries(cfg_r, "Nuovo")) == 1
    assert mms.profile_names(mms.delete_profile(cfg, "Pandorabet")) == []
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
