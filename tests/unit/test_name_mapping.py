"""Test del dizionario di mappatura nomi squadra (name_mapping_store) e della sua
integrazione nel pipeline del Parser Personalizzato.

Esercitano funzioni reali: CRUD puri sui profili, risoluzione nomi/EventName
(separatori liberi, multi-profilo, fail-closed) e la traduzione dell'EventName in
`custom_pipeline.build_validated_row` (status MAPPING_MISSING incluso).
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import name_mapping_store as nm
from xtrader_bridge import validator


# ── CRUD puri sui profili ────────────────────────────────────────────────────

def _cfg():
    return {"name_mappings": {"Premier": [
        {"country": "Inghilterra", "betfair": "Liverpool", "provider": "Liverpool FC"},
        {"country": "Inghilterra", "betfair": "Leeds", "provider": "Leeds Utd"},
    ]}}


def test_profile_names_ordinati_case_insensitive():
    cfg = {"name_mappings": {"Serie A": [], "premier": [], "Bundes": []}}
    assert nm.profile_names(cfg) == ["Bundes", "premier", "Serie A"]


def test_get_entries_pulisce_righe_vuote():
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter", "provider": "Internazionale"},
        {"betfair": "", "provider": ""},          # riga vuota → scartata
        "non-un-dict",                              # rumore → scartato
    ]}}
    entries = nm.get_entries(cfg, "P")
    assert entries == [{"country": "", "betfair": "Inter", "provider": "Internazionale"}]


def test_profili_assenti_o_malformati_non_esplodono():
    assert nm.profile_names({}) == []
    assert nm.get_entries({}, "x") == []
    assert nm.profile_names({"name_mappings": "rotto"}) == []
    assert nm.get_entries({"name_mappings": {"x": "rotto"}}, "x") == []


def test_set_entries_immutabile_e_pulisce():
    cfg = {}
    out = nm.set_entries(cfg, "Liga", [
        {"betfair": "Real", "provider": "Real Madrid"},
        {"betfair": "", "provider": ""},   # scartata
    ])
    assert cfg == {}                                    # originale invariato
    assert nm.get_entries(out, "Liga") == [
        {"country": "", "betfair": "Real", "provider": "Real Madrid"}]


def test_add_profile_non_sovrascrive_esistente():
    cfg = _cfg()
    out = nm.add_profile(cfg, "Premier")
    assert nm.get_entries(out, "Premier") == nm.get_entries(cfg, "Premier")  # righe intatte
    out2 = nm.add_profile(cfg, "Nuovo")
    assert "Nuovo" in nm.profile_names(out2) and nm.get_entries(out2, "Nuovo") == []
    assert cfg.get("name_mappings", {}).get("Nuovo") is None  # immutabile


def test_delete_e_rename_profile():
    cfg = _cfg()
    assert "Premier" not in nm.profile_names(nm.delete_profile(cfg, "Premier"))
    renamed = nm.rename_profile(cfg, "Premier", "EPL")
    assert nm.profile_names(renamed) == ["EPL"]
    assert nm.get_entries(renamed, "EPL") == nm.get_entries(cfg, "Premier")
    # Non sovrascrive un nome già esistente.
    busy = {"name_mappings": {"A": [{"betfair": "X", "provider": "x"}], "B": []}}
    assert nm.rename_profile(busy, "A", "B") == busy


# ── resolve_team ─────────────────────────────────────────────────────────────

def test_resolve_team_alias_e_case_insensitive():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    assert nm.resolve_team("liverpool fc", profiles) == "Liverpool"   # alias, case-insensitive
    assert nm.resolve_team("  Leeds   Utd ", profiles) == "Leeds"     # spazi collassati


def test_resolve_team_match_canonico_se_provider_manda_il_nome_betfair():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    assert nm.resolve_team("Liverpool", profiles) == "Liverpool"       # nome canonico diretto


def test_resolve_team_ignoto_ritorna_none():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    assert nm.resolve_team("Arsenal", profiles) is None
    assert nm.resolve_team("", profiles) is None


def test_resolve_team_multi_profilo_prima_corrispondenza_vince():
    cfg = {"name_mappings": {
        "A": [{"betfair": "Milan", "provider": "ACM"}],
        "B": [{"betfair": "AC Milan", "provider": "ACM"}],
    }}
    # Ordine [A, B] → vince A; ordine [B, A] → vince B (deterministico).
    assert nm.resolve_team("ACM", nm.entries_for_profiles(cfg, ["A", "B"])) == "Milan"
    assert nm.resolve_team("ACM", nm.entries_for_profiles(cfg, ["B", "A"])) == "AC Milan"


def test_resolve_team_canonico_del_primo_profilo_batte_alias_del_secondo():
    # Codex: "il primo profilo vince" → alias+canonico del profilo A si esauriscono
    # PRIMA di passare a B. A ha il canonico "Rangers"; B ha l'alias "Rangers"→QPR.
    cfg = {"name_mappings": {
        "A": [{"betfair": "Rangers", "provider": ""}],
        "B": [{"betfair": "Queens Park Rangers", "provider": "Rangers"}],
    }}
    assert nm.resolve_team("Rangers", nm.entries_for_profiles(cfg, ["A", "B"])) == "Rangers"
    # Ordine inverso: nessun match in B (canonico "Queens Park Rangers", alias "Rangers"),
    # quindi vince l'alias di B che ora è il primo profilo.
    assert nm.resolve_team(
        "Rangers", nm.entries_for_profiles(cfg, ["B", "A"])) == "Queens Park Rangers"


# ── split_event / resolve_event_name ────────────────────────────────────────

def test_split_event_separatori_liberi():
    assert nm.split_event("Liverpool v Leeds", "v") == ("Liverpool", "Leeds")
    assert nm.split_event("Liverpool vs Leeds", "vs") == ("Liverpool", "Leeds")
    assert nm.split_event("Liverpool - Leeds", "-") == ("Liverpool", "Leeds")
    assert nm.split_event("Liverpool/Leeds", "/") == ("Liverpool", "Leeds")


def test_split_event_separatore_alfabetico_non_spezza_nome_interno():
    # "Liverpool" contiene 'v': il separatore "v" richiede spazi attorno, niente falso split.
    assert nm.split_event("Liverpool", "v") is None
    assert nm.split_event("Aston Villa v Everton", "v") == ("Aston Villa", "Everton")


def test_split_event_non_spezza_punteggiatura_interna_al_nome():
    # Codex: "Paris Saint-Germain - Lyon" col separatore "-" deve dividere sul " - "
    # con spazi, non sul trattino interno a "Saint-Germain".
    assert nm.split_event("Paris Saint-Germain - Lyon", "-") == ("Paris Saint-Germain", "Lyon")
    # Forma compatta (fallback solo per simboli) quando non c'è la forma con spazi.
    assert nm.split_event("Liverpool/Leeds", "/") == ("Liverpool", "Leeds")
    # Con spazi attorno a "/" funziona comunque (match con spazi preferito).
    assert nm.split_event("Inter / Milan", "/") == ("Inter", "Milan")


def test_split_event_casi_non_separabili():
    assert nm.split_event("Solo Una Squadra", "v") is None
    assert nm.split_event("", "v") is None
    assert nm.split_event("A v B", "") is None


def test_resolve_event_name_traduce_e_ricompone():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    # Output nel formato XTrader "Casa - Trasferta" (compose_event_name).
    assert nm.resolve_event_name("Liverpool FC v Leeds Utd", "v", profiles) == "Liverpool - Leeds"


def test_resolve_event_name_fail_closed_se_una_squadra_ignota():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    assert nm.resolve_event_name("Liverpool FC v Arsenal", "v", profiles) is None
    assert nm.resolve_event_name("Solo Liverpool FC", "v", profiles) is None


def test_resolve_event_name_nome_con_trattino_interno():
    # Nome che contiene il separatore "-" internamente: il match con spazi lo preserva.
    cfg = {"name_mappings": {"L1": [
        {"betfair": "Paris Saint-Germain", "provider": "PSG"},
        {"betfair": "Lyon", "provider": "OL"},
    ]}}
    profiles = nm.entries_for_profiles(cfg, ["L1"])
    assert nm.resolve_event_name("PSG - OL", "-", profiles) == "Paris Saint-Germain - Lyon"


# ── Integrazione pipeline (build_validated_row) ──────────────────────────────

def _mapping_parser(profiles=("Premier",), separator="v"):
    return cp.CustomParserDef(
        name="Map", mode="NAME_ONLY",
        name_mapping_profiles=list(profiles), team_separator=separator,
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


_MSG = "Match: Liverpool FC v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"


def test_pipeline_mappa_eventname_quando_profili_forniti():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    res = pipe.build_validated_row(_mapping_parser(), _MSG, name_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.placeable is True
    assert res.row["EventName"] == "Liverpool - Leeds"     # tradotto e ricomposto


def test_pipeline_mapping_missing_se_squadra_ignota():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    msg = "Match: Liverpool FC v Arsenal\nSel: Sì\nQuota: 1,85\nLato: BACK"
    res = pipe.build_validated_row(_mapping_parser(), msg, name_mapping_profiles=profiles)
    assert res.status == pipe.MAPPING_MISSING
    assert res.placeable is False                          # fail-closed: niente riga


def test_pipeline_mapping_missing_se_separatore_non_trovato():
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    msg = "Match: Liverpool FC - Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"  # usa "-" non "v"
    res = pipe.build_validated_row(_mapping_parser(separator="v"), msg, name_mapping_profiles=profiles)
    assert res.status == pipe.MAPPING_MISSING


def test_pipeline_nessuna_mappatura_se_parser_senza_profili():
    # Retro-compatibilità: parser senza profili → EventName invariato.
    parser = _mapping_parser(profiles=())
    res = pipe.build_validated_row(parser, _MSG, name_mapping_profiles=[])
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Liverpool FC v Leeds Utd"   # non tradotto


def test_pipeline_fail_closed_se_mappatura_richiesta_ma_profili_none():
    # Codex: anteprima senza config (profili None) NON deve mostrare "Pronto" per un
    # evento non mappato. Mappatura richiesta → obbligatoria → MAPPING_MISSING.
    res = pipe.build_validated_row(_mapping_parser(), _MSG, name_mapping_profiles=None)
    assert res.status == pipe.MAPPING_MISSING
    assert res.placeable is False


# ── (de)serializzazione dei nuovi campi del parser ───────────────────────────

def test_custom_parser_roundtrip_campi_mappatura():
    defn = _mapping_parser(profiles=("Premier", "Serie A"), separator="vs")
    back = cp.CustomParserDef.from_json(defn.to_json())
    assert back.name_mapping_profiles == ["Premier", "Serie A"]
    assert back.team_separator == "vs"


def test_custom_parser_default_retrocompatibile():
    # File legacy senza i nuovi campi → liste/stringhe vuote (nessuna mappatura).
    back = cp.CustomParserDef.from_dict({"name": "X", "rules": [{"target": "EventName"}]})
    assert back.name_mapping_profiles == []
    assert back.team_separator == ""


def test_rename_mapping_profile_in_files_aggiorna_riferimenti(tmp_path):
    # Codex: rinominare un profilo deve aggiornare i parser che lo referenziano,
    # preservando ordine e senza duplicati; chi non lo usa resta intatto.
    d = str(tmp_path)
    using = _mapping_parser(profiles=("B", "Premier"), separator="v")
    using.name = "Using"
    cp.save_parser(using, d)
    other = _mapping_parser(profiles=("Altro",))
    other.name = "Other"
    cp.save_parser(other, d)

    updated, failed = cp.rename_mapping_profile_in_files("Premier", "EPL", d)
    assert updated == ["Using"]
    assert failed == []
    reloaded = cp.load_parser(cp.parser_path("Using", d))
    assert reloaded.name_mapping_profiles == ["B", "EPL"]          # ordine preservato
    # Parser che non usa il profilo: invariato.
    assert cp.load_parser(cp.parser_path("Other", d)).name_mapping_profiles == ["Altro"]
    # No-op: nuovo nome vuoto / uguale al vecchio.
    assert cp.rename_mapping_profile_in_files("EPL", "EPL", d) == ([], [])
    assert cp.rename_mapping_profile_in_files("EPL", "", d) == ([], [])


def test_rename_mapping_profile_in_files_evita_duplicati(tmp_path):
    # Se il nuovo nome è già presente nel parser, il rename non crea duplicati.
    d = str(tmp_path)
    defn = _mapping_parser(profiles=("A", "B"))
    defn.name = "Dup"
    cp.save_parser(defn, d)
    updated, failed = cp.rename_mapping_profile_in_files("A", "B", d)
    assert updated == ["Dup"] and failed == []
    assert cp.load_parser(cp.parser_path("Dup", d)).name_mapping_profiles == ["B"]


def test_parsers_using_mapping_profile(tmp_path):
    # Elenca i parser salvati che referenziano un profilo (per avvisare prima di
    # eliminarlo): chi lo usa è listato, chi non lo usa no.
    d = str(tmp_path)
    a = _mapping_parser(profiles=("Premier", "Serie A"))
    a.name = "A"
    cp.save_parser(a, d)
    b = _mapping_parser(profiles=("Serie A",))
    b.name = "B"
    cp.save_parser(b, d)
    assert cp.parsers_using_mapping_profile("Premier", d) == ["A"]
    assert sorted(cp.parsers_using_mapping_profile("Serie A", d)) == ["A", "B"]
    assert cp.parsers_using_mapping_profile("Inesistente", d) == []
    assert cp.parsers_using_mapping_profile("", d) == []


def test_diagnose_non_mente_se_mappatura_richiesta_senza_profili():
    # Codex: "Prova messaggio" senza profili risolti deve risultare NON pronta
    # (MAPPING_MISSING su EventName), non un falso "Pronto" col nome grezzo.
    from xtrader_bridge import parser_diagnostics as pd
    diag = pd.diagnose(_mapping_parser(), _MSG)            # name_mapping_profiles=None
    assert diag.placeable is False
    assert diag.status == pipe.MAPPING_MISSING
    event_fd = next(fd for fd in diag.fields if fd.target == "EventName")
    assert event_fd.error == pd.MAPPING_MISSING


def test_parser_builder_preserva_campi_mappatura_nel_roundtrip():
    # Codex: aprire un parser nel builder e ri-salvarlo NON deve azzerare la mappatura.
    from xtrader_bridge.parser_builder import ParserBuilder
    defn = _mapping_parser(profiles=("Premier", "Serie A"), separator="vs")
    out = ParserBuilder(defn).to_def()
    assert out.name_mapping_profiles == ["Premier", "Serie A"]
    assert out.team_separator == "vs"
    # builder vuoto: default sicuri (nessuna mappatura).
    empty = ParserBuilder().to_def()
    assert empty.name_mapping_profiles == [] and empty.team_separator == ""
