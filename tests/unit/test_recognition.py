"""Test delle modalità di riconoscimento (PR-06)."""

from xtrader_bridge import recognition as rec


def _name_row(**over):
    row = {"EventName": "Inter v Milan", "MarketType": "MATCH_ODDS",
           "SelectionName": "Inter", "MarketId": "", "SelectionId": ""}
    row.update(over)
    return row


def _id_row(**over):
    row = {"EventName": "", "MarketType": "", "SelectionName": "",
           "MarketId": "1.234", "SelectionId": "55"}
    row.update(over)
    return row


def test_modi_validi():
    # Confronto come set: non dipende dall'ordine.
    assert set(rec.VALID_MODES) == {"ID_ONLY", "NAME_ONLY", "BOTH"}
    assert rec.DEFAULT_MODE in rec.VALID_MODES
    assert rec.DEFAULT_MODE == "NAME_ONLY"


def test_normalize_mode_sconosciuto_fallback_name_only():
    assert rec.normalize_mode("BOH") == "NAME_ONLY"
    assert rec.normalize_mode("ID_ONLY") == "ID_ONLY"


def test_name_only_completo_valido():
    assert rec.is_valid(_name_row(), "NAME_ONLY") is True


def test_name_only_senza_eventname_invalido():
    assert rec.missing_fields(_name_row(EventName=""), "NAME_ONLY") == ["EventName"]
    assert rec.is_valid(_name_row(EventName=""), "NAME_ONLY") is False


def test_name_only_senza_selectionname_invalido():
    assert "SelectionName" in rec.missing_fields(_name_row(SelectionName=""), "NAME_ONLY")


def test_id_only_completo_valido():
    assert rec.is_valid(_id_row(), "ID_ONLY") is True


def test_id_only_senza_marketid_invalido():
    assert rec.missing_fields(_id_row(MarketId=""), "ID_ONLY") == ["MarketId"]


def test_both_valido_se_solo_nomi():
    # Nessun ID ma nomi completi -> valido in BOTH.
    assert rec.is_valid(_name_row(), "BOTH") is True


def test_both_valido_se_solo_id():
    assert rec.is_valid(_id_row(), "BOTH") is True


def test_both_invalido_se_nessun_set_completo():
    row = _name_row(EventName="", MarketId="", SelectionId="")  # né nomi né ID completi
    assert rec.is_valid(row, "BOTH") is False
    # Solo EventName manca nel set nomi (MarketType/SelectionName presenti).
    assert rec.missing_fields(row, "BOTH") == ["EventName"]


def test_modalita_sconosciuta_tratta_come_name_only():
    assert rec.is_valid(_name_row(), "QUALCOSA") is True
    assert rec.is_valid(_id_row(), "QUALCOSA") is False  # nomi mancanti


def test_segnale_reale_costruito_e_valido_name_only():
    # Un segnale RICONOSCIUTO dal dizionario costruito da build_csv_row NON deve essere
    # scartato: la selezione viene dal dizionario (reale), non inventata dal fallback (A1).
    from xtrader_bridge.csv_writer import build_csv_row
    parsed = {"signal_type": "GG", "teams": "Inter v Milan",
              "quota": "1.85", "bet_type": "BACK"}
    row = build_csv_row(parsed, "PBet")
    assert row["SelectionName"] == "Sì"
    assert rec.is_valid(row, "NAME_ONLY") is True


def test_segnale_senza_squadre_scartato_name_only():
    # Messaggio senza squadre (EventName vuoto) -> non riconoscibile -> scartato.
    from xtrader_bridge.csv_writer import build_csv_row
    parsed = {"signal_type": "MATCH ODDS", "teams": "", "quota": "1.85", "bet_type": "BACK"}
    row = build_csv_row(parsed, "PBet")
    assert rec.is_valid(row, "NAME_ONLY") is False


# ── required_targets: campi auto-obbligatori per modalità (PR-4) ─────────────

def test_required_targets_per_modalita():
    assert rec.required_targets("NAME_ONLY") == ("EventName", "MarketType", "SelectionName")
    assert rec.required_targets("ID_ONLY") == ("MarketId", "SelectionId")
    assert rec.required_targets("BOTH") == ()                 # basta un set → non forza
    assert rec.required_targets("boh") == ("EventName", "MarketType", "SelectionName")  # default
    for f in rec.required_targets("ID_ONLY") + rec.required_targets("NAME_ONLY"):
        assert f in rec.RECOGNITION_FIELDS


def test_recognition_fields_for_mode():
    # Content-gate A10 (Codex P2): campi di riconoscimento RILEVANTI per la modalità.
    assert rec.recognition_fields_for_mode("NAME_ONLY") == ("EventName", "MarketType", "SelectionName")
    assert rec.recognition_fields_for_mode("ID_ONLY") == ("MarketId", "SelectionId")
    # BOTH → entrambi i set (basta un set, quindi ognuno conta come segnale).
    assert rec.recognition_fields_for_mode("BOTH") == rec.RECOGNITION_FIELDS
    # Modalità sconosciuta → default sicuro (NAME_ONLY).
    assert rec.recognition_fields_for_mode("boh") == ("EventName", "MarketType", "SelectionName")
