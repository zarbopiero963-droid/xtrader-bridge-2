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
    # PR-P10: la riga ripulita include ora `sport` e `entity_type` (""=agnostici,
    # retro-compatibili con le config salvate prima di questi campi).
    assert entries == [{"country": "", "betfair": "Inter", "provider": "Internazionale",
                        "sport": "", "entity_type": ""}]


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
        {"country": "", "betfair": "Real", "provider": "Real Madrid",
         "sport": "", "entity_type": ""}]


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


def test_profilo_con_whitespace_trovato_e_cancellabile():
    # audit L1: un profilo salvato con spazi attorno al nome (config legacy/editata a mano)
    # NON deve "sparire": lookup/CRUD normalizzano il nome come fa market_mapping_store.
    cfg = {"name_mappings": {"  Premier  ": [{"betfair": "Liverpool", "provider": "Liverpool FC"}]}}
    assert nm.profile_names(cfg) == ["Premier"]                  # mostrato ripulito
    # get_entries lo ritrova sia col nome ripulito sia con spazi.
    assert nm.get_entries(cfg, "Premier")[0]["betfair"] == "Liverpool"
    assert nm.get_entries(cfg, " Premier ")[0]["betfair"] == "Liverpool"
    # delete_profile lo rimuove passando il nome ripulito (prima restava orfano, non cancellabile).
    assert nm.profile_names(nm.delete_profile(cfg, "Premier")) == []
    # set_entries su un nome equivalente migra la chiave legacy: niente doppione.
    updated = nm.set_entries(cfg, "Premier", [{"betfair": "Everton", "provider": "EFC"}])
    assert nm.profile_names(updated) == ["Premier"]
    assert nm.get_entries(updated, "Premier")[0]["betfair"] == "Everton"


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


# ── PR-P10: scoping per sport (multi-sport) ─────────────────────────────────────

def test_get_entries_normalizza_sport():
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter", "provider": "Internazionale", "sport": "calcio"},   # case-insens.
        {"betfair": "Sinner", "provider": "J. Sinner", "sport": "Cricket"},       # ignoto → ""
        {"betfair": "Roma", "provider": "AS Roma"},                               # assente → ""
    ]}}
    entries = nm.get_entries(cfg, "P")
    assert entries[0]["sport"] == "Calcio"     # canonicalizzato
    assert entries[1]["sport"] == ""           # sport ignoto → agnostico (no nuovo failure mode)
    assert entries[2]["sport"] == ""           # assente → agnostico


def _sport_cfg():
    return {"name_mappings": {"Multi": [
        {"betfair": "Inter", "provider": "Internazionale", "sport": "Calcio"},
        {"betfair": "Sinner", "provider": "Sinner T", "sport": "Tennis"},
        {"betfair": "Milan", "provider": "ACM"},                       # agnostico
    ]}}


def test_resolve_team_scoping_per_sport():
    profs = nm.entries_for_profiles(_sport_cfg(), ["Multi"])
    # sport=Calcio: trova la voce Calcio e l'agnostica, NON la voce Tennis.
    assert nm.resolve_team("Internazionale", profs, sport="Calcio") == "Inter"
    assert nm.resolve_team("ACM", profs, sport="Calcio") == "Milan"           # agnostica vale
    assert nm.resolve_team("Sinner T", profs, sport="Calcio") is None         # altro sport → saltata
    # sport=Tennis: trova la voce Tennis e l'agnostica, NON la voce Calcio.
    assert nm.resolve_team("Sinner T", profs, sport="Tennis") == "Sinner"
    assert nm.resolve_team("Internazionale", profs, sport="Tennis") is None


def test_resolve_team_senza_sport_nessun_filtro():
    # sport assente/None/"" → comportamento legacy: tutte le righe considerate.
    profs = nm.entries_for_profiles(_sport_cfg(), ["Multi"])
    assert nm.resolve_team("Sinner T", profs) == "Sinner"
    assert nm.resolve_team("Internazionale", profs, sport="") == "Inter"
    assert nm.resolve_team("Internazionale", profs, sport=None) == "Inter"


def test_resolve_event_name_scoping_per_sport():
    cfg = {"name_mappings": {"M": [
        {"betfair": "Inter", "provider": "Internazionale", "sport": "Calcio"},
        {"betfair": "Milan", "provider": "ACM", "sport": "Calcio"},
        {"betfair": "Inter", "provider": "Internazionale", "sport": "Basket"},   # altro sport
    ]}}
    profs = nm.entries_for_profiles(cfg, ["M"])
    assert nm.resolve_event_name("Internazionale v ACM", "v", profs, sport="Calcio") == "Inter - Milan"
    # con sport=Tennis nessuna voce combacia → fail-closed (None).
    assert nm.resolve_event_name("Internazionale v ACM", "v", profs, sport="Tennis") is None


def _sport_mapping_parser(sport):
    defn = _mapping_parser(profiles=("Multi",), separator="v")
    defn.sport = sport
    return defn


def test_pipeline_usa_lo_sport_del_parser_per_la_mappatura():
    cfg = {"name_mappings": {"Multi": [
        {"betfair": "Liverpool", "provider": "Liverpool FC", "sport": "Calcio"},
        {"betfair": "Leeds", "provider": "Leeds Utd", "sport": "Calcio"},
        {"betfair": "Liverpool", "provider": "Liverpool FC", "sport": "Tennis"},  # rumore altro sport
    ]}}
    profs = nm.entries_for_profiles(cfg, ["Multi"])
    # Parser sport=Calcio → mappa con le voci Calcio.
    res = pipe.build_validated_row(_sport_mapping_parser("Calcio"), _MSG, name_mapping_profiles=profs)
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Liverpool - Leeds"
    # Parser sport=Basket → nessuna voce Basket/agnostica per queste squadre → MAPPING_MISSING.
    res2 = pipe.build_validated_row(_sport_mapping_parser("Basket"), _MSG, name_mapping_profiles=profs)
    assert res2.status == pipe.MAPPING_MISSING


def test_resolve_team_sport_esatto_vince_su_agnostico_precedente():
    # Una riga AGNOSTICA salvata PRIMA non deve scavalcare un override PER-SPORT salvato
    # dopo, con lo stesso alias (la GUI fa solo append) — CodeRabbit. Lo sport esatto vince.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter generico", "provider": "Inter"},                  # agnostica (prima)
        {"betfair": "Inter Calcio", "provider": "Inter", "sport": "Calcio"}, # override Calcio (dopo)
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, sport="Calcio") == "Inter Calcio"   # esatto vince
    assert nm.resolve_team("Inter", profs, sport="Tennis") == "Inter generico" # fallback agnostico
    assert nm.resolve_team("Inter", profs) == "Inter generico"                 # senza sport: ordine (legacy)


def test_resolve_team_fallback_agnostico_se_nessun_match_esatto():
    # Se non c'è una riga per lo sport richiesto, l'agnostica resta valida (fallback).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Milan", "provider": "ACM"},                              # agnostica
        {"betfair": "Sinner", "provider": "Sinner T", "sport": "Tennis"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("ACM", profs, sport="Calcio") == "Milan"           # agnostica usata


def test_resolve_team_canonico_esatto_sport_batte_alias_agnostico():
    # P2 Codex #174: un ALIAS agnostico non deve scavalcare un CANONICO esatto-sport dello
    # stesso nome. Con l'alias globale "Inter"→"Wrong" e la riga Calcio con canonico
    # "Inter", chiedendo sport=Calcio deve vincere il canonico Calcio ("Inter"), non
    # l'alias agnostico. Prima del fix i due passi (tutti-alias, poi tutti-canonici)
    # facevano vincere l'alias agnostico.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Wrong", "provider": "Inter"},                    # agnostica, alias "Inter"
        {"betfair": "Inter", "provider": "", "sport": "Calcio"},      # Calcio, canonico "Inter"
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, sport="Calcio") == "Inter"    # canonico esatto-sport vince
    # Fallback: chiedendo un altro sport (nessuna riga esatta) resta valido l'alias agnostico.
    assert nm.resolve_team("Inter", profs, sport="Tennis") == "Wrong"
    # Senza sport: comportamento legacy (ordine salvato) → l'alias agnostico salvato prima vince.
    assert nm.resolve_team("Inter", profs) == "Wrong"


def test_resolve_team_canonico_esatto_tipo_batte_alias_agnostico():
    # Stessa precedenza sulla dimensione TIPO: un alias agnostico non scavalca un canonico
    # esatto-tipo dello stesso nome quando si filtra per entity_type.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Wrong", "provider": "Inter"},                          # agnostica, alias "Inter"
        {"betfair": "Inter", "provider": "", "entity_type": "team"},        # team, canonico "Inter"
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, entity_type="team") == "Inter"   # canonico esatto-tipo vince
    assert nm.resolve_team("Inter", profs) == "Wrong"                       # senza filtro: legacy


# ── entity_type: tassonomia unificata (issue #178 §2 / PR-P10) ────────────────

def test_normalize_entity_type():
    assert nm.normalize_entity_type("Team") == "team"          # case-insensitive
    assert nm.normalize_entity_type(" PLAYER ") == "player"    # strip
    assert nm.normalize_entity_type("competition") == "competition"
    assert nm.normalize_entity_type("") == ""                  # vuoto → agnostico
    assert nm.normalize_entity_type("squadra") == ""           # ignoto → agnostico
    assert nm.normalize_entity_type(None) == ""
    # tutti i tipi richiesti dall'issue sono ammessi
    for t in ("participant", "team", "player", "competition", "market", "selection"):
        assert nm.normalize_entity_type(t) == t


def test_clean_entry_normalizza_entity_type():
    cfg = {"name_mappings": {"P": [
        {"betfair": "Juventus", "provider": "Juve", "entity_type": "Team"},
        {"betfair": "Jannik Sinner", "provider": "Sinner", "entity_type": "PLAYER"},
        {"betfair": "Serie A", "provider": "SerieA", "entity_type": "boh"},   # ignoto → ""
    ]}}
    ents = nm.get_entries(cfg, "P")
    assert ents[0]["entity_type"] == "team"
    assert ents[1]["entity_type"] == "player"
    assert ents[2]["entity_type"] == ""


def test_entity_type_competition_e_player_rappresentabili():
    # I tipi che PRIMA mancavano (player, competition) ora si esprimono e si risolvono.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Jannik Sinner", "provider": "Sinner", "entity_type": "player"},
        {"betfair": "Serie A", "provider": "SerieA", "entity_type": "competition"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Sinner", profs, entity_type="player") == "Jannik Sinner"
    assert nm.resolve_team("SerieA", profs, entity_type="competition") == "Serie A"


def test_resolve_team_scoping_per_entity_type():
    # Stesso alias "Inter" taggato come team e come competition: filtrando per tipo si
    # prende SOLO quello giusto (un alias di competition non traduce un nome squadra).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter FC", "provider": "Inter", "entity_type": "team"},
        {"betfair": "Inter Cup", "provider": "Inter", "entity_type": "competition"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, entity_type="team") == "Inter FC"
    assert nm.resolve_team("Inter", profs, entity_type="competition") == "Inter Cup"


def test_resolve_team_entity_agnostica_sempre_eleggibile():
    # Una riga senza entity_type (agnostica) si applica anche quando si filtra per tipo.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Milan", "provider": "ACM"},                          # agnostica
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("ACM", profs, entity_type="team") == "Milan"


def test_resolve_team_entity_altro_tipo_saltato():
    # Una riga taggata "competition" NON traduce se si chiede "team" e non c'è agnostica.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Liga", "provider": "LaLiga", "entity_type": "competition"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("LaLiga", profs, entity_type="team") is None
    assert nm.resolve_team("LaLiga", profs) == "Liga"          # senza filtro: applicata


def test_resolve_team_senza_entity_nessun_filtro_legacy():
    # entity_type assente/None → comportamento legacy: si considerano tutte le righe.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter FC", "provider": "Inter", "entity_type": "team"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs) == "Inter FC"


def test_entity_type_e_sport_combinati():
    # I due filtri sono additivi: serve match di sport (o agnostico) E di tipo (o agnostico).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter FC", "provider": "Inter", "sport": "Calcio", "entity_type": "team"},
        {"betfair": "Inter Tennis", "provider": "Inter", "sport": "Tennis", "entity_type": "team"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, sport="Calcio", entity_type="team") == "Inter FC"
    assert nm.resolve_team("Inter", profs, sport="Tennis", entity_type="team") == "Inter Tennis"


# ── Codex review su PR #182: priorità tipo esatto + esclusione non-participant ──

def test_resolve_team_tipo_esatto_vince_su_agnostico_precedente():
    # P2 Codex: una riga agnostica legacy salvata PRIMA non deve scavalcare un override
    # tipizzato per lo stesso alias (la GUI fa solo append). Con entity_type="team" vince
    # l'override tipizzato; senza filtro tipo resta l'ordine salvato (legacy invariato).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter generico", "provider": "Inter"},                   # agnostica (prima)
        {"betfair": "Inter FC", "provider": "Inter", "entity_type": "team"},  # override tipizzato (dopo)
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, entity_type="team") == "Inter FC"
    assert nm.resolve_team("Inter", profs) == "Inter generico"


def test_resolve_team_entity_type_accetta_insieme_di_tipi():
    # entity_type può essere un INSIEME di tipi ammessi (es. PARTICIPANT_ENTITY_TYPES).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Giocatore A", "provider": "x", "entity_type": "player"},
        {"betfair": "Mercato B", "provider": "y", "entity_type": "market"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("x", profs, entity_type=nm.PARTICIPANT_ENTITY_TYPES) == "Giocatore A"
    assert nm.resolve_team("y", profs, entity_type=nm.PARTICIPANT_ENTITY_TYPES) is None  # market escluso


def test_resolve_event_name_esclude_tipi_non_participant():
    # P1 Codex: una riga "competition" con alias che collide NON traduce un partecipante
    # quando si passa l'insieme participant/team/player.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Coppa Reds", "provider": "Reds", "entity_type": "competition"},
        {"betfair": "Leeds", "provider": "Leeds Utd", "entity_type": "team"},
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_event_name("Reds v Leeds Utd", "v", profs,
                                 entity_type=nm.PARTICIPANT_ENTITY_TYPES) is None
    # con righe participant/team/player (e agnostiche) la traduzione avviene
    cfg2 = {"name_mappings": {"P": [
        {"betfair": "Liverpool", "provider": "Reds", "entity_type": "team"},
        {"betfair": "Leeds", "provider": "Leeds Utd", "entity_type": "player"},
    ]}}
    profs2 = nm.entries_for_profiles(cfg2, ["P"])
    assert nm.resolve_event_name("Reds v Leeds Utd", "v", profs2,
                                 entity_type=nm.PARTICIPANT_ENTITY_TYPES) == "Liverpool - Leeds"


def test_pipeline_eventname_ignora_righe_non_participant():
    # P1 Codex end-to-end: nel flusso live una riga competition/market/selection con alias
    # che collide NON traduce un partecipante → fail-closed (nessun EventName sbagliato).
    cfg = {"name_mappings": {"P": [
        {"betfair": "Coppa Reds", "provider": "Reds", "entity_type": "competition"},
        {"betfair": "Leeds", "provider": "Leeds Utd", "entity_type": "team"},
    ]}}
    profiles = nm.entries_for_profiles(cfg, ["P"])
    msg = "Match: Reds v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"
    res = pipe.build_validated_row(_mapping_parser(profiles=("P",)), msg,
                                   name_mapping_profiles=profiles)
    assert res.status == pipe.MAPPING_MISSING
    assert res.placeable is False


def test_pipeline_eventname_usa_team_e_participant():
    # Controprova: righe team/participant traducono regolarmente nel flusso live.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Liverpool", "provider": "Reds", "entity_type": "team"},
        {"betfair": "Leeds", "provider": "Leeds Utd", "entity_type": "participant"},
    ]}}
    profiles = nm.entries_for_profiles(cfg, ["P"])
    msg = "Match: Reds v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"
    res = pipe.build_validated_row(_mapping_parser(profiles=("P",)), msg,
                                   name_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Liverpool - Leeds"


def test_pipeline_eventname_agnostiche_restano_valide():
    # Retro-compatibilità: righe SENZA entity_type (agnostiche) traducono ancora l'EventName.
    profiles = nm.entries_for_profiles(_cfg(), ["Premier"])
    res = pipe.build_validated_row(_mapping_parser(), _MSG, name_mapping_profiles=profiles)
    assert res.status == validator.VALID
    assert res.row["EventName"] == "Liverpool - Leeds"


def test_resolve_team_tipo_esatto_vince_su_riga_sport_legacy_senza_tipo():
    # Codex (2° giro): una riga legacy sport-specifica MA senza tipo salvata PRIMA non deve
    # scavalcare un override tipizzato (sport-agnostico) salvato dopo, quando si chiede
    # sport+participante. Il tipo è la dimensione PRIMARIA del ranking.
    cfg = {"name_mappings": {"P": [
        {"betfair": "Inter legacy", "provider": "Inter", "sport": "Calcio"},   # sport-specifica, senza tipo
        {"betfair": "Inter FC", "provider": "Inter", "entity_type": "team"},   # override tipizzato (agnostico di sport)
    ]}}
    profs = nm.entries_for_profiles(cfg, ["P"])
    assert nm.resolve_team("Inter", profs, sport="Calcio",
                           entity_type=nm.PARTICIPANT_ENTITY_TYPES) == "Inter FC"
    # Senza filtro tipo: lo scoping per sport resta legacy (vince la riga sport-specifica salvata prima).
    assert nm.resolve_team("Inter", profs, sport="Calcio") == "Inter legacy"
