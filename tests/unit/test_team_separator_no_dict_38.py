"""Test hard veritieri — Issue #38.

Separatore squadre attivo ANCHE senza dizionario nomi: riformatta l'`EventName` nel formato
XTrader «Casa - Trasferta» usando le squadre **verbatim** del messaggio (nessuna traduzione,
nessun nome inventato), con guardia anti-split per i separatori simbolici (solo forma spaziata,
nessun fallback compatto) così un separatore sbagliato non taglia dentro un nome col trattino/
slash interno.

Coprono i 3 casi del ramo EventName, la guardia `spaced_only`, la NON-cancellazione degli ID nel
percorso senza-dizionario, l'INVARIANZA del ramo dizionario, la parità preview↔runtime, la
propagazione multi-riga e gli avvisi non-fatali su preview/router.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import name_mapping_store, signal_router, validator
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule
from xtrader_bridge.parser_builder import ParserBuilder


# ── helper: parser SENZA dizionario che ricava l'EventName da un valore fisso ────────────────
def _fixed_parser(event, separator, *, extra_rules=(), profiles=()):
    """Parser minimo placeable in NAME_ONLY con EventName **fisso** = `event` e `separator`.
    `profiles` vuoto = nessun dizionario nomi (ramo #38). Price non richiesto nei test core."""
    rules = [
        FieldRule(target="Provider", fixed_value="TG"),
        FieldRule(target="EventName", fixed_value=event, required=True),
        FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
        FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
        FieldRule(target="BetType", fixed_value="PUNTA"),
        *extra_rules,
    ]
    return CustomParserDef(name="P", mode="NAME_ONLY",
                           name_mapping_profiles=list(profiles),
                           team_separator=separator, rules=rules)


def _event_of(defn):
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)
    return res


# ── caso 2: riformattazione «Casa - Trasferta» con separatore esplicito ──────────────────────

def test_separatore_alfabetico_v_riformatta():
    res = _event_of(_fixed_parser("Milan v Inter", "v"))
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Milan - Inter"
    assert res.warnings == []


def test_separatori_vari_spaziati_riformattano():
    for event, sep in [("Milan vs Inter", "vs"), ("Milan @ Inter", "@"),
                       ("Milan - Inter", "-"), ("Roma / Lazio", "/")]:
        res = _event_of(_fixed_parser(event, sep))
        assert res.row["EventName"] == ("Roma - Lazio" if sep == "/" else "Milan - Inter"), (event, sep)
        assert res.warnings == []


def test_trattino_interno_non_spezza():
    # Il separatore vero è "v"; i trattini interni ai nomi NON devono spezzare (forma spaziata).
    res = _event_of(_fixed_parser("Paris Saint-Germain v Lyon", "v"))
    assert res.row["EventName"] == "Paris Saint-Germain - Lyon"
    assert res.warnings == []


def test_caso_reale_al_kholood_sep_v():
    # Caso reale dell'issue: `🆚Al-Kholood Club v Al-Hilal`, separatore vero "v".
    res = _event_of(_fixed_parser("Al-Kholood Club v Al-Hilal", "v"))
    assert res.row["EventName"] == "Al-Kholood Club - Al-Hilal"
    assert res.warnings == []


def test_slash_spaziato_riformatta_preserva_trattino_interno():
    res = _event_of(_fixed_parser("Paris Saint-Germain / Lyon", "/"))
    assert res.row["EventName"] == "Paris Saint-Germain - Lyon"
    assert res.warnings == []


# ── guardia anti-split: separatore simbolico SBAGLIATO → verbatim + avviso, MAI taglio interno ─

def test_separatore_simbolico_sbagliato_non_taglia_dentro_nome():
    # sep "-" su "Al-Kholood Club v Al-Hilal": non esiste " - " spaziato → NIENTE fallback compatto
    # nel percorso senza-dizionario → nome VERBATIM + avviso (mai "Al" / "Kholood Club v Al-Hilal").
    res = _event_of(_fixed_parser("Al-Kholood Club v Al-Hilal", "-"))
    assert res.row["EventName"] == "Al-Kholood Club v Al-Hilal"    # invariato
    assert res.warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]


def test_slash_compatto_non_spezza_senza_forma_spaziata():
    # "Marseille/Lyon" con sep "/": nessuna forma spaziata → verbatim + avviso (no split compatto).
    res = _event_of(_fixed_parser("Marseille/Lyon", "/"))
    assert res.row["EventName"] == "Marseille/Lyon"
    assert res.warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]


def test_separatore_assente_nel_nome_verbatim_piu_avviso():
    res = _event_of(_fixed_parser("Milan Inter", "v"))     # nessun " v " nel nome
    assert res.row["EventName"] == "Milan Inter"
    assert res.warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]


# ── caso 3 + retro-compatibilità: separatore vuoto → verbatim, nessun default "v", nessun avviso ─

def test_separatore_vuoto_verbatim_nessun_default():
    res = _event_of(_fixed_parser("Milan v Inter", ""))
    assert res.row["EventName"] == "Milan v Inter"      # verbatim, NON riformattato
    assert res.warnings == []


def test_separatore_solo_spazi_verbatim():
    res = _event_of(_fixed_parser("Milan v Inter", "   "))
    assert res.row["EventName"] == "Milan v Inter"
    assert res.warnings == []


# ── il percorso senza-dizionario NON azzera gli ID (stesso evento, solo formato) ─────────────

def test_ramo_senza_dizionario_non_azzera_id():
    # A differenza del ramo dizionario (che traduce il nome → azzera ID stantii), qui il nome
    # NON cambia identità: gli ID forniti dalle regole-colonna restano.
    defn = _fixed_parser("Milan v Inter", "v", extra_rules=[
        FieldRule(target="EventId", fixed_value="111"),
        FieldRule(target="MarketId", fixed_value="1.222"),
        FieldRule(target="SelectionId", fixed_value="333"),
    ])
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)
    assert res.row["EventName"] == "Milan - Inter"
    assert (res.row["EventId"], res.row["MarketId"], res.row["SelectionId"]) == ("111", "1.222", "333")


# ── unit diretti su split_event: il param spaced_only è opt-in, il default è INVARIATO ───────

def test_split_event_default_ha_ancora_fallback_compatto():
    # Comportamento storico INVARIATO (ramo dizionario): il fallback compatto taglia sul primo "-".
    assert name_mapping_store.split_event("Al-Kholood Club v Al-Hilal", "-") == (
        "Al", "Kholood Club v Al-Hilal")
    assert name_mapping_store.split_event("Marseille/Lyon", "/") == ("Marseille", "Lyon")


def test_split_event_spaced_only_niente_fallback_compatto():
    # spaced_only=True: nessun fallback compatto → None invece di tagliare dentro il nome.
    assert name_mapping_store.split_event("Al-Kholood Club v Al-Hilal", "-", spaced_only=True) is None
    assert name_mapping_store.split_event("Marseille/Lyon", "/", spaced_only=True) is None
    # forma spaziata: risolve comunque, preservando i trattini interni
    assert name_mapping_store.split_event("Al-Kholood Club - Al-Hilal", "-", spaced_only=True) == (
        "Al-Kholood Club", "Al-Hilal")


def test_split_event_spaced_only_non_cambia_gli_alfabetici():
    # "v"/"vs" già oggi hanno solo la forma spaziata: spaced_only non cambia nulla.
    assert name_mapping_store.split_event("Milan v Inter", "v", spaced_only=True) == ("Milan", "Inter")
    assert name_mapping_store.split_event("Milan vs Inter", "vs", spaced_only=True) == ("Milan", "Inter")


# ── INVARIANZA del ramo dizionario: con profili attivi il comportamento resta quello di prima ─

def test_ramo_dizionario_invariato_traduce_e_azzera_id():
    # Con un profilo nomi attivo, il ramo dizionario traduce (compact fallback incluso via
    # split_event default) e azzera gli ID stantii — comportamento #38-invariato.
    profiles = [[{"provider": "Juve", "betfair": "Juventus", "entity_type": "team"},
                 {"provider": "Roma", "betfair": "AS Roma", "entity_type": "team"}]]
    defn = CustomParserDef(
        name="D", mode="NAME_ONLY", name_mapping_profiles=["Serie A"], team_separator="v",
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Juve v Roma", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="EventId", fixed_value="999"),
        ])
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False,
                                   name_mapping_profiles=profiles)
    assert res.row["EventName"] == "Juventus - AS Roma"      # tradotto
    assert res.row["EventId"] == ""                          # ID stantio azzerato (ramo dizionario)


# ── parità preview ↔ runtime + avviso nel verdetto ───────────────────────────────────────────

def _builder(event, sep):
    b = ParserBuilder(_fixed_parser(event, sep))
    return b


def test_preview_riformatta_come_runtime():
    b = _builder("Milan v Inter", "v")
    rows = b.preview_rows("msg", provider="TG", require_price=False)
    runtime = pipe.build_validated_row(b.to_def(), "msg", provider="TG", require_price=False)
    assert rows[0].row["EventName"] == "Milan - Inter" == runtime.row["EventName"]
    assert rows[0].warnings == []


def test_preview_avviso_su_split_fallito_nel_verdetto_e_previewrow():
    b = _builder("Marseille/Lyon", "/")
    res = b.test_message("msg", provider="TG", require_price=False)
    rows = b.preview_rows("msg", provider="TG", require_price=False)
    assert res.warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]
    assert rows[0].warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]
    verdict = ParserBuilder.test_verdict(
        b.errors(), rows, diag_placeable=res.placeable, diag_status=res.status,
        res_row=res.row, res_missing_required=res.missing_required, res_detail=res.detail,
        res_warnings=res.warnings)
    assert pipe.WARN_TEAM_SEPARATOR_NOT_FOUND in verdict
    assert "⚠" in verdict


def test_verdict_nessun_avviso_quando_split_ok():
    b = _builder("Milan v Inter", "v")
    res = b.test_message("msg", provider="TG", require_price=False)
    rows = b.preview_rows("msg", provider="TG", require_price=False)
    verdict = ParserBuilder.test_verdict(
        b.errors(), rows, diag_placeable=res.placeable, diag_status=res.status,
        res_row=res.row, res_missing_required=res.missing_required, res_detail=res.detail,
        res_warnings=res.warnings)
    assert "⚠" not in verdict


# ── propagazione multi-riga: EventName base riformattato + avviso una sola volta ─────────────

def test_multiriga_propaga_eventname_riformattato_e_avviso():
    # MultiSelection: 2 selezioni fisse. L'EventName base riformattato deve comparire su TUTTE le
    # righe; l'avviso (se lo split fallisse) è a livello messaggio → una sola volta su out[0].
    defn = CustomParserDef(
        name="M", mode="NAME_ONLY", team_separator="v",
        multi_selection_enabled=True,
        multi_selections=[
            cp.MultiRowRule(enabled=True, selection_name="Casa"),
            cp.MultiRowRule(enabled=True, selection_name="Ospite"),
        ],
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Milan v Inter", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
        ])
    results = pipe.build_validated_rows(defn, "msg", provider="TG", require_price=False)
    assert len(results) == 2
    assert all(r.row["EventName"] == "Milan - Inter" for r in results)
    assert all(r.warnings == [] for r in results)


def test_multiriga_avviso_una_sola_volta_su_split_fallito():
    defn = CustomParserDef(
        name="M", mode="NAME_ONLY", team_separator="/",
        multi_selection_enabled=True,
        multi_selections=[
            cp.MultiRowRule(enabled=True, selection_name="Casa"),
            cp.MultiRowRule(enabled=True, selection_name="Ospite"),
        ],
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Marseille/Lyon", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
        ])
    results = pipe.build_validated_rows(defn, "msg", provider="TG", require_price=False)
    assert len(results) == 2
    assert all(r.row["EventName"] == "Marseille/Lyon" for r in results)   # verbatim
    # avviso una sola volta (su out[0]), non duplicato per riga
    all_warns = [w for r in results for w in r.warnings]
    assert all_warns == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]


# ── router live: RouteResult.warnings popolato/vuoto (parità col log) ─────────────────────────

def _router_parser(event, sep, name="NoDict"):
    # EventName ESTRATTO dal messaggio (attiva il content gate `matches_message` del router);
    # gli altri campi fissi (SelectionName estratto darebbe falsi negativi sull'ultima riga
    # senza newline finale). Il separatore riformatta l'EventName estratto.
    return CustomParserDef(
        name=name, mode="NAME_ONLY", team_separator=sep,
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="BetType", fixed_value="PUNTA"),
        ])


def _cfg(name):
    return {"provider": "TG", "active_parser": name, "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "require_price": False}


def test_router_warning_su_split_fallito(tmp_path):
    cp.save_parser(_router_parser("Marseille/Lyon", "/", name="R1"), str(tmp_path))
    msg = "Match: Marseille/Lyon\nSel: Pareggio"
    res = signal_router.resolve_row(msg, _cfg("R1"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.all_rows()[0]["EventName"] == "Marseille/Lyon"     # verbatim
    assert res.warnings == [pipe.WARN_TEAM_SEPARATOR_NOT_FOUND]


def test_router_nessun_warning_quando_split_ok(tmp_path):
    cp.save_parser(_router_parser("Milan v Inter", "v", name="R2"), str(tmp_path))
    msg = "Match: Milan v Inter\nSel: Pareggio"
    res = signal_router.resolve_row(msg, _cfg("R2"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.all_rows()[0]["EventName"] == "Milan - Inter"      # riformattato
    assert res.warnings == []
