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

import csv

from xtrader_bridge import csv_writer
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


def _parser_raw_bettype():
    """Parser NAME_ONLY che ESTRAE il BetType dal messaggio **senza value-map** (`bettype`): il
    lato inglese grezzo arriva al confine del contratto così com'è. Estrae anche EventName/Price
    dal messaggio (serve un content-match reale, altrimenti il gate CP-09 scarta il parser)."""
    return cp.CustomParserDef(name="RawBT", mode="NAME_ONLY", sport="Calcio", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", end_before="\n", required=True),
    ])


def test_csv_finale_mai_bettype_grezzo_back_lay(tmp_path):
    """Issue #3 (verifica dei reviewer GLM/GPT/Fable/Fugu): nessun percorso di scrittura CSV deve
    emettere un `BACK`/`LAY` GREZZO. Catena completa fino al FILE: `resolve_row` → `write_rows` →
    file su disco → il `BetType` scritto è SEMPRE canonico `PUNTA`/`BANCA` (universale), mai
    l'input inglese. Fail-first: senza la canonicalizzazione a monte il file conterrebbe `BACK`."""
    for side, expected in (("BACK", "PUNTA"), ("LAY", "BANCA")):
        defn = _parser_raw_bettype()
        defn.name = f"RawBT_{side}"
        cp.save_parser(defn, str(tmp_path))
        msg = f"Match: Inter v Milan\nLato: {side}\nQuota: 1,85\n"   # trailing \n: end_before delle righe
        res = signal_router.resolve_row(msg, _cfg(defn.name), chat_id="42",
                                        parsers_dir=str(tmp_path))
        assert res.placeable is True, side
        assert res.row["BetType"] == expected, side       # riga già canonica
        path = str(tmp_path / f"segnali_{side}.csv")
        csv_writer.write_rows([res.row], path)
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1, side
        assert rows[0]["BetType"] == expected, side       # sul FILE: canonico, mai BACK/LAY grezzo
        assert rows[0]["Points"] == "", side              # Points resta vuoto anche sul FILE


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


def test_quota_cifre_non_ascii_scartata_end_to_end(tmp_path):
    # #318 L2-1 end-to-end: un messaggio Telegram con quota in cifre NON-ASCII («١٩», arabo)
    # deve produrre una riga NON piazzabile (nessuna scrittura CSV). Prima del fix `\d` matchava
    # l'Unicode e float("١٩")==19.0 → la riga sarebbe stata piazzabile con "١٩" nel Price, valore
    # che XTrader non sa leggere. Percorso reale: messaggio → parser custom → validatore → router.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    msg = "Match: Inter v Milan\nEsito: GG\nQuota: ١٩\nLato: BACK"
    res = signal_router.resolve_row(msg, _cfg("Esempio"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False       # quota non-ASCII → scartata, nessuna riga nel CSV


def test_quota_con_punto_end_to_end(tmp_path):
    # Linee guida parser: quota sia con virgola sia con PUNTO. Qui "1.85" deve
    # restare "1.85" (già col punto) e produrre una riga piazzabile.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    msg = "Match: Inter v Milan\nEsito: GG\nQuota: 1.85\nLato: BACK"
    res = signal_router.resolve_row(msg, _cfg("Esempio"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.row["Price"] == "1.85"


def test_messaggio_vuoto_o_non_supportato_scarta(tmp_path):
    # Linee guida parser: messaggio vuoto/non supportato → nessuna riga. Con un
    # parser custom attivo restano source=CUSTOM e placeable=False (resolve_row è
    # puro: niente CSV scritto; la garanzia "non scrive" è proprio placeable=False).
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    for msg in ("", "testo non supportato"):
        res = signal_router.resolve_row(msg, _cfg("Esempio"),
                                        chat_id="42", parsers_dir=str(tmp_path))
        assert res.source == signal_router.CUSTOM
        assert res.placeable is False
        assert res.row is None


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


# ── caso reale: provider P.Bet con emoji 🆚 e quota assente ─────────────────

def test_pbet_gol_secondo_tempo_yangon_end_to_end(tmp_path):
    """Messaggio reale di un provider 'P.Bet' (emoji 🆚 davanti alle squadre, nessuna
    quota di puntata). Regressione: la catena attuale lo gestisce senza modifiche —
    EventName estratto **dopo 🆚** fino a fine riga; mercato/selezione tradotti dal
    dizionario via fixed_value+value_map; Price assente AMMESSO perché il parser NON
    marca `Price` obbligatorio (`price_required()` False → quota opzionale, unico
    comando dalla riga Price). Nessun campo inventato."""
    defn = cp.CustomParserDef(name="PBetGol2T", rules=[
        cp.FieldRule(target="Provider", fixed_value="P.Bet"),
        # "🆚Yangon City v Silver Stars FC" → tutto dopo 🆚 fino a fine riga.
        cp.FieldRule(target="EventName", start_after="\U0001F19A", end_before="\n", required=True),
        # Mercato/selezione scelti dall'utente (Over 0.5 HT) e tradotti dal dizionario.
        cp.FieldRule(target="MarketType", fixed_value="over 0.5 ht", value_map="markettype", required=True),
        cp.FieldRule(target="MarketName", fixed_value="over 0.5 ht", value_map="marketname"),
        cp.FieldRule(target="SelectionName", fixed_value="over 0.5 ht", value_map="selectionname", required=True),
        cp.FieldRule(target="BetType", fixed_value="BACK", value_map="bettype", required=True),
        cp.FieldRule(target="Handicap", fixed_value="0"),
    ])
    cp.save_parser(defn, str(tmp_path))
    msg = (
        "P.Bet. GOL SECONDO TEMPO LIVE \U0001F4E3✔️\n\n"
        "\U0001F3C6 Myanmar National League 2 League\n"
        "\U0001F19AYangon City v Silver Stars FC\n"
        "⚽ 6 - 0\n"
        "⏱ 46m\n"
        "\U0001F4C8Quota 0,5 HT\n"
        "Prematch:0"
    )
    res = signal_router.resolve_row(msg, _cfg("PBetGol2T"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    assert list(res.row.keys()) == CSV_HEADER
    assert res.row["EventName"] == "Yangon City v Silver Stars FC"
    assert res.row["MarketType"] == "FIRST_HALF_GOALS_05"
    assert res.row["MarketName"] == "1º tempo - Totale goal 0,5"
    assert res.row["SelectionName"] == "Over 0,5 goal"
    assert res.row["BetType"] == "PUNTA"            # "BACK" via value-map bettype
    assert res.row["Price"] == ""                   # quota assente ammessa (Price opzionale)
    assert res.row["Handicap"] == "0"


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
    # active_parser globale ma chat_id vuoto: una chat arbitraria NON usa il custom e,
    # col parser automatico disattivato (CP-09b), il messaggio è ignorato.
    defn = parser_io.example_parser()
    defn.name = "Esempio"
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "Esempio", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="999", parsers_dir=str(tmp_path))
    assert res.source == signal_router.NO_PARSER
    assert res.placeable is False


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
