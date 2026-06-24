"""Test del controller del costruttore di Parser Personalizzati (CP-06).

Esercitano `xtrader_bridge.parser_builder.ParserBuilder`: opzioni dei menu,
gestione regole, validazione, save/load e test-live. Nessun widget GUI qui.
"""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER


# Righe-dizionario sintetiche per il catalogo (B2): un mercato statico con due
# selezioni statiche, un mercato DINAMICO (placeholder nel MarketName) e un mercato
# statico con selezione DINAMICA (placeholder/flag nella selezione).
_CATALOG_ROWS = [
    {"MarketType_XTrader": "MATCH_ODDS", "MarketName_XTrader": "Esito finale",
     "SelectionName_XTrader": "1", "SelezioneDinamica": ""},
    {"MarketType_XTrader": "MATCH_ODDS", "MarketName_XTrader": "Esito finale",
     "SelectionName_XTrader": "X", "SelezioneDinamica": ""},
    {"MarketType_XTrader": "HANDICAP", "MarketName_XTrader": "{HOME_TEAM} +1",
     "SelectionName_XTrader": "Vince", "SelezioneDinamica": ""},          # mercato dinamico
    {"MarketType_XTrader": "CORRECT_SCORE", "MarketName_XTrader": "Risultato esatto",
     "SelectionName_XTrader": "{HOME_TEAM} 1-0", "SelezioneDinamica": "Sì"},  # selezione dinamica
]


# ── catalogo XTrader: Mercato → Selezione fissi (B2) ───────────────────────

def test_market_options_esclude_i_mercati_dinamici():
    b = pb.ParserBuilder()
    assert b.market_options(rows=_CATALOG_ROWS) == ["Esito finale", "Risultato esatto"]


def test_selection_options_solo_non_dinamiche():
    b = pb.ParserBuilder()
    assert b.selection_options("Esito finale", rows=_CATALOG_ROWS) == ["1", "X"]
    # mercato statico ma con selezione dinamica → nessuna selezione fissa offerta
    assert b.selection_options("Risultato esatto", rows=_CATALOG_ROWS) == []
    assert b.selection_options("Inesistente", rows=_CATALOG_ROWS) == []


def test_set_fixed_market_crea_le_tre_regole_fisse():
    b = pb.ParserBuilder()
    b.add_rule(target="Price", required=True)        # regola preesistente: non va toccata
    b.set_fixed_market("Esito finale", "1", rows=_CATALOG_ROWS)
    by_target = {r.target: r for r in b.rules}
    assert by_target["MarketType"].fixed_value == "MATCH_ODDS"
    assert by_target["MarketName"].fixed_value == "Esito finale"
    assert by_target["SelectionName"].fixed_value == "1"
    # valori canonici fissi: niente estrazione/value-map che li altererebbe
    for t in ("MarketType", "MarketName", "SelectionName"):
        assert by_target[t].value_map == "" and by_target[t].start_after == ""
    assert "Price" in by_target                       # regola preesistente preservata


def test_set_fixed_market_aggiorna_senza_duplicare_target():
    b = pb.ParserBuilder()
    b.name = "Test"
    b.set_fixed_market("Esito finale", "1", rows=_CATALOG_ROWS)
    b.set_fixed_market("Esito finale", "X", rows=_CATALOG_ROWS)   # update
    targets = [r.target for r in b.rules]
    assert targets.count("SelectionName") == 1                   # nessun duplicato
    assert {r.target: r.fixed_value for r in b.rules}["SelectionName"] == "X"
    assert not b.errors()                                        # parser valido (no target dup)


def test_set_fixed_market_persiste_valori_canonici_da_input_non_canonico():
    # CodeRabbit (CSV-safety): un input con case/spazi diversi NON deve finire grezzo nel
    # CSV — si persistono SEMPRE i nomi canonici del catalogo (XTrader-compatibili).
    b = pb.ParserBuilder()
    b.set_fixed_market("  esito finale ", " x ", rows=_CATALOG_ROWS)
    by_target = {r.target: r.fixed_value for r in b.rules}
    assert by_target["MarketName"] == "Esito finale"      # non "esito finale"
    assert by_target["SelectionName"] == "X"              # non "x"
    assert by_target["MarketType"] == "MATCH_ODDS"


def test_set_fixed_market_rifiuta_mercato_o_selezione_non_validi():
    b = pb.ParserBuilder()
    with pytest.raises(ValueError, match="non nel catalogo"):
        b.set_fixed_market("Inesistente", "1", rows=_CATALOG_ROWS)
    with pytest.raises(ValueError, match="dinamica"):
        # selezione dinamica (placeholder) NON ammessa come valore fisso
        b.set_fixed_market("Risultato esatto", "{HOME_TEAM} 1-0", rows=_CATALOG_ROWS)


# ── opzioni per i menu a tendina ───────────────────────────────────────────

def test_target_options_sono_le_14_colonne():
    b = pb.ParserBuilder()
    assert b.target_options() == list(CSV_HEADER)


def test_transform_options_includono_vuoto_e_score():
    opts = pb.ParserBuilder().transform_options()
    assert opts[0] == ""                      # nessuna trasformazione
    assert "score_to_over" in opts


def test_value_map_options_builtin_e_dizionario():
    b = pb.ParserBuilder()
    builtin = b.value_map_options(include_dizionario=False)
    assert builtin[0] == "" and "bettype" in builtin
    full = b.value_map_options(include_dizionario=True)
    assert "markettype" in full and "selectionname" in full


def test_mode_options():
    assert set(pb.ParserBuilder().mode_options()) == {"ID_ONLY", "NAME_ONLY", "BOTH"}


# ── gestione regole ────────────────────────────────────────────────────────

def test_add_update_remove_rule():
    b = pb.ParserBuilder()
    b.add_rule("EventName", start_after="Match:", required=True)
    assert len(b.rules) == 1 and b.rules[0].target == "EventName"
    b.update_rule(0, end_before="\n")
    assert b.rules[0].end_before == "\n"
    b.remove_rule(0)
    assert b.rules == []


def test_update_rule_campo_sconosciuto_errore():
    b = pb.ParserBuilder()
    b.add_rule("Price")
    with pytest.raises(AttributeError):
        b.update_rule(0, non_esiste="x")


def test_move_rule():
    b = pb.ParserBuilder()
    b.add_rule("EventName")
    b.add_rule("Price")
    b.add_rule("BetType")
    assert b.move_rule(2, -1) == 1          # BetType su di uno
    assert [r.target for r in b.rules] == ["EventName", "BetType", "Price"]
    assert b.move_rule(0, -5) == 0          # clamp al bordo
    assert b.move_rule(0, +99) == 2         # clamp all'altro bordo


# ── validazione ────────────────────────────────────────────────────────────

def test_errors_e_is_valid():
    b = pb.ParserBuilder()
    assert not b.is_valid()                 # nome vuoto + nessuna regola
    b.name = "Mio parser"
    b.add_rule("Price", required=True)
    assert b.is_valid()
    assert b.errors() == []


def test_validazione_trasformazione_sconosciuta():
    b = pb.ParserBuilder()
    b.name = "X"
    b.add_rule("SelectionName", fixed_value="x", transform="boh")
    assert any("trasformazione sconosciuta" in e for e in b.errors())


# ── persistenza ─────────────────────────────────────────────────────────────

def test_save_e_load_round_trip(tmp_path):
    b = pb.ParserBuilder()
    b.name = "Yangon"
    b.add_rule("Provider", fixed_value="TG_CUSTOM")
    b.add_rule("Price", start_after="Quota:", required=True)
    path = b.save(str(tmp_path))
    loaded = pb.ParserBuilder.load(path)
    assert loaded.name == "Yangon"
    assert [r.target for r in loaded.rules] == ["Provider", "Price"]
    assert pb.ParserBuilder.list_saved(str(tmp_path)) == [path]


def test_save_parser_invalido_solleva(tmp_path):
    b = pb.ParserBuilder()  # nome vuoto, nessuna regola
    with pytest.raises(ValueError):
        b.save(str(tmp_path))


# ── gestione parser salvati (CP-11: lista / carica / duplica / elimina) ──────

def _save_parser(name, dir_path):
    b = pb.ParserBuilder()
    b.name = name
    b.add_rule("Price", start_after="Quota:", required=True)
    return b.save(dir_path)


def test_saved_parsers_lista_nome_e_path_ordinata(tmp_path):
    d = str(tmp_path)
    p_b = _save_parser("Beta", d)
    p_a = _save_parser("Alfa", d)
    saved = pb.ParserBuilder.saved_parsers(d)
    # Ordine per nome case-insensitive: Alfa prima di Beta.
    assert [it["name"] for it in saved] == ["Alfa", "Beta"]
    assert {it["path"] for it in saved} == {p_a, p_b}


def test_saved_parsers_cartella_assente_e_vuota(tmp_path):
    assert pb.ParserBuilder.saved_parsers(str(tmp_path / "non_esiste")) == []
    assert pb.ParserBuilder.saved_parsers(str(tmp_path)) == []


def test_saved_parsers_file_corrotto_usa_stem_senza_crash(tmp_path):
    _save_parser("Buono", str(tmp_path))
    (tmp_path / "rotto.json").write_text("{ non json", encoding="utf-8")
    nomi = [it["name"] for it in pb.ParserBuilder.saved_parsers(str(tmp_path))]
    # Il file corrotto compare col nome del file (stem), senza nascondere gli altri.
    assert "Buono" in nomi and "rotto" in nomi


def test_delete_saved_rimuove_e_idempotente(tmp_path):
    d = str(tmp_path)
    _save_parser("DaCancellare", d)
    assert len(pb.ParserBuilder.saved_parsers(d)) == 1
    assert pb.ParserBuilder.delete_saved("DaCancellare", d) is True
    assert pb.ParserBuilder.saved_parsers(d) == []
    # Seconda cancellazione: nessun errore, ritorna False.
    assert pb.ParserBuilder.delete_saved("DaCancellare", d) is False


def test_delete_saved_non_esce_dalla_cartella(tmp_path):
    # Anti path-traversal: un name "ostile" non cancella file fuori dalla cartella.
    outside = tmp_path / "vittima.json"
    outside.write_text("{}", encoding="utf-8")
    pb.ParserBuilder.delete_saved("../vittima", str(tmp_path / "parsers"))
    assert outside.exists()


def test_duplicate_saved_crea_copia_senza_toccare_originale(tmp_path):
    d = str(tmp_path)
    src = _save_parser("Originale", d)
    new_path = pb.ParserBuilder.duplicate_saved(src, "Copia", d)
    assert new_path != src
    nomi = {it["name"] for it in pb.ParserBuilder.saved_parsers(d)}
    assert nomi == {"Originale", "Copia"}
    # L'originale è intatto.
    assert pb.ParserBuilder.load(src).name == "Originale"


def test_duplicate_saved_nome_in_collisione_solleva(tmp_path):
    d = str(tmp_path)
    src = _save_parser("Uno", d)
    _save_parser("Due", d)
    # Duplicare "Uno" col nome "Due" collide con un parser diverso → rifiutato.
    with pytest.raises(ValueError):
        pb.ParserBuilder.duplicate_saved(src, "Due", d)


# ── test-live ────────────────────────────────────────────────────────────────

def test_test_message_riga_piazzabile():
    b = pb.ParserBuilder()
    b.name = "Yangon"
    b.add_rule("Provider", fixed_value="TG_CUSTOM")
    b.add_rule("EventName", start_after="Match:", end_before="\n", required=True)
    b.add_rule("MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True)
    b.add_rule("SelectionName", start_after="Sel:", end_before="\n", required=True)
    b.add_rule("Price", start_after="Quota:", end_before="\n", required=True)
    b.add_rule("BetType", start_after="Lato:", value_map="bettype", required=True)
    res = b.test_message("Match: Inter v Milan\nSel: Sì\nQuota: 1,85\nLato: BACK")
    assert res.status == validator.VALID
    assert res.placeable is True
    assert res.row["BetType"] == "PUNTA"
    assert res.row["Price"] == "1.85"


def test_test_message_inoltra_name_mapping_profiles():
    # L'anteprima deve tradurre l'EventName quando il parser usa la mappatura nomi e i
    # profili risolti sono passati (come fa la GUI risolvendoli da config).
    b = pb.ParserBuilder()
    b.name = "Map"
    b.name_mapping_profiles = ["Premier"]
    b.team_separator = "v"
    b.add_rule("Provider", fixed_value="TG_CUSTOM")
    b.add_rule("EventName", start_after="Match:", end_before="\n", required=True)
    b.add_rule("MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True)
    b.add_rule("SelectionName", start_after="Sel:", end_before="\n", required=True)
    b.add_rule("Price", start_after="Quota:", end_before="\n", required=True)
    b.add_rule("BetType", start_after="Lato:", value_map="bettype", required=True)
    msg = "Match: Liverpool FC v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"
    profiles = [[
        {"country": "", "betfair": "Liverpool", "provider": "Liverpool FC"},
        {"country": "", "betfair": "Leeds", "provider": "Leeds Utd"},
    ]]
    res = b.test_message(msg, name_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Liverpool - Leeds"     # tradotto come il runtime
    # Senza profili risolti (None) la mappatura richiesta fa fail-closed in anteprima.
    res_none = b.test_message(msg, name_mapping_profiles=None)
    assert res_none.placeable is False


def test_test_message_inoltra_market_mapping_profiles():
    # L'anteprima deve impostare Mercato/Selezione quando il parser usa la mappatura mercati
    # e i profili risolti sono passati (come fa la GUI risolvendoli da config).
    b = pb.ParserBuilder()
    b.name = "Mkt"
    b.mode = "NAME_ONLY"
    b.market_mapping_profiles = ["Pandora"]
    b.add_rule("Provider", fixed_value="TG")
    b.add_rule("EventName", fixed_value="Inter v Milan", required=True)
    b.add_rule("MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True)
    b.add_rule("SelectionName", fixed_value="No", required=True)
    b.add_rule("Price", fixed_value="1.85", required=True)
    b.add_rule("BetType", fixed_value="PUNTA", required=True)
    # Coppia reale del Catalogo XTrader; il mercato si legge dal campo delimitato.
    profiles = [[{"start_after": "Mercato:", "end_before": "\n", "phrase": "gol gol",
                  "market_type": "", "market_name": "Entrambe le squadre a segno",
                  "selection_name": "Sì"}]]
    res = b.test_message("consiglio\nMercato: gol gol\n", market_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["SelectionName"] == "Sì"        # dizionario vince sul "No" della colonna


def test_test_message_non_pronto():
    b = pb.ParserBuilder()
    b.name = "X"
    b.add_rule("Price", start_after="Quota:", required=True)
    res = b.test_message("nessuna quota")
    assert res.placeable is False


def test_init_da_definizione_copia_le_regole():
    base = cp.skeleton("Base")
    b = pb.ParserBuilder(base)
    assert b.name == "Base"
    b.update_rule(0, fixed_value="ALTRO")     # modifica la copia
    assert base.rules[0].fixed_value != "ALTRO"  # l'originale non cambia


# ── Modalità per-parser + auto-obbligatori + griglia 14 colonne (PR-4) ───────

_RECOG = ("EventName", "MarketType", "SelectionName", "MarketId", "SelectionId")


def test_set_mode_allinea_obbligatori_alla_modalita():
    # set_mode ALLINEA i required dei campi di riconoscimento alla modalità: il set
    # scelto diventa required, l'altro set viene sbloccato (no required "stantii", Codex).
    b = pb.ParserBuilder()
    for t in (*_RECOG, "Price"):
        b.add_rule(target=t)
    b.set_mode("ID_ONLY")
    assert b.mode == "ID_ONLY"
    assert {r.target for r in b.rules if r.required} == {"MarketId", "SelectionId"}
    b.set_mode("NAME_ONLY")               # cambio: ID sbloccati, NAME obbligatori
    assert {r.target for r in b.rules if r.required} == {"EventName", "MarketType", "SelectionName"}
    # Price NON è un campo di riconoscimento: la modalità non lo tocca mai.
    assert next(r for r in b.rules if r.target == "Price").required is False


def test_set_mode_both_non_forza_alcun_set():
    b = pb.ParserBuilder()
    for t in _RECOG:
        b.add_rule(target=t, required=True)
    b.set_mode("BOTH")                      # basta un set → nessun campo di riconoscimento forzato
    assert all(not r.required for r in b.rules if r.target in _RECOG)


def test_ensure_all_columns_14_in_ordine_preserva_esistenti():
    b = pb.ParserBuilder()
    b.add_rule(target="Price", fixed_value="1.85")
    b.ensure_all_columns()
    assert [r.target for r in b.rules] == list(CSV_HEADER)        # 14, ordine contratto
    assert next(r for r in b.rules if r.target == "Price").fixed_value == "1.85"  # preservata


def test_to_def_include_mode():
    b = pb.ParserBuilder()
    b.add_rule(target="Provider", fixed_value="X")
    b.set_mode("ID_ONLY")
    assert b.to_def().mode == "ID_ONLY"
