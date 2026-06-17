"""Test del ponte Parser Personalizzato → riga CSV validata (CP-04).

Esercitano `xtrader_bridge.custom_pipeline.build_validated_row`: i due gate
(parser "Non pronto" + validator) e i default del contratto.
"""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER


def _full_parser():
    """Parser che, su un messaggio completo, produce una riga NAME_ONLY valida."""
    return cp.CustomParserDef(name="Yangon", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
    ])


_MSG_OK = "Match: Inter v Milan\nSel: Sì\nQuota: 1,85\nLato: BACK"


def test_riga_valida_piazzabile():
    res = pipe.build_validated_row(_full_parser(), _MSG_OK)
    assert res.status == validator.VALID
    assert res.placeable is True
    assert list(res.row.keys()) == CSV_HEADER          # 14 colonne, ordine contratto
    assert res.row["EventName"] == "Inter v Milan"
    assert res.row["BetType"] == "PUNTA"               # value-map applicata
    assert res.row["Price"] == "1.85"                  # virgola → punto (contratto)
    assert res.row["Handicap"] == "0"                  # default contratto
    assert res.row["Points"] == ""                     # default contratto (vuoto)


def test_handicap_points_non_sovrascritti_se_impostati():
    # Se il parser valorizza Handicap/Points, i default del contratto NON devono
    # sovrascriverli (guardia anti-regressione su _with_contract_defaults).
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="Handicap", fixed_value="-1"),
        cp.FieldRule(target="Points", fixed_value="3"),
    ])
    res = pipe.build_validated_row(defn, "qualsiasi")
    assert res.status == validator.VALID
    assert res.row["Handicap"] == "-1"   # non sovrascritto dal default "0"
    assert res.row["Points"] == "3"      # non sovrascritto dal default ""


def test_non_pronto_se_manca_obbligatorio():
    msg = "Match: Inter v Milan\nSel: Sì\nLato: BACK"   # manca Quota (Price)
    res = pipe.build_validated_row(_full_parser(), msg)
    assert res.status == pipe.NOT_READY
    assert res.placeable is False
    assert res.missing_required == ["Price"]


def test_invalid_price_quota_uno():
    msg = "Match: Inter v Milan\nSel: Sì\nQuota: 1.00\nLato: BACK"
    res = pipe.build_validated_row(_full_parser(), msg)
    assert res.status == validator.INVALID_PRICE
    assert res.placeable is False


def test_invalid_bettype_lato_sconosciuto():
    # BetType opzionale con value-map: lato non riconosciuto → "" → INVALID_BETTYPE
    # (non NOT_READY, perché qui BetType non è obbligatorio della regola).
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype"),
    ])
    res = pipe.build_validated_row(defn, "Lato: testacroce")
    assert res.status == validator.INVALID_BETTYPE
    assert res.placeable is False


def test_invalid_missing_fields_modalita_nome():
    # Parser non marca MarketType obbligatorio, ma NAME_ONLY lo richiede →
    # passa il gate parser ma il validator scarta per campo nome mancante.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "qualsiasi")
    assert res.status == validator.INVALID_MISSING_FIELDS
    assert "MarketType" in res.detail


def test_require_price_false_bypassa_prezzo():
    msg = "Match: Inter v Milan\nSel: Sì\nLato: BACK"   # nessun prezzo
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
    ])
    res = pipe.build_validated_row(defn, msg, require_price=False)
    assert res.status == validator.VALID
    assert res.placeable is True


def test_bettype_minuscolo_normalizzato():
    # BetType "punta" (senza value-map) → normalizzato a "PUNTA" nel contratto.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="punta", required=True),
    ])
    res = pipe.build_validated_row(defn, "qualsiasi")
    assert res.status == validator.VALID
    assert res.row["BetType"] == "PUNTA"


def test_provider_dal_runtime_se_assente():
    # Una regola senza Provider: il provider del runtime riempie la colonna.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    ok = pipe.build_validated_row(defn, "x", provider="TelegramBot")
    assert ok.status == validator.VALID
    assert ok.row["Provider"] == "TelegramBot"
    # senza provider e senza regola Provider → non piazzabile
    ko = pipe.build_validated_row(defn, "x")
    assert ko.status == pipe.INVALID_MISSING_PROVIDER
    assert ko.placeable is False


def test_prezzo_virgola_normalizzato_a_punto():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "Quota: 2,50")
    assert res.status == validator.VALID
    assert res.row["Price"] == "2.50"


def test_prezzo_non_finito_rifiutato():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="inf", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "x")
    assert res.status == validator.INVALID_PRICE
    assert res.placeable is False


def test_minprice_malformato_rifiutato():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="MinPrice", fixed_value="abc"),
    ])
    res = pipe.build_validated_row(defn, "x")
    assert res.status == validator.INVALID_PRICE
    assert res.placeable is False


def test_value_map_dizionario_di_default():
    # Senza passare un registro, le value-map del dizionario sono disponibili:
    # "GG" → MarketType/SelectionName risolti dal dizionario.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", start_after="M:", value_map="markettype", required=True),
        cp.FieldRule(target="SelectionName", start_after="S:", value_map="selectionname", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "M: GG\nS: GG")
    assert res.status == validator.VALID
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert res.row["SelectionName"] == "Sì"


def test_prezzo_esponente_rifiutato():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="1e2", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "x")
    assert res.status == validator.INVALID_PRICE
    assert res.placeable is False


def test_require_price_false_ma_prezzo_malformato_rifiutato():
    # require_price=False ammette il prezzo ASSENTE, ma un Price presente e
    # malformato va comunque scartato.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="abc"),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    res = pipe.build_validated_row(defn, "x", require_price=False)
    assert res.status == validator.INVALID_PRICE
    assert res.placeable is False


def test_handicap_malformato_rifiutato():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="Handicap", fixed_value="abc"),
    ])
    res = pipe.build_validated_row(defn, "x")
    assert res.status == pipe.INVALID_HANDICAP
    assert res.placeable is False


def test_handicap_negativo_decimale_ok():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="Handicap", fixed_value="-0.5"),
    ])
    res = pipe.build_validated_row(defn, "x")
    assert res.status == validator.VALID
    assert res.row["Handicap"] == "-0.5"


def test_is_placeable_scorciatoia():
    assert pipe.is_placeable(_full_parser(), _MSG_OK) is True
    assert pipe.is_placeable(_full_parser(), "vuoto") is False
