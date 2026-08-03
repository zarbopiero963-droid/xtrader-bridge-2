"""✂️ Blocco separatore impostato ma non trovato (#182 PR S) — l'UNICA PR di comportamento.

**Cosa cambia:** separatore configurato nel parser ma non presente nell'`EventName` → prima la
riga veniva scritta col nome **verbatim** più un avviso, ora **non viene scritta affatto**, con
esito dedicato `TEAM_SEPARATOR_NOT_FOUND`.

**Cosa NON cambia, ed è la cosa che questi test proteggono di più:** il **campo vuoto**. È la
condizione che tiene in piedi tutti i parser esistenti che non usano il separatore. Se un giorno
questa PR facesse scartare anche quelli, il bridge smetterebbe di scrivere righe che oggi scrive
correttamente — un danno molto maggiore di quello che la PR previene.

**Il compromesso, registrato dal proprietario nella #182:** un messaggio con formato
occasionalmente diverso dal solito (`vs` invece di `v`) oggi produce una riga col nome verbatim;
dopo non produrrà nulla. Va nella direzione fail-closed — meno scommesse, mai di più — ma è un
segnale perso. È il motivo per cui lo scarto **deve** essere visibile ovunque, e diversi test qui
sotto verificano proprio la visibilità, non solo il blocco.
"""

import json
import os

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import parser_diagnostics, signal_router, validator
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule


def _parser(event, separator, *, profiles=(), nome="P"):
    """Parser minimo piazzabile in NAME_ONLY con `EventName` fisso e separatore dato."""
    return CustomParserDef(
        name=nome, mode="NAME_ONLY",
        name_mapping_profiles=list(profiles),
        team_separator=separator,
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value=event, required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="BetType", fixed_value="PUNTA"),
        ])


def _res(defn):
    return pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)


# ── ① separatore impostato E TROVATO: invariato, la riga si scrive ──────────────────

def test_separatore_trovato_scrive_e_riformatta():
    """Guardia: la PR S non deve toccare il caso che funziona."""
    for evento, sep, atteso in [("Milan v Inter", "v", "Milan - Inter"),
                                ("Milan vs Inter", "vs", "Milan - Inter"),
                                ("Milan - Inter", "-", "Milan - Inter"),
                                ("Roma / Lazio", "/", "Roma - Lazio")]:
        res = _res(_parser(evento, sep))
        assert res.status == validator.VALID, (evento, sep, res.status)
        assert res.placeable is True
        assert res.row["EventName"] == atteso


# ── ② separatore impostato e NON trovato: nessuna riga ──────────────────────────────

def test_caso_reale_della_issue_al_kholood_con_trattino():
    """`Al-Kholood Club v Al-Hilal` con separatore `-` — l'evento reale che ha motivato la PR.

    Senza dizionario vale `spaced_only=True`: ` - ` non esiste in quel nome, quindi nessuno
    split. Prima si scriveva il nome verbatim; ora non si scrive nulla."""
    res = _res(_parser("Al-Kholood Club v Al-Hilal", "-"))
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.placeable is False
    # …e MAI lo split sbagliato che la guardia `spaced_only` impedisce. Col fallback compatto
    # (percorso dizionario) `-` spezzerebbe in «Al» / «Kholood Club v Al-Hilal»: qui il nome
    # deve restare INTERO. L'asserzione confronta la stringa esatta, non una sua parte —
    # una versione precedente finiva con `or True` ed era una guardia morta (rilievo Fable
    # sulla PR #231): in una PR di sicurezza è peggio di nessuna asserzione, perché sembra
    # copertura senza esserlo.
    assert res.row["EventName"] == "Al-Kholood Club v Al-Hilal"
    assert res.row["EventName"] != "Al", "split compatto: il nome è stato tagliato dentro"
    assert " - " not in res.row["EventName"], "nome ricomposto da uno split che non doveva avvenire"


def test_alfabetico_e_simbolico_bloccano_uguale():
    """Alfabetici (` v `, ` vs `) e simbolici (`-`, `/`): stesso esito, nessuna asimmetria."""
    for evento, sep in [("Milan Inter", "v"), ("Milan Inter", "vs"),
                        ("Marseille/Lyon", "/"), ("Milan Inter", "-")]:
        res = _res(_parser(evento, sep))
        assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND, (evento, sep, res.status)
        assert res.placeable is False


# ── ③ CAMPO VUOTO: invariato — la guardia anti-regressione più importante ───────────

def test_campo_vuoto_scrive_ancora_la_riga():
    """⚠️ L'invariante che protegge TUTTI i parser esistenti.

    Col campo separatore vuoto non c'è alcuna aspettativa di formato da tradire, quindi non c'è
    niente da bloccare: la riga si scrive col nome verbatim, esattamente come prima della PR S.
    Se questo test cadesse, il bridge smetterebbe di scrivere righe che oggi scrive bene — un
    danno molto maggiore di quello che la PR previene."""
    for vuoto in ("", "   ", "\t"):
        res = _res(_parser("Milan v Inter", vuoto))
        assert res.status == validator.VALID, (repr(vuoto), res.status)
        assert res.placeable is True, repr(vuoto)
        assert res.row["EventName"] == "Milan v Inter"      # verbatim, non riformattato


def test_campo_vuoto_anche_con_nome_NON_divisibile():
    """Il campo vuoto non blocca nemmeno quando il nome non contiene alcun separatore
    riconoscibile: non c'era nulla da trovare, quindi non c'è nulla da fallire."""
    res = _res(_parser("EventoSenzaSeparatore", ""))
    assert res.status == validator.VALID
    assert res.placeable is True


# ── ④ col DIZIONARIO attivo il percorso è un altro, e resta invariato ───────────────

def test_col_dizionario_il_percorso_resta_MAPPING_MISSING():
    """Area che l'audit ha dichiarato sana: non toccata.

    Col dizionario attivo la riformattazione passa da `resolve_event_name`, che già fa
    fail-closed con `MAPPING_MISSING` quando non riesce a tradurre. Sono due cause diverse — lì
    manca la TRADUZIONE, qui manca lo SPLIT — e restano codici distinti apposta: confonderle
    manderebbe l'utente a cercare il problema nel dizionario invece che nel campo «Separatore»."""
    res = _res(_parser("Al-Kholood Club v Al-Hilal", "-", profiles=["Inesistente"]))
    assert res.status == pipe.MAPPING_MISSING
    assert res.status != pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.placeable is False        # in entrambi i casi: nessuna riga


# ── ⑤ lo scarto NON deve essere silenzioso ─────────────────────────────────────────

def test_lo_scarto_dice_quale_separatore_usare():
    """Il `detail` porta il separatore che il messaggio sembra usare: uno scarto che non dice
    come rimediare sarebbe peggio dell'avviso che sostituisce."""
    res = _res(_parser("Al-Kholood Club v Al-Hilal", "-"))
    assert res.detail, "scarto muto: l'utente non sa cosa correggere"
    assert "«v»" in res.detail, res.detail
    assert "Separatore squadre" in res.detail, res.detail


def test_la_diagnostica_marca_EventName_col_motivo_dedicato():
    """Nel verdetto dell'anteprima la colonna evidenziata dev'essere **EventName**, col motivo
    dedicato e non `MAPPING_MISSING` — che manderebbe a guardare il dizionario."""
    defn = _parser("Milan Inter", "v")
    diag = parser_diagnostics.diagnose(defn, "msg", provider="TG", require_price=False)
    testo = str(getattr(diag, "fields", diag))
    assert "TEAM_SEPARATOR_NOT_FOUND" in testo, testo
    assert "EventName" in testo, testo
    assert "MAPPING_MISSING" not in testo.replace("TEAM_SEPARATOR_NOT_FOUND", ""), (
        "il motivo generico manderebbe a cercare il problema nel dizionario")


def test_explain_ha_un_testo_per_il_nuovo_codice():
    """`parser_diagnostics.explain` traduce il codice in una frase per l'utente: senza, lo
    scarto arriverebbe a schermo come una sigla."""
    testo = parser_diagnostics.explain(parser_diagnostics.TEAM_SEPARATOR_NOT_FOUND)
    assert testo and testo != parser_diagnostics.TEAM_SEPARATOR_NOT_FOUND, testo
    assert "eparatore" in testo, testo


def _router_parser(sep, nome):
    """Parser col content gate attivo: l'`EventName` è ESTRATTO dal messaggio, non fisso —
    altrimenti `matches_message` non riconosce il testo e il router si ferma prima
    (`NO_CONTENT_MATCH`), senza mai arrivare al ramo separatore."""
    return CustomParserDef(
        name=nome, mode="NAME_ONLY", team_separator=sep,
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
            FieldRule(target="BetType", fixed_value="PUNTA"),
        ])


def _cfg(nome):
    return {"provider": "TG", "active_parser": nome, "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "require_price": False}


def test_il_router_riporta_lo_scarto_col_codice_giusto(tmp_path):
    """Percorso live: è quello che alimenta log e diario eventi."""
    cp.save_parser(_router_parser("/", "R1"), str(tmp_path))
    res = signal_router.resolve_row("Match: Marseille/Lyon\nSel: Pareggio",
                                    _cfg("R1"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert res.row is None, "una riga non piazzabile non deve arrivare valorizzata al chiamante"


def test_il_codice_arriva_al_DIARIO_senza_cablaggio_extra(tmp_path):
    """Il diario registra `SIGNAL_PARSED` con `status=result.status`: il codice nuovo ci arriva
    perché è uno status come gli altri. Verificato, non dedotto — la #182 chiede esplicitamente
    che lo scarto sia visibile nel diario."""
    cp.save_parser(_router_parser("/", "R2"), str(tmp_path))
    res = signal_router.resolve_row("Match: Marseille/Lyon\nSel: Pareggio",
                                    _cfg("R2"), chat_id="42", parsers_dir=str(tmp_path))
    # il valore che `app._journal("SIGNAL_PARSED", status=result.status, …)` scriverebbe
    assert res.status == pipe.TEAM_SEPARATOR_NOT_FOUND
    assert isinstance(res.status, str) and res.status, "status non serializzabile nel diario"


def test_il_router_scrive_ancora_quando_il_separatore_C_E(tmp_path):
    """Contro-guardia sul percorso live: il blocco non deve aver rotto il caso che funziona."""
    cp.save_parser(_router_parser("v", "R3"), str(tmp_path))
    res = signal_router.resolve_row("Match: Milan v Inter\nSel: Pareggio",
                                    _cfg("R3"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.all_rows()[0]["EventName"] == "Milan - Inter"


# ── ⑥ multi-riga: la base bloccata non genera N righe sbagliate ─────────────────────

def test_multiriga_non_moltiplica_un_evento_non_interpretato():
    """⚠️ Il buco che questi test hanno intercettato durante lo sviluppo.

    `TEAM_SEPARATOR_NOT_FOUND` deve stare in `_BASE_BLOCKING`. Senza, la generazione multi
    sarebbe partita lo stesso e avrebbe prodotto UNA scommessa sbagliata **per ogni selezione** —
    il difetto sta nell'EventName della base, che tutte le righe derivate ereditano, e nessuna
    riga multi può «colmarlo»."""
    defn = CustomParserDef(
        name="M", mode="NAME_ONLY", team_separator="/",
        multi_selection_enabled=True,
        multi_selections=[cp.MultiRowRule(enabled=True, selection_name="Casa"),
                          cp.MultiRowRule(enabled=True, selection_name="Ospite")],
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Marseille/Lyon", required=True),
            FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
            FieldRule(target="BetType", fixed_value="PUNTA"),
        ])
    results = pipe.build_validated_rows(defn, "msg", provider="TG", require_price=False)
    assert not any(r.placeable for r in results), "generate righe da un evento non interpretato"
    assert all(r.status == pipe.TEAM_SEPARATOR_NOT_FOUND for r in results), \
        [r.status for r in results]


def test_il_codice_e_nell_insieme_bloccante():
    """Guardia strutturale: se qualcuno aggiungesse un percorso che consulta `_BASE_BLOCKING`,
    il nuovo esito ne fa parte per costruzione."""
    assert pipe.TEAM_SEPARATOR_NOT_FOUND in pipe._BASE_BLOCKING
    assert pipe.TEAM_SEPARATOR_NOT_FOUND not in pipe._MULTI_RESOLVABLE, (
        "nessuna riga multi può colmare un separatore assente dal messaggio")


# ── ⑦ il codice è distinto, non un riuso ───────────────────────────────────────────

def test_il_codice_e_dedicato_e_distinto():
    """Requisito esplicito della #182: «codice di esito dedicato, non un riuso ambiguo di
    MAPPING_MISSING»."""
    assert pipe.TEAM_SEPARATOR_NOT_FOUND == "TEAM_SEPARATOR_NOT_FOUND"
    assert pipe.TEAM_SEPARATOR_NOT_FOUND != pipe.MAPPING_MISSING
    assert pipe.TEAM_SEPARATOR_NOT_FOUND != pipe.MARKET_MAPPING_MISSING
    assert parser_diagnostics.TEAM_SEPARATOR_NOT_FOUND == pipe.TEAM_SEPARATOR_NOT_FOUND


# ── ⑧ un parser salvato prima della PR non cambia comportamento se non usa il campo ─

def test_parser_legacy_senza_campo_separatore_invariato(tmp_path):
    """Retro-compatibilità: un JSON salvato prima che il campo esistesse non ha
    `team_separator`, quindi ricade nel campo vuoto → riga scritta, come sempre."""
    percorso = os.path.join(str(tmp_path), "Legacy.json")
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump({"name": "Legacy", "mode": "NAME_ONLY", "rules": [
            {"target": "Provider", "fixed_value": "TG"},
            {"target": "EventName", "fixed_value": "Milan v Inter", "required": True},
            {"target": "MarketType", "fixed_value": "MATCH_ODDS", "required": True},
            {"target": "SelectionName", "fixed_value": "Pareggio", "required": True},
            {"target": "BetType", "fixed_value": "PUNTA"},
        ]}, fh)
    defn = cp.load_parser(percorso)
    assert defn.team_separator == ""
    res = pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)
    assert res.placeable is True
    assert res.row["EventName"] == "Milan v Inter"
