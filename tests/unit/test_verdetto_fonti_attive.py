"""«Prova messaggio» deve dire il motivo per OGNI fonte attiva, non solo per i campi.

Ordine del proprietario (2026-08-04, dopo la #245): «se ho attivo multimarket,
multiselection, le condizioni di gate, il catalogo XTrader, provider, dizionario
nomi o dizionario mercati, facendo prova messaggio devo sapere tutto — e se
qualcosa è andato storto, il motivo, come le altre cose».

Stato misurato PRIMA della patch, eseguendo il codice vero:

    condizione di gate non soddisfatta  → ⛔ Non pronto (NO_CONTENT_MATCH)
                                          «nessun contenuto estratto dal messaggio»
    dizionario nomi non risolve         → ⛔ Non pronto (MAPPING_MISSING)
    dizionario mercati non risolve      → ⛔ Non pronto (MARKET_MAPPING_MISSING)
    Provider vuoto                      → ⛔ Non pronto (INVALID_MISSING_PROVIDER)
    multi: tutte le righe rotte         → ⛔ Nessuna delle 1 righe è piazzabile (INVALID_PRICE)
    multi acceso senza righe            → ✅ Pronto · …

Due difetti diversi.

**Il grave**: sulle condizioni di gate il motivo è *falso*. Il contenuto È stato
estratto correttamente — è la condizione ad aver fermato il messaggio — ma il
verdetto manda a cercare l'errore nei delimitatori, cioè nel posto sbagliato, e
non nomina la condizione colpevole.

**Il diffuso**: la spiegazione di ogni stato esiste già in
`parser_diagnostics._EXPLAIN` (la vedi nella tabella diagnostica sotto), ma non
arriva alla riga del verdetto, che resta una sigla.

Invariante di sicurezza che questi test presidiano: `diagnose` è usata SOLO
dall'anteprima (GUI `_test` e `batch_report`), mai dal runtime. Il gate live
continua a scartare esattamente gli stessi messaggi — cambia cosa viene
spiegato, non cosa passa.
"""
from __future__ import annotations

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as engine
from xtrader_bridge import parser_diagnostics as pdg
from xtrader_bridge.parser_builder import ParserBuilder

_BASE = [
    cp.FieldRule(target="Provider", fixed_value="TG"),
    cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
    cp.FieldRule(target="MarketType", fixed_value="OVER_UNDER", required=True),
    cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
    cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
    cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
]
_MSG = "Match: Juventus v Inter\nSel: Over 2,5\nQuota: 1,85\n"


def _builder(**kw) -> ParserBuilder:
    b = ParserBuilder()
    b.name = "P"
    b.mode = "NAME_ONLY"
    b.rules = [cp.FieldRule(**r.to_dict()) for r in _BASE]
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def _verdetto(b: ParserBuilder, *, provider="TG", msg=_MSG, **kw) -> str:
    """La riga ESATTA che l'utente legge dopo «🧪 Prova messaggio» (stessa
    composizione di `CustomParserPanel._test`)."""
    defn = b.to_def()
    rp = defn.price_required()
    res = b.test_message(msg, provider=provider, mode=b.mode, require_price=rp, **kw)
    diag = pdg.diagnose(defn, msg, provider=provider, mode=b.mode, require_price=rp, **kw)
    prev = b.preview_rows(msg, provider=provider, mode=b.mode, require_price=rp, **kw)
    return ParserBuilder.test_verdict(
        b.errors(), prev, diag_placeable=diag.placeable, diag_status=diag.status,
        res_row=res.row, res_missing_required=res.missing_required, res_detail=res.detail,
        content_ok=not diag.message_error, res_warnings=getattr(res, "warnings", ()),
        missing_reasons=pdg.motivi_campi_mancanti(diag),
        multi_warnings=b.multi_warnings(),
        status_reason=pdg.motivo_stato(diag),
        content_status=diag.message_error)


# ── 1. condizioni di gate: il motivo oggi è FALSO ────────────────────────────
def test_condizione_non_soddisfatta_ha_uno_stato_suo():
    """Non deve più essere confusa con «nessun contenuto estratto»: sono due
    diagnosi diverse che portano a due correzioni diverse."""
    b = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")])
    diag = pdg.diagnose(b.to_def(), _MSG, provider="TG", mode="NAME_ONLY", require_price=True)
    assert diag.status == pdg.CONDITIONS_NOT_MET
    assert diag.message_error == pdg.CONDITIONS_NOT_MET


def test_il_verdetto_nomina_la_condizione_che_ha_bloccato():
    b = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")])
    testo = _verdetto(b)
    assert "GOL ANNULLATO" in testo, testo
    assert "nessun contenuto estratto" not in testo, (
        "il contenuto ERA estraibile: accusare i delimitatori manda a cercare "
        f"l'errore nel posto sbagliato — {testo}")


def test_il_verdetto_distingue_contiene_da_non_contiene():
    """«NON contiene» violata: il testo c'è e non doveva esserci. Dirlo al
    contrario manderebbe ad aggiungere quello che va tolto."""
    b = _builder(conditions=[cp.Condition(text="Juventus", negate=True)])
    testo = _verdetto(b)
    assert "Juventus" in testo, testo
    assert "NON contiene" in testo, testo


def test_modo_O_dice_che_nessuna_delle_condizioni_e_soddisfatta():
    b = _builder(conditions=[cp.Condition(text="GOL"), cp.Condition(text="RIGORE")],
                 conditions_mode="any")
    testo = _verdetto(b)
    assert "GOL" in testo and "RIGORE" in testo, testo


def test_modo_E_nomina_SOLO_le_condizioni_davvero_fallite():
    """In «TUTTE (E)» basta una condizione a bloccare: elencare anche quelle
    soddisfatte manderebbe a correggere righe che vanno bene."""
    b = _builder(conditions=[cp.Condition(text="Juventus"),      # soddisfatta
                            cp.Condition(text="GOL ANNULLATO")],  # fallita
                 conditions_mode="all")
    testo = _verdetto(b)
    assert "GOL ANNULLATO" in testo, testo
    assert "Juventus" not in testo, f"nominata una condizione soddisfatta: {testo}"


def test_il_gate_del_RUNTIME_non_cambia():
    """Invariante di sicurezza: la patch tocca solo la SPIEGAZIONE. Il motore
    continua a fermare e a far passare esattamente gli stessi messaggi."""
    bloccante = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")]).to_def()
    passante = _builder(conditions=[cp.Condition(text="Juventus")]).to_def()
    assert engine.conditions_pass(bloccante, _MSG) is False
    assert engine.conditions_pass(passante, _MSG) is True
    assert engine.matches_message(bloccante, _MSG, "NAME_ONLY") is False
    assert engine.matches_message(passante, _MSG, "NAME_ONLY") is True


def test_nessun_contenuto_estratto_resta_distinto():
    """L'altro caso non deve essere assorbito: un parser a soli valori fissi
    continua a dire NO_CONTENT_MATCH, che lì è il motivo giusto."""
    b = _builder()
    b.rules = [cp.FieldRule(target="Provider", fixed_value="TG"),
               cp.FieldRule(target="EventName", fixed_value="X v Y", required=True),
               cp.FieldRule(target="MarketType", fixed_value="OVER_UNDER", required=True),
               cp.FieldRule(target="SelectionName", fixed_value="Over 2,5", required=True),
               cp.FieldRule(target="Price", fixed_value="1.85", required=True),
               cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True)]
    diag = pdg.diagnose(b.to_def(), _MSG, provider="TG", mode="NAME_ONLY", require_price=True)
    assert diag.status == pdg.NO_CONTENT_MATCH


# ── 2. gli stati di riga non devono restare sigle nude ───────────────────────
def test_dizionario_nomi_spiega_perche():
    b = _builder(name_mapping_profiles=["squadre"])
    testo = _verdetto(b, name_mapping_profiles=[])
    assert pdg.MAPPING_MISSING in testo, testo
    assert "non traducibile" in testo, f"sigla nuda, nessun motivo: {testo}"


def test_dizionario_mercati_spiega_perche():
    b = _builder(market_mapping_profiles=["mercati"])
    b.rules = [r for r in b.rules if r.target != "MarketType"]
    testo = _verdetto(b, market_mapping_profiles=[])
    assert pdg.MARKET_MAPPING_MISSING in testo, testo
    assert "non risolvibile" in testo, f"sigla nuda, nessun motivo: {testo}"


def test_provider_vuoto_spiega_perche():
    b = _builder()
    b.rules = [r for r in b.rules if r.target != "Provider"]
    testo = _verdetto(b, provider="")
    assert "Provider" in testo, testo
    # non basta la sigla INVALID_MISSING_PROVIDER: serve la frase che dice cosa fare
    assert "contratto" in testo or "mancante" in testo, f"sigla nuda: {testo}"


def test_catalogo_xtrader_id_mancanti_resta_esplicito():
    """Caso già a posto prima della patch: non deve regredire."""
    b = _builder()
    b.mode = "ID_ONLY"
    testo = _verdetto(b)
    assert "MarketId" in testo and "SelectionId" in testo, testo


def test_il_motivo_dello_stato_viene_dalla_fonte_unica():
    """Regola 3: nessun letterale nuovo — la frase è quella di `_EXPLAIN`, la
    stessa che la tabella diagnostica mostra già."""
    for codice in (pdg.MAPPING_MISSING, pdg.MARKET_MAPPING_MISSING,
                   pdg.NO_CONTENT_MATCH, pdg.CONDITIONS_NOT_MET):
        assert pdg.explain(codice), f"{codice} senza spiegazione in _EXPLAIN"


def test_verdetto_pronto_non_guadagna_rumore():
    """Un parser che va bene deve restare pulito com'era."""
    testo = _verdetto(_builder())
    assert testo.startswith("✅ Pronto · "), testo
    assert "⚠" not in testo and "⛔" not in testo, testo


# ── 3. multi-riga: quale riga, e l'interruttore a vuoto ──────────────────────
def test_multi_riga_rotta_viene_nominata():
    b = _builder(multi_market_enabled=True,
                 multi_markets=[cp.MultiRowRule(market_type="CORRECT_SCORE", price="abc"),
                                cp.MultiRowRule(market_type="MATCH_ODDS")])
    testo = _verdetto(b)
    assert "1/2" in testo or "1 di 2" in testo, testo
    assert "riga 1" in testo.lower(), f"non dice QUALE riga è scartata: {testo}"
    assert pdg.INVALID_PRICE in testo, f"non dice PERCHÉ è scartata: {testo}"


def test_multi_tutte_rotte_spiega_lo_stato():
    b = _builder(multi_market_enabled=True,
                 multi_markets=[cp.MultiRowRule(price="abc")])
    testo = _verdetto(b)
    assert pdg.INVALID_PRICE in testo, testo
    assert "quota" in testo.lower(), f"sigla nuda, nessun motivo: {testo}"


def test_interruttore_multi_acceso_senza_righe_compare_nel_verdetto():
    """L'avviso esiste, ma solo nel banner arancione della sezione: chi guarda il
    verdetto crede che le righe extra verranno generate, e invece no."""
    b = _builder(multi_market_enabled=True)
    testo = _verdetto(b)
    assert "MultiMarket" in testo, f"il verdetto tace sull'interruttore a vuoto: {testo}"
    assert "nessuna riga" in testo.lower(), testo


def test_interruttore_a_vuoto_non_trasforma_pronto_in_bloccato():
    """È un AVVISO, non un errore: la riga base resta piazzabile e il verdetto
    deve continuare a dirlo — declassarlo a ⛔ sarebbe un falso allarme."""
    b = _builder(multi_selection_enabled=True)
    testo = _verdetto(b)
    assert testo.startswith("✅ Pronto"), testo
    assert "MultiSelection" in testo, testo


def test_multi_senza_anomalie_non_aggiunge_avvisi():
    b = _builder(multi_market_enabled=True,
                 multi_markets=[cp.MultiRowRule(market_type="MATCH_ODDS")])
    testo = _verdetto(b)
    assert "⚠" not in testo, testo


# ── 4. retrocompatibilità dei chiamanti che non passano i nuovi argomenti ────
def test_test_verdict_resta_identico_senza_i_nuovi_argomenti():
    """`batch_report` e i test storici non passano `multi_warnings`/`status_reason`:
    devono vedere ESATTAMENTE la riga di prima."""
    args = dict(diag_placeable=False, diag_status=pdg.MAPPING_MISSING, res_row={},
                res_missing_required=[], res_detail=None)
    assert (ParserBuilder.test_verdict([], [], **args)
            == f"⛔ Non pronto ({pdg.MAPPING_MISSING})")


# ── 5. anche tabella e appunti dicono lo stesso, non meno ────────────────────
def _diagnosi(b: ParserBuilder, msg=_MSG, **kw):
    defn = b.to_def()
    return defn, pdg.diagnose(defn, msg, provider="TG", mode=b.mode,
                              require_price=defn.price_required(), **kw)


def test_la_tabella_diagnostica_nomina_la_condizione():
    """Il banner in testa alla tabella mostrava la spiegazione del solo CODICE: per le
    condizioni sarebbe stata più povera del verdetto sopra, e per giunta quella
    sbagliata prima della patch."""
    defn, diag = _diagnosi(_builder(conditions=[cp.Condition(text="GOL ANNULLATO")]))
    banner = [r for r in pdg.diagnostic_table(diag, defn) if r.banner]
    assert len(banner) == 1
    assert banner[0].target == pdg.CONDITIONS_NOT_MET
    assert "GOL ANNULLATO" in banner[0].reason, banner[0].reason


def test_il_report_negli_appunti_porta_il_motivo_dello_stato():
    """«📋 Copia diagnostica» serve a incollare il problema altrove: se lì resta la
    sigla nuda, chi legge il testo copiato è al punto di partenza."""
    defn, diag = _diagnosi(_builder(name_mapping_profiles=["squadre"]),
                           name_mapping_profiles=[])
    testo = pdg.format_report(diag)
    assert pdg.MAPPING_MISSING in testo
    assert "non traducibile" in testo, testo


def test_il_report_di_un_parser_sano_non_guadagna_righe():
    _defn, diag = _diagnosi(_builder())
    testo = pdg.format_report(diag)
    assert testo.startswith("PRONTO ✅")
    assert "•" not in testo, f"riga di motivo aggiunta a un parser che va bene: {testo}"


def test_il_testo_delle_condizioni_e_sanificato_come_il_valore_letto():
    """Il testo della condizione lo scrive l'utente ma finisce accanto a testo del
    bridge: stessa classe di rischio del valore letto (#245) — control-char, bidi
    override e delimitatori vanno neutralizzati anche qui."""
    b = _builder(conditions=[cp.Condition(text="A\x1b[31mB\x00C‮D» finto motivo")])
    testo = _verdetto(b)
    for ch in ("\x1b", "\x00", "‮"):
        assert ch not in testo, f"control char {ch!r} sopravvissuto: {testo!r}"
    corpo = testo.split("di gate ", 1)[1]
    assert corpo.count("«") == 1 and corpo.count("»") == 1, corpo


def test_condizione_lunghissima_viene_capata():
    b = _builder(conditions=[cp.Condition(text="Z" * 400)])
    testo = _verdetto(b)
    assert "…" in testo, "il troncamento deve essere VISIBILE"
    assert len(testo) < 300, f"riga illeggibile ({len(testo)})"


def test_condizione_fallita_su_parser_MULTI_riga():
    """Il caso che passa dal ramo multi-riga del verdetto, dove il codice di stato
    NON viene da `diag_status` ma dal parametro esplicito `content_status`: se lì si
    perdesse la distinzione, un parser multi con condizioni tornerebbe a dire
    «nessun contenuto estratto» — il motivo sbagliato di prima."""
    b = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")],
                 multi_market_enabled=True,
                 multi_markets=[cp.MultiRowRule(market_type="MATCH_ODDS")])
    testo = _verdetto(b)
    assert pdg.CONDITIONS_NOT_MET in testo, testo
    assert "GOL ANNULLATO" in testo, testo
    assert "nessun contenuto estratto" not in testo, testo


def test_content_status_assente_conserva_il_codice_storico():
    """Contratto verso i chiamanti che non lo passano (report batch, test storici):
    il ramo di contenuto continua a nominare NO_CONTENT_MATCH come prima."""
    from xtrader_bridge.parser_builder import PreviewRow
    righe = [PreviewRow(index=0, kind="market", placeable=True, status="VALID")]
    testo = ParserBuilder.test_verdict(
        [], righe, diag_placeable=True, diag_status="VALID", res_row={},
        res_missing_required=[], res_detail=None, content_ok=False)
    assert pdg.NO_CONTENT_MATCH in testo, testo


# ── 6. il tester MULTIPLO e l'assistente devono dire le stesse cose ──────────
# Il tester multiplo fa `strip()` su ogni messaggio (`split_messages`): l'ULTIMO campo
# perde l'a-capo, e con `end_before="\n"` non si estrarrebbe più. È un comportamento
# preesistente del batch, non di questa patch: qui si usa un messaggio con una riga in
# coda, così sotto test resta il verdetto e non quell'artefatto.
_MSG_BATCH = _MSG + "fine\n"
def test_il_verdetto_del_tester_multiplo_e_quello_del_singolo():
    """`batch_report` promette nel suo docstring «è lo stesso `test_verdict` del
    singolo «Prova messaggio»». Aggiungendo i motivi al solo percorso singolo quella
    promessa si rompe in silenzio: il tester multiplo — e l'assistente, che passa di
    qui — tornerebbero alla sigla nuda, e per le condizioni al motivo SBAGLIATO.

    Rilievo del proprietario (2026-08-04): «anche le docs dell'assistente devono
    essere sincronizzate al codice» — e prima ancora il codice a sé stesso."""
    b = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")])
    reports, _skipped = b.batch_report(_MSG_BATCH, provider="TG", mode="NAME_ONLY",
                                       require_price=True)
    assert len(reports) == 1
    verdetto = reports[0].verdict
    assert pdg.CONDITIONS_NOT_MET in verdetto, verdetto
    assert "GOL ANNULLATO" in verdetto, verdetto
    assert "nessun contenuto estratto" not in verdetto, verdetto


def test_il_tester_multiplo_spiega_anche_gli_stati_di_riga():
    b = _builder(name_mapping_profiles=["squadre"])
    reports, _ = b.batch_report(_MSG_BATCH, provider="TG", mode="NAME_ONLY",
                                require_price=True, name_mapping_profiles=[])
    verdetto = reports[0].verdict
    assert pdg.MAPPING_MISSING in verdetto and "non traducibile" in verdetto, verdetto


def test_il_tester_multiplo_porta_gli_avvisi_multi():
    b = _builder(multi_market_enabled=True)
    reports, _ = b.batch_report(_MSG_BATCH, provider="TG", mode="NAME_ONLY", require_price=True)
    verdetto = reports[0].verdict
    assert verdetto.startswith("✅ Pronto"), verdetto
    assert "MultiMarket" in verdetto, verdetto


def test_anteprima_dell_assistente_riporta_il_verdetto_col_motivo(monkeypatch):
    """Il tool sola-lettura `test_message` dell'assistente costruisce la sua anteprima
    da `batch_report`: il motivo deve arrivare fino al JSON che il modello legge,
    altrimenti l'assistente spiega MENO di quanto mostra la GUI sulla stessa cosa —
    ed è l'assistente che l'utente interroga quando la GUI non gli basta.

    Si stuba solo il CARICAMENTO del parser (seam iniettabile): sotto test è la
    propagazione del verdetto, non la risoluzione del parser attivo per la chat."""
    from xtrader_bridge import config_agent, parser_manager

    defn = _builder(conditions=[cp.Condition(text="GOL ANNULLATO")]).to_def()
    monkeypatch.setattr(parser_manager, "load_primary_parser",
                        lambda *a, **k: defn)
    dati = config_agent.build_message_preview({"provider": "TG"}, _MSG_BATCH)
    verdetti = [r["verdict"] for r in dati.get("reports", [])]
    assert verdetti, dati
    assert any(pdg.CONDITIONS_NOT_MET in v and "GOL ANNULLATO" in v for v in verdetti), verdetti


def test_il_system_prompt_insegna_a_non_confondere_le_due_cause():
    """La riga del prompt che dice al modello QUANDO e COME usare il tool fa parte
    del contratto (disciplina di estensione dell'assistente): il verdetto ora
    distingue due cause opposte — condizione di gate contro nulla di estratto — e
    l'assistente deve saperlo, o le confonderà a parole dopo che il codice le ha
    separate, suggerendo di correggere i delimitatori al posto della condizione."""
    from xtrader_bridge import config_agent

    prompt = config_agent.build_system_prompt("IT")
    assert pdg.CONDITIONS_NOT_MET in prompt
    assert pdg.NO_CONTENT_MATCH in prompt
    assert "delimitatori" in prompt.lower()
