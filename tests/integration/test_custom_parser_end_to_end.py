"""Integrazione end-to-end del Parser Personalizzato (CP-10: CUSTOM_PARSER_READY).

Esercita l'INTERA catena con funzioni reali, dal messaggio Telegram alla riga
CSV decisa dal router, senza GUI né scrittura su disco del CSV:

    messaggio → estrazione (CP-02, delimitatori tolleranti agli spazi)
              → trasformazione (CP-05) → value-map (CP-03)
              → riga validata col contratto (CP-04)
              → instradamento live + gate sicurezza (CP-07/CP-09)

Verifica anche le invarianti di sicurezza: parser autoritativo (niente fallback
hardcoded quando attivo), gate "Non pronto", gate di contenuto (parser a soli
valori fissi), approvazione della chat. È la prova di "pronto" della PHASE 3-bis.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io, signal_router
from xtrader_bridge.csv_writer import CSV_HEADER


def _cfg(name, chat="42", **extra):
    cfg = {"provider": "TG", "active_parser": name, "chat_id": chat,
           "recognition_mode": "NAME_ONLY"}
    cfg.update(extra)
    return cfg


# ── catena completa: parser d'esempio → riga piazzabile ─────────────────────

def test_esempio_end_to_end_riga_completa(tmp_path):
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("Esempio"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    # riga conforme al contratto a 14 colonne, valori tradotti dal dizionario/bettype
    assert list(res.row.keys()) == CSV_HEADER
    assert res.row["EventName"] == "Inter v Milan"
    assert res.row["SelectionName"] == "Sì"        # "GG" via value-map dizionario
    assert res.row["BetType"] == "PUNTA"           # "BACK" via value-map bettype
    assert res.row["Price"] == "1.85"              # virgola → punto
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert res.row["Handicap"] == "0"              # default contratto
    assert res.row["Points"] == ""                 # default contratto


def test_tolleranza_spazi_nei_delimitatori_end_to_end(tmp_path):
    # Lo stesso parser deve estrarre anche se nel messaggio i delimitatori hanno
    # spazi extra: la tolleranza agli spazi (extract_value) arriva fino al router.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    msg = "Match:   Inter v Milan\nEsito:  GG\nQuota:   1,85\nLato:  BACK"
    res = signal_router.resolve_row(msg, _cfg("Esempio"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.row["EventName"] == "Inter v Milan"
    assert res.row["Price"] == "1.85"


# ── trasformazione somma-gol → Over (CP-05) lungo la catena ─────────────────

def test_transform_score_to_over_end_to_end(tmp_path):
    defn = cp.CustomParserDef(name="Somma", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="OVER_UNDER", required=True),
        cp.FieldRule(target="SelectionName", start_after="Risultato:", end_before="\n",
                     transform="score_to_over", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    cp.save_parser(defn, str(tmp_path))
    msg = "Match: Inter v Milan\nRisultato: 6-0\nQuota: 1,85\n"
    res = signal_router.resolve_row(msg, _cfg("Somma"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.row["SelectionName"] == "Over 6,5"   # "6-0" → somma 6 → Over 6,5
    assert res.row["Price"] == "1.85"


# ── invarianti di sicurezza ─────────────────────────────────────────────────

def test_non_pronto_scarta_senza_fallback(tmp_path):
    # Custom attivo ma messaggio incompleto: scarto, niente ripiego sull'hardcoded.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    res = signal_router.resolve_row("Match: solo questo", _cfg("Esempio"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is False


def test_parser_solo_fissi_non_scrive_su_messaggio_arbitrario(tmp_path):
    # Gate di contenuto: obbligatori tutti fissi → non deve scrivere su testo a caso.
    defn = cp.CustomParserDef(name="Fissi", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    cp.save_parser(defn, str(tmp_path))
    res = signal_router.resolve_row("ciao", _cfg("Fissi"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is False
    assert res.status == signal_router.NO_CONTENT_MATCH


def test_chat_non_approvata_non_usa_parser_globale(tmp_path):
    # active_parser globale ma chat_id vuoto: una chat arbitraria NON usa il custom.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "Esempio", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="999", parsers_dir=str(tmp_path))
    assert res.source == signal_router.HARDCODED


def test_override_per_chat_end_to_end(tmp_path):
    # parser_by_chat senza chat_id singolo: il chat id del messaggio attiva l'override.
    defn = parser_io.example_parser()
    defn.name = "PerChat"
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"},
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="123", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
