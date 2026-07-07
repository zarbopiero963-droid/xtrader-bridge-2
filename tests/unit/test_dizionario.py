"""Test del dizionario XTrader (PR-07).

Verifica struttura, assenza di alias duplicati e copertura dei mercati/combinazioni
richiesti, basandosi sul file reale `data/dizionario_xtrader.csv`.
"""

from xtrader_bridge import dizionario as dz


def _rows():
    return dz.load_dizionario()


def test_file_caricabile():
    rows = _rows()
    assert len(rows) == 81


def test_header_esatto():
    rows = _rows()
    assert list(rows[0].keys()) == dz.EXPECTED_COLUMNS


def test_nessun_alias_duplicato():
    assert dz.duplicate_alias_pairs(_rows()) == []


def test_ogni_riga_ha_markettype_e_selectionname():
    for row in _rows():
        assert row["MarketType_XTrader"].strip()
        assert row["SelectionName_XTrader"].strip()


def test_bettype_solo_punta_o_banca():
    for row in _rows():
        assert row["BetType_XTrader"] in ("PUNTA", "BANCA")


def test_correct_score_19_selezioni():
    rows = [r for r in _rows() if r["MarketType_XTrader"] == "CORRECT_SCORE"]
    sels = {r["SelectionName_XTrader"] for r in rows}
    # 16 risultati esatti 0-0..3-3 + 3 "Altro"
    for h in range(4):
        for a in range(4):
            assert f"{h} - {a}" in sels
    assert len(rows) == 19


def test_half_time_score_10_selezioni():
    rows = [r for r in _rows() if r["MarketType_XTrader"] == "HALF_TIME_SCORE"]
    sels = {r["SelectionName_XTrader"] for r in rows}
    for h in range(3):
        for a in range(3):
            assert f"{h} - {a}" in sels        # 0-0..2-2
    assert "Qualsiasi altro risultato" in sels
    assert len(rows) == 10


def test_over_under_da_05_a_85():
    mts = dz.market_types(_rows())
    for suffix in ("05", "15", "25", "35", "45", "55", "65", "75", "85"):
        assert f"OVER_UNDER_{suffix}" in mts


def test_first_half_goals_05_15_25():
    mts = dz.market_types(_rows())
    for mt in ("FIRST_HALF_GOALS_05", "FIRST_HALF_GOALS_15", "FIRST_HALF_GOALS_25"):
        assert mt in mts


def test_market_types_riga_senza_colonna_non_solleva():
    """#184 M9: una riga senza `MarketType_XTrader` (dizionario non validato / dict parziale) NON
    deve sollevare `KeyError`; degrada come i fratelli che usano `.get()`. Valori vuoti/assenti
    esclusi, valori presenti inclusi (con strip).

    Fail-first: col vecchio `row["MarketType_XTrader"]` la riga `{}` sollevava `KeyError`."""
    rows = [
        {"MarketType_XTrader": "OVER_UNDER_05"},
        {},                                          # riga senza la colonna → niente KeyError
        {"MarketType_XTrader": ""},                  # vuoto → escluso
        {"MarketType_XTrader": "  CORRECT_SCORE  "},  # strippato come gli altri lettori
        {"Sport": "Calcio"},                         # altra colonna, nessun MarketType
    ]
    mts = dz.market_types(rows)
    assert mts == {"OVER_UNDER_05", "CORRECT_SCORE"}


def test_market_types_reali_coerenti_con_market_catalog():
    """#184 M9: sul dizionario reale `market_types` coincide con i MarketType di `market_catalog`
    (stessa fonte/normalizzazione), così il fix non cambia l'output in produzione."""
    rows = _rows()
    assert dz.market_types(rows) == {m["MarketType"] for m in dz.market_catalog(rows)}


def test_data_dir_da_meipass_se_frozen(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(dz.sys, "frozen", True, raising=False)
    monkeypatch.setattr(dz.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert dz._data_dir() == os.path.join(str(tmp_path), "data")


# ── resource_path: 3 forme di distribuzione (source / PyInstaller / Nuitka) ──
# Fase 6: l'EXE ufficiale passa a Nuitka. `resource_path` è l'unico punto che risolve gli
# asset read-only impacchettati (`data/dizionario_xtrader.csv`); questi test bloccano una
# regressione che, cambiando distribuzione, spedirebbe l'EXE senza dizionario (→ nessun
# lookup alias→XTrader → CSV incompleto). Ogni test è verificabile fail-first via mutazione.

def test_resource_path_da_sorgente_usa_file(monkeypatch):
    """Run da SORGENTE: nessun `sys.frozen`, nessun `_MEIPASS` → base = genitore del package
    (`dirname(dirname(__file__))`), cioè la radice del repo dove vive `data/`."""
    import os
    monkeypatch.delattr(dz.sys, "frozen", raising=False)
    monkeypatch.delattr(dz.sys, "_MEIPASS", raising=False)
    base = os.path.dirname(os.path.dirname(os.path.abspath(dz.__file__)))
    assert dz.resource_path("data") == os.path.join(base, "data")
    assert dz.resource_path(os.path.join("data", "x.csv")) == os.path.join(base, "data", "x.csv")


def test_resource_path_pyinstaller_usa_meipass(monkeypatch, tmp_path):
    """PyInstaller: `sys.frozen=True` + `_MEIPASS=<bundle>` → base = `_MEIPASS`. Nel bundle
    `__file__` punta alla cartella temporanea sbagliata, quindi si DEVE usare `_MEIPASS`."""
    import os
    monkeypatch.setattr(dz.sys, "frozen", True, raising=False)
    monkeypatch.setattr(dz.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert dz.resource_path("data") == os.path.join(str(tmp_path), "data")


def test_resource_path_nuitka_ignora_meipass_e_usa_file(monkeypatch, tmp_path):
    """Nuitka: marca il modulo con `__compiled__` ma NON imposta `sys.frozen`. Il ramo
    `_MEIPASS` è gated su `sys.frozen`, quindi Nuitka cade nel ramo `__file__` come il
    sorgente — anche se un `_MEIPASS` stray fosse presente in `sys`, va IGNORATO.
    GARANZIA: nessun uso di `_MEIPASS` senza `frozen` (altrimenti l'EXE Nuitka cercherebbe
    il dizionario in una cartella PyInstaller inesistente)."""
    import os
    monkeypatch.setattr(dz, "__compiled__", object(), raising=False)       # marchio Nuitka
    monkeypatch.delattr(dz.sys, "frozen", raising=False)                    # Nuitka non lo setta
    monkeypatch.setattr(dz.sys, "_MEIPASS", str(tmp_path), raising=False)   # stray → da ignorare
    base = os.path.dirname(os.path.dirname(os.path.abspath(dz.__file__)))
    got = dz.resource_path("data")
    assert got == os.path.join(base, "data")
    assert str(tmp_path) not in got                                        # _MEIPASS NON usato


def test_resource_path_nuitka_anche_se_frozen_impostato_usa_file(monkeypatch, tmp_path):
    """DIFESA-IN-PROFONDITÀ (finding review Fable #365): Nuitka NON imposta `sys.frozen` (doc
    ufficiale), ma se un domani qualcosa lo impostasse su un binario Nuitka, il gating su
    `__compiled__` PRIMA di `sys.frozen` garantisce che si usi comunque `__file__` — MAI il
    ramo PyInstaller (`_MEIPASS`/`dirname(executable)`), che in onefile punterebbe accanto
    all'EXE reale dove i dati spacchettati NON sono (→ dizionario non trovato → CSV senza
    lookup alias). Qui: `__compiled__` presente + `sys.frozen=True` + `_MEIPASS` stray →
    DEVE risolvere via `__file__`."""
    import os
    monkeypatch.setattr(dz, "__compiled__", object(), raising=False)       # marchio Nuitka
    monkeypatch.setattr(dz.sys, "frozen", True, raising=False)             # ipotetico frozen
    monkeypatch.setattr(dz.sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    monkeypatch.setattr(dz.sys, "executable", str(tmp_path / "app.exe"), raising=False)
    base = os.path.dirname(os.path.dirname(os.path.abspath(dz.__file__)))
    got = dz.resource_path("data")
    assert got == os.path.join(base, "data")
    assert str(tmp_path) not in got            # né _MEIPASS né dirname(executable) usati


def test_resource_path_frozen_senza_meipass_fallback_eseguibile(monkeypatch, tmp_path):
    """Difensivo: un freezer che imposta `sys.frozen` ma NON `_MEIPASS` → fallback alla
    cartella dell'eseguibile (`dirname(sys.executable)`), non un crash da AttributeError."""
    import os
    monkeypatch.setattr(dz.sys, "frozen", True, raising=False)
    monkeypatch.delattr(dz.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(dz.sys, "executable", str(tmp_path / "app.exe"), raising=False)
    assert dz.resource_path("data") == os.path.join(str(tmp_path), "data")


def test_data_dir_delega_a_resource_path(monkeypatch):
    """`_data_dir()` è solo `resource_path("data")`: se cambia la radice risolta, `_data_dir`
    la segue (nessuna logica di path duplicata che possa divergere)."""
    import os
    monkeypatch.setattr(dz, "resource_path", lambda rel: os.path.join("FAKE_ROOT", rel))
    assert dz._data_dir() == os.path.join("FAKE_ROOT", "data")


def test_alias_key_normalizza():
    assert dz.alias_key("  Over 0.5 HT ", "OVER 0.5 HT") == ("over 0.5 ht", "over 0.5 ht")


def test_alias_key_collassa_spazi_interni():
    assert dz.alias_key("over   0.5    ht", "Over  0.5  HT") == ("over 0.5 ht", "over 0.5 ht")


def test_duplicate_ignora_righe_con_alias_vuoti():
    rows = [
        {"MarketAliasTelegram": "", "SelectionAliasTelegram": ""},
        {"MarketAliasTelegram": "", "SelectionAliasTelegram": ""},
        {"MarketAliasTelegram": "esito_finale", "SelectionAliasTelegram": "1"},
    ]
    assert dz.duplicate_alias_pairs(rows) == []   # gli alias vuoti non sono duplicati


def test_duplicate_rileva_veri_duplicati():
    rows = [
        {"MarketAliasTelegram": "esito_finale", "SelectionAliasTelegram": "1"},
        {"MarketAliasTelegram": "Esito_Finale", "SelectionAliasTelegram": " 1 "},
    ]
    assert dz.duplicate_alias_pairs(rows) == [("esito_finale", "1")]


# ── Catalogo per le tendine (A1) ────────────────────────────────────────────

def test_market_catalog_22_mercati_senza_duplicati():
    cat = dz.market_catalog()
    assert len(cat) == 22                              # 22 MarketType distinti
    types = [m["MarketType"] for m in cat]
    assert len(types) == len(set(types))               # nessun duplicato
    assert all(m["MarketType"] and m["MarketName"] for m in cat)  # mai vuoti


def test_market_catalog_flag_dynamic_sui_mercati_handicap():
    # Codex P2 (follow-up): anche il CATALOGO mercati espone `dynamic`, perché i
    # MarketName degli handicap TEAM_A_1/TEAM_B_1 sono placeholder ("{HOME_TEAM} +1"):
    # non sono valori fissi sicuri. I mercati normali restano dynamic=False.
    cat = {m["MarketType"]: m for m in dz.market_catalog()}
    assert all("dynamic" in m for m in cat.values())
    assert cat["TEAM_A_1"]["dynamic"] is True
    assert cat["TEAM_B_1"]["dynamic"] is True
    assert cat["MATCH_ODDS"]["dynamic"] is False
    assert cat["OVER_UNDER_25"]["dynamic"] is False
    assert cat["CORRECT_SCORE"]["dynamic"] is False
    # helper coerente, per MarketType e per MarketName
    assert dz.market_is_dynamic("TEAM_A_1") is True
    assert dz.market_is_dynamic("Esito Finale") is False
    assert dz.market_is_dynamic("INESISTENTE") is False
    assert dz.market_is_dynamic("") is False


def test_market_names_fixed_only_esclude_i_dinamici():
    # Codex P2: il helper documentato per la tendina deve poter escludere i mercati
    # dinamici (MarketName con placeholder), così non vengono offerti come valore fisso.
    all_names = dz.market_names()
    fixed = dz.market_names(fixed_only=True)
    # nel default ci sono anche i nomi handicap con placeholder…
    assert "{HOME_TEAM} +1" in all_names
    assert "{AWAY_TEAM} +1" in all_names
    # …in fixed_only no: nessun nome con placeholder.
    assert not any(dz.has_placeholder(n) for n in fixed)
    assert "{HOME_TEAM} +1" not in fixed and "{AWAY_TEAM} +1" not in fixed
    # i mercati normali restano in entrambi.
    assert "Esito Finale" in fixed and "Esito Finale" in all_names
    assert len(fixed) == len(all_names) - 2     # esclusi solo TEAM_A_1/TEAM_B_1


def test_market_name_type_roundtrip():
    assert dz.market_name_for_type("MATCH_ODDS") == "Esito Finale"
    assert dz.market_type_for_name("Esito Finale") == "MATCH_ODDS"
    # case/space-insensitive sul nome
    assert dz.market_type_for_name("  over/under 2,5 gol ") == "OVER_UNDER_25"
    # sconosciuti → None (niente eccezioni)
    assert dz.market_name_for_type("INESISTENTE") is None
    assert dz.market_type_for_name("Mercato che non esiste") is None


def test_selections_for_market_match_odds():
    # match per MarketType e per MarketName danno lo stesso insieme.
    by_type = dz.selections_for_market("MATCH_ODDS")
    by_name = dz.selections_for_market("Esito Finale")
    assert {s["SelectionName"] for s in by_type} == {s["SelectionName"] for s in by_name}
    names = {s["SelectionName"] for s in by_type}
    assert names == {"{HOME_TEAM}", "{AWAY_TEAM}", "Pareggio"}
    # Home/Away sono dinamiche (placeholder squadra), Pareggio no.
    dyn = {s["SelectionName"]: s["dynamic"] for s in by_type}
    assert dyn["{HOME_TEAM}"] is True
    assert dyn["{AWAY_TEAM}"] is True
    assert dyn["Pareggio"] is False


def test_selections_for_market_over_under_porta_la_linea():
    ou = dz.selections_for_market("OVER_UNDER_25")
    assert {s["SelectionName"] for s in ou} == {"Over 2,5 goal", "Under 2,5 goal"}
    assert all(s["Linea"] == "2.5" and s["dynamic"] is False for s in ou)


def test_selections_for_market_correct_score_19_non_dinamiche():
    cs = dz.selections_for_market("CORRECT_SCORE")
    assert len(cs) == 19
    assert not any(s["dynamic"] for s in cs)


def test_selections_handicap_placeholder_nel_marketname_e_dinamico():
    # Codex P2: in TEAM_A_1/TEAM_B_1 il MarketName contiene {HOME_TEAM}/{AWAY_TEAM}
    # mentre una selezione è statica ("Pareggio"): la riga è COMUNQUE dinamica perché
    # serve Home/Away per risolvere il mercato. Tutte e 3 le selezioni → dynamic=True.
    for mt in ("TEAM_A_1", "TEAM_B_1"):
        sels = dz.selections_for_market(mt)
        assert sels, mt
        assert all(s["dynamic"] for s in sels), [(s["SelectionName"], s["dynamic"]) for s in sels]
        # in particolare la selezione statica "Pareggio" è marcata dinamica.
        pareggio = [s for s in sels if s["SelectionName"] == "Pareggio"]
        assert pareggio and pareggio[0]["dynamic"] is True


def test_selections_for_market_mercato_ignoto_o_vuoto():
    assert dz.selections_for_market("INESISTENTE") == []
    assert dz.selections_for_market("") == []
    assert dz.selections_for_market(None) == []


def test_has_placeholder():
    assert dz.has_placeholder("{HOME_TEAM}") is True
    assert dz.has_placeholder("{HOME_TEAM} +1") is True
    assert dz.has_placeholder("Pareggio") is False
    assert dz.has_placeholder("Over 2,5 goal") is False


def test_compose_event_name():
    assert dz.compose_event_name("Portogallo", "R.D. Congo") == "Portogallo - R.D. Congo"
    assert dz.compose_event_name("  Inter ", " Milan ") == "Inter - Milan"
    # squadra mancante → l'altra, senza separatore penzolante
    assert dz.compose_event_name("Inter", "") == "Inter"
    assert dz.compose_event_name("", "Milan") == "Milan"
    assert dz.compose_event_name("", "") == ""


def test_fill_placeholders():
    assert dz.fill_placeholders("{HOME_TEAM} +1", home="Inter") == "Inter +1"
    assert dz.fill_placeholders("{AWAY_TEAM}", away="Milan") == "Milan"
    assert dz.fill_placeholders("{EVENT_NAME}", home="Inter", away="Milan") == "Inter - Milan"
    # placeholder senza valore resta invariato (selezione non completabile)
    out = dz.fill_placeholders("{HOME_TEAM}", away="Milan")
    assert out == "{HOME_TEAM}"
    assert dz.has_placeholder(out) is True


def test_load_dizionario_header_valido_si_carica(tmp_path):
    # Un CSV con tutte le colonne attese (anche con colonne EXTRA) si carica.
    import csv as _csv
    p = tmp_path / "d.csv"
    cols = dz.EXPECTED_COLUMNS + ["ColonnaExtra"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow({c: "x" for c in cols})
    assert len(dz.load_dizionario(str(p))) == 1


def test_load_dizionario_colonna_mancante_fallisce_chiaramente(tmp_path):
    # audit C4: una colonna ATTESA mancante/rinominata → ValueError chiaro al load, invece
    # di mapping silenziosamente vuoti (alias→"" → nessun match) o KeyError al primo accesso.
    import csv as _csv

    import pytest
    p = tmp_path / "d.csv"
    cols = [c for c in dz.EXPECTED_COLUMNS if c != "MarketType_XTrader"] + ["MarketType_RINOMINATA"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow({c: "x" for c in cols})
    with pytest.raises(ValueError, match="MarketType_XTrader"):
        dz.load_dizionario(str(p))
