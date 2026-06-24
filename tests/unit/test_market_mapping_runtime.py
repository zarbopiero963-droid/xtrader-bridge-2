"""Test end-to-end dell'aggancio runtime della mappatura mercati a frase (FASE 2 passo 2).

Coprono il flusso `custom_pipeline.build_validated_row` con `market_mapping_profiles`, la
serializzazione del nuovo campo `CustomParserDef.market_mapping_profiles`, il round-trip del
`ParserBuilder` e l'instradamento reale (`signal_router.resolve_row`). Decisioni di design:
D1 (il dizionario VINCE sulle regole-colonna), D2 (ambiguità fail-closed), D3 (match sul
messaggio grezzo). Vedi `docs/audit/mercati_mapping_design.md`.

Coppie Mercato/Selezione REALI del Catalogo XTrader (resolve_market valida col catalogo):
"Entrambe le squadre a segno"/"Sì"|"No" → MarketType canonico "BOTH_TEAMS_TO_SCORE".
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import parser_builder, signal_router, validator


# ── parser/voci di supporto ──────────────────────────────────────────────────

def _entry(phrase, market="Entrambe le squadre a segno", selection="Sì"):
    return {"phrase": phrase, "market_type": "", "market_name": market,
            "selection_name": selection}


def _market_parser(profiles=("Pandora",), *, with_market_cols=True,
                   col_selection="No"):
    """Parser NAME_ONLY a valori fissi (per build_validated_row, che non ha il gate di
    contenuto del router). Se `with_market_cols`, le regole-colonna impostano un mercato
    (MarketType + SelectionName) — utile a testare il fallback/override del dizionario."""
    rules = [
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="Price", fixed_value="1.85", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ]
    if with_market_cols:
        rules.append(cp.FieldRule(target="MarketType",
                                  fixed_value="BOTH_TEAMS_TO_SCORE", required=True))
        rules.append(cp.FieldRule(target="SelectionName",
                                  fixed_value=col_selection, required=True))
    return cp.CustomParserDef(name="Mkt", mode="NAME_ONLY",
                              market_mapping_profiles=list(profiles), rules=rules)


# ── build_validated_row: regola di precedenza D1 e fail-safe ─────────────────

def test_pipeline_dizionario_vince_sulla_colonna():
    # D1: la colonna dice Selezione "No"; una frase combacia e dice "Sì" → vince il dizionario.
    profiles = [[_entry("gol gol", selection="Sì")]]
    res = pipe.build_validated_row(_market_parser(col_selection="No"),
                                   "Consiglio: gol gol, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == validator.VALID and res.placeable is True
    # valori CANONICI del catalogo (non quelli grezzi del config: market_type era "")
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert res.row["MarketName"] == "Entrambe le squadre a segno"
    assert res.row["SelectionName"] == "Sì"          # sovrascrive il "No" della colonna


def test_pipeline_ambiguo_market_mapping_missing():
    # D2: due frasi combaciano e indicano selezioni DIVERSE → fail-closed, niente riga.
    profiles = [[_entry("gol gol", selection="Sì"), _entry("no gol", selection="No")]]
    res = pipe.build_validated_row(_market_parser(),
                                   "scommetti gol gol e no gol",
                                   market_mapping_profiles=profiles)
    assert res.status == pipe.MARKET_MAPPING_MISSING
    assert res.placeable is False


def test_pipeline_none_fallback_regola_colonna():
    # Nessuna frase combacia, ma la colonna ha un mercato (MarketType+SelectionName) → si
    # tiene il valore della colonna, la riga è valida.
    profiles = [[_entry("frase assente")]]
    res = pipe.build_validated_row(_market_parser(col_selection="No"),
                                   "nessuna frase mercato qui, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == validator.VALID and res.placeable is True
    assert res.row["SelectionName"] == "No"          # valore della regola-colonna preservato


def test_pipeline_none_senza_mercato_colonna_failclosed():
    # Nessuna frase combacia E nessun mercato dalle regole-colonna → MARKET_MAPPING_MISSING
    # (niente mercato inventato), invece di lasciar passare una riga senza mercato.
    profiles = [[_entry("frase assente")]]
    res = pipe.build_validated_row(_market_parser(with_market_cols=False),
                                   "nessuna frase mercato qui, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == pipe.MARKET_MAPPING_MISSING
    assert res.placeable is False


def test_pipeline_voce_incoerente_col_catalogo_ignorata_fallback():
    # Voce del dizionario con coppia NON nel catalogo: la frase combacia ma resolve la
    # ignora → "none" → fallback alla regola-colonna (mai scrivere un mercato non canonico).
    profiles = [[_entry("gol gol", market="Mercato Inventato", selection="Sel X")]]
    res = pipe.build_validated_row(_market_parser(col_selection="No"),
                                   "gol gol, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["SelectionName"] == "No"          # colonna, non la voce incoerente
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"


def test_pipeline_profili_none_con_colonna_resta_valida():
    # Profili None (anteprima senza config) = nessuna voce = "none": con un mercato dalle
    # regole-colonna la riga resta valida (i mercati ripiegano sulla colonna, a differenza
    # dei nomi che sono obbligatori).
    res = pipe.build_validated_row(_market_parser(col_selection="No"),
                                   "gol gol, quota 1.85",
                                   market_mapping_profiles=None)
    assert res.status == validator.VALID
    assert res.row["SelectionName"] == "No"


def test_pipeline_profili_none_senza_colonna_failclosed():
    # Profili None + nessun mercato dalle regole → fail-closed: l'anteprima NON mostra
    # "Pronto" per un mercato che il runtime non saprebbe risolvere.
    res = pipe.build_validated_row(_market_parser(with_market_cols=False),
                                   "gol gol, quota 1.85",
                                   market_mapping_profiles=None)
    assert res.status == pipe.MARKET_MAPPING_MISSING


def test_pipeline_nessun_profilo_mercati_retrocompat():
    # Parser SENZA profili mercati → l'hook è saltato del tutto, colonne invariate.
    defn = _market_parser(profiles=(), col_selection="No")
    res = pipe.build_validated_row(defn, "gol gol, quota 1.85",
                                   market_mapping_profiles=[[_entry("gol gol")]])
    assert res.status == validator.VALID
    assert res.row["SelectionName"] == "No"          # nessuna sovrascrittura


def test_pipeline_override_azzera_id_stantii_both():
    # CodeRabbit (Major): un parser BOTH che ha estratto MarketId/SelectionId dalle
    # regole-colonna NON deve conservarli quando il dizionario (NAME-based) vince, o la
    # riga porterebbe identificatori di mercato CONTRADDITTORI. La coppia ID va azzerata;
    # in BOTH basta la coppia a nome → resta VALID, ma senza ID stantii.
    defn = cp.CustomParserDef(
        name="MktBoth", mode="BOTH", market_mapping_profiles=["Pandora"],
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
            cp.FieldRule(target="Price", fixed_value="1.85", required=True),
            cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
            cp.FieldRule(target="MarketType", fixed_value="MATCH_ODDS"),
            cp.FieldRule(target="SelectionName", fixed_value="1"),
            cp.FieldRule(target="MarketId", fixed_value="1.234"),       # ID stantio
            cp.FieldRule(target="SelectionId", fixed_value="999"),      # ID stantio
        ])
    profiles = [[_entry("gol gol", selection="Sì")]]
    res = pipe.build_validated_row(defn, "gol gol, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == validator.VALID and res.placeable is True
    assert res.row["SelectionName"] == "Sì"          # mercato a nome dal dizionario
    assert res.row["MarketName"] == "Entrambe le squadre a segno"
    assert res.row["MarketId"] == "" and res.row["SelectionId"] == ""  # ID stantii azzerati


def test_pipeline_override_id_only_failclosed():
    # Parser ID_ONLY + mappatura mercati a frase (config incoerente): quando il dizionario
    # vince, gli ID vengono azzerati e la modalità ID non ha più un mercato → fail-closed
    # (niente riga), invece di scommettere su ID che contraddicono la frase.
    defn = cp.CustomParserDef(
        name="MktId", mode="ID_ONLY", market_mapping_profiles=["Pandora"],
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="Price", fixed_value="1.85", required=True),
            cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
            cp.FieldRule(target="MarketId", fixed_value="1.234", required=True),
            cp.FieldRule(target="SelectionId", fixed_value="999", required=True),
        ])
    profiles = [[_entry("gol gol", selection="Sì")]]
    res = pipe.build_validated_row(defn, "gol gol, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.placeable is False                     # ID azzerati → ID_ONLY senza mercato
    assert res.row["MarketId"] == "" and res.row["SelectionId"] == ""


def test_pipeline_match_sul_messaggio_grezzo_non_su_campo():
    # D3: la frase si cerca nel MESSAGGIO grezzo, non in EventName (qui "Inter v Milan",
    # che non contiene la frase). Il match avviene comunque → override.
    profiles = [[_entry("gol gol", selection="Sì")]]
    res = pipe.build_validated_row(_market_parser(),
                                   "Match Inter-Milan: gol gol consigliato, quota 1.85",
                                   market_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["SelectionName"] == "Sì"


# ── serializzazione del nuovo campo del parser ───────────────────────────────

def test_custom_parser_roundtrip_market_profiles():
    defn = _market_parser(profiles=("Pandora", "Bet365"))
    back = cp.CustomParserDef.from_json(defn.to_json())
    assert back.market_mapping_profiles == ["Pandora", "Bet365"]


def test_custom_parser_market_profiles_default_retrocompat():
    # File legacy senza la chiave → lista vuota (nessuna mappatura mercati).
    back = cp.CustomParserDef.from_dict({"name": "X", "rules": [{"target": "EventName"}]})
    assert back.market_mapping_profiles == []


def test_custom_parser_market_profiles_pulisce_input():
    # Voci non-stringa/spazi → ripulite (coerente con i profili nomi).
    back = cp.CustomParserDef.from_dict(
        {"name": "X", "market_mapping_profiles": ["  A  ", "", None, "B"],
         "rules": [{"target": "EventName"}]})
    assert back.market_mapping_profiles == ["A", "B"]


# ── round-trip del ParserBuilder ─────────────────────────────────────────────

def test_builder_preserva_market_profiles():
    defn = _market_parser(profiles=("Pandora",))
    b = parser_builder.ParserBuilder(defn)
    assert b.market_mapping_profiles == ["Pandora"]
    assert b.to_def().market_mapping_profiles == ["Pandora"]


def test_builder_nuovo_market_profiles_vuoto():
    assert parser_builder.ParserBuilder().market_mapping_profiles == []


# ── instradamento reale (signal_router) ──────────────────────────────────────

def _router_parser(name="MktR", profiles=("Pandora",)):
    """Parser che ESTRAE dal messaggio (supera il gate di contenuto del router)."""
    return cp.CustomParserDef(
        name=name, mode="NAME_ONLY", market_mapping_profiles=list(profiles),
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


def _router_cfg(name="MktR", entries=None):
    if entries is None:
        entries = [_entry("gol gol", selection="Sì")]
    return {"provider": "TG", "active_parser": name, "chat_id": "42",
            "recognition_mode": "NAME_ONLY",
            "market_mappings": {"Pandora": entries}}


_ROUTER_MSG = "gol gol\nMatch: Inter v Milan\nSel: No\nQuota: 1,85\nLato: BACK"


def test_router_applica_mappatura_mercati(tmp_path):
    cp.save_parser(_router_parser(), str(tmp_path))
    res = signal_router.resolve_row(_ROUTER_MSG, _router_cfg(),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM and res.placeable is True
    assert res.row["SelectionName"] == "Sì"          # frase → override del "No" estratto
    assert res.row["MarketName"] == "Entrambe le squadre a segno"


def test_router_ambiguo_scarta(tmp_path):
    cp.save_parser(_router_parser(), str(tmp_path))
    entries = [_entry("gol gol", selection="Sì"), _entry("no gol", selection="No")]
    msg = "gol gol no gol\nMatch: Inter v Milan\nSel: Sì\nQuota: 1,85\nLato: BACK"
    res = signal_router.resolve_row(msg, _router_cfg(entries=entries),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False                     # fail-closed: niente riga CSV
    assert res.status == pipe.MARKET_MAPPING_MISSING


def test_router_nessuna_frase_usa_colonna(tmp_path):
    # Nessuna frase nel messaggio: il router tiene la Selezione estratta dalla colonna.
    cp.save_parser(_router_parser(), str(tmp_path))
    msg = "Match: Inter v Milan\nSel: No\nQuota: 1,85\nLato: BACK"
    res = signal_router.resolve_row(msg, _router_cfg(),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.row["SelectionName"] == "No"
