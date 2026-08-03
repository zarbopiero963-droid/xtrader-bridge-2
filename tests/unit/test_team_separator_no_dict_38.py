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
    # #182 PR S — IL COMPORTAMENTO ORA CAMBIA, ed è il cuore di questa PR.
    # Fino alla PR A questo caso produceva una riga col nome VERBATIM più un avviso; la PR A
    # aveva reso l'avviso azionabile lasciando il comportamento intatto, con una guardia che
    # diceva «è la PR S a introdurre il blocco». Eccola: nessuna riga.
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.placeable is False, "una riga con separatore non trovato NON è piazzabile"
    # Il nome resta comunque verbatim nella riga di diagnostica — non si inventa uno split che
    # avrebbe tagliato dentro «Al-Kholood» (mai "Al" / "Kholood Club v Al-Hilal").
    assert res.row["EventName"] == "Al-Kholood Club v Al-Hilal"
    # …e lo scarto DICE COSA CORREGGERE: il `detail` porta il separatore che il messaggio sembra
    # usare. Uno scarto muto sarebbe peggio dell'avviso che sostituisce.
    assert res.detail and res.detail.startswith(pipe.WARN_TEAM_SEPARATOR_NOT_FOUND)
    assert "«v»" in res.detail, res.detail
    assert "Separatore squadre" in res.detail


def test_slash_compatto_non_spezza_senza_forma_spaziata():
    # "Marseille/Lyon" con sep "/": nessuna forma spaziata → verbatim + avviso (no split compatto).
    res = _event_of(_fixed_parser("Marseille/Lyon", "/"))
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND      # #182 PR S: bloccata
    assert res.row["EventName"] == "Marseille/Lyon"         # nessuno split compatto inventato


def test_separatore_assente_nel_nome_BLOCCA():
    """#182 PR S: separatore impostato e assente dal nome → nessuna riga.

    Prima: riga scritta con «Milan Inter» verbatim. Il parser dichiarava di aspettarsi « v » e
    il messaggio non ce l'ha: non si è saputo interpretare il formato, quindi non si scrive."""
    res = _event_of(_fixed_parser("Milan Inter", "v"))     # nessun " v " nel nome
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.placeable is False
    assert res.row["EventName"] == "Milan Inter"


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
    # #182 PR S: l'anteprima deve mostrare lo SCARTO, non più un avviso su una riga scritta —
    # ed è il requisito «lo scarto non deve mai essere silenzioso». Se qui passasse inosservato,
    # l'utente vedrebbe «Pronto» per un messaggio che il runtime non scriverà.
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.placeable is False
    verdict = ParserBuilder.test_verdict(
        b.errors(), rows, diag_placeable=res.placeable, diag_status=res.status,
        res_row=res.row, res_missing_required=res.missing_required, res_detail=res.detail,
        res_warnings=res.warnings)
    assert "⛔" in verdict, f"lo scarto non è visibile nel verdetto: {verdict}"
    assert pipe.TEAM_SEPARATOR_NOT_FOUND in verdict or "eparatore" in verdict, verdict


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
    # #182 PR S: la BASE è bloccata, quindi la generazione multi non parte proprio — nessuna
    # delle N righe viene scritta. È la conseguenza corretta: se non si è saputo interpretare
    # l'evento, moltiplicarlo per due selezioni produrrebbe DUE scommesse sbagliate invece di una.
    assert all(r.status == pipe.TEAM_SEPARATOR_NOT_FOUND for r in results), \
        [r.status for r in results]
    assert not any(r.placeable for r in results)


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
    # #182 PR S: è QUI che si vede il cambiamento che conta — il router è il percorso live.
    # Prima `placeable is True` e la riga finiva nel CSV col nome verbatim; ora nessuna riga.
    assert res.placeable is False, "il router piazzerebbe ancora un evento non interpretato"
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND


def test_router_nessun_warning_quando_split_ok(tmp_path):
    cp.save_parser(_router_parser("Milan v Inter", "v", name="R2"), str(tmp_path))
    msg = "Match: Milan v Inter\nSel: Pareggio"
    res = signal_router.resolve_row(msg, _cfg("R2"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.all_rows()[0]["EventName"] == "Milan - Inter"      # riformattato
    assert res.warnings == []


# ── retro-compat blindata: il DEFAULT della dataclass è "" (non "v") → verbatim ──────────────

def test_default_dataclass_team_separator_vuoto_nessuna_riformattazione():
    # Refuta il timore reviewer «default v»: costruito SENZA specificare team_separator, il
    # default è "" → il ramo #38 NON scatta e l'EventName resta verbatim (parser legacy salvi).
    defn = CustomParserDef(
        name="Legacy", mode="NAME_ONLY",
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Milan v Inter", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="BetType", fixed_value="PUNTA"),
        ])
    assert defn.team_separator == ""     # default esplicito, non "v"
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Milan v Inter"   # verbatim, feature NON attivata
    assert res.warnings == []


def test_json_legacy_senza_campo_separatore_resta_verbatim():
    # Un JSON parser salvato PRIMA del campo (from_dict senza team_separator) → "" → verbatim.
    d = cp.CustomParserDef.from_dict({
        "name": "OldJson", "mode": "NAME_ONLY",
        "rules": [
            {"target": "Provider", "fixed_value": "TG"},
            {"target": "EventName", "fixed_value": "Milan v Inter", "required": True},
            {"target": "MarketType", "fixed_value": "MATCH_ODDS", "required": True},
            {"target": "SelectionName", "fixed_value": "Pareggio", "required": True},
            {"target": "BetType", "fixed_value": "PUNTA"},
        ]})
    assert d.team_separator == ""
    res = pipe.build_validated_row(d, "msg", provider="TG", require_price=False)
    assert res.row["EventName"] == "Milan v Inter"
    assert res.warnings == []


# ── consistenza avvisi (finding CodeRabbit/Fable): verdetto NO_CONTENT_MATCH + path non-fired ─

def test_verdict_no_content_match_include_avviso():
    # Verdetto NO_CONTENT_MATCH (multi-riga con almeno una riga piazzabile ma content-gate KO):
    # l'avviso separatore deve comparire comunque accanto al verdetto (coerenza con gli altri rami).
    from xtrader_bridge.parser_builder import PreviewRow
    rows = [PreviewRow(index=0, kind="market", placeable=True, status=validator.VALID,
                       warnings=[pipe.WARN_TEAM_SEPARATOR_NOT_FOUND])]
    verdict = ParserBuilder.test_verdict(
        [], rows, diag_placeable=True, diag_status=validator.VALID,
        res_row={}, res_missing_required=[], res_detail=None, content_ok=False)
    assert "NO_CONTENT_MATCH" in verdict
    assert pipe.WARN_TEAM_SEPARATOR_NOT_FOUND in verdict


def test_separatore_precede_la_mappatura_mercati():
    """#182 PR S — conseguenza d'ORDINE, decisa e non subita.

    Prima: split fallito produceva un avviso, poi la mappatura mercati falliva e l'esito era
    `MARKET_MAPPING_MISSING` con l'avviso separatore accodato. Ora il blocco separatore ritorna
    PRIMA che i mercati vengano valutati, quindi l'esito è `TEAM_SEPARATOR_NOT_FOUND`.

    È la scelta giusta: si riporta la PRIMA causa in ordine di pipeline, quella che l'utente deve
    correggere per prima. Segnalare il mercato mentre l'evento non è stato interpretato manderebbe
    a sistemare la cosa sbagliata. In entrambi i casi **nessuna riga viene scritta**: la direzione
    fail-closed è identica, cambia solo quale causa viene nominata."""
    defn = CustomParserDef(
        name="MM", mode="NAME_ONLY", team_separator="/",
        market_mapping_profiles=["M"],
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Marseille/Lyon", required=True),
        ])
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False,
                                   market_mapping_profiles=[[]])   # profilo vuoto → nessun match
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND, (
        "il separatore va riportato PRIMA del mercato: è la causa da correggere per prima")
    assert res.placeable is False          # fail-closed identico a prima: nessuna riga
    assert res.row["EventName"] == "Marseille/Lyon"   # verbatim, nessuno split inventato


def test_router_scarto_separatore_dice_il_motivo_giusto(tmp_path):
    """#182 PR S — lo scarto deve nominare il SEPARATORE, non un difetto a valle.

    Prima: il gate parser passava, il separatore falliva (avviso), e la riga veniva poi scartata
    per un difetto successivo (BetType mancante) — l'avviso separatore viaggiava accodato allo
    scarto altrui. Ora il separatore è **esso stesso** il motivo dello scarto, e il router lo
    riporta come tale.

    Perché conta: con lo scarto attribuito a BetType, l'utente sarebbe andato a sistemare il
    BetType e il messaggio avrebbe continuato a non passare. Nota: uno scarto per campo MANCANTE
    si ferma al gate parser PRIMA del ramo separatore (`NOT_READY`) — quello resta invariato."""
    defn = CustomParserDef(
        name="RD", mode="NAME_ONLY", team_separator="/",
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        ])
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "RD", "chat_id": "42",
           "recognition_mode": "NAME_ONLY", "require_price": True}
    # Price valido (gate passa) ma manca BetType → riga non piazzabile DOPO il ramo separatore.
    msg = "Match: Marseille/Lyon\nQuota: 999\n"
    res = signal_router.resolve_row(msg, cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND, (
        "lo scarto deve dire «separatore», non un difetto a valle che l'utente sistemerebbe invano")
