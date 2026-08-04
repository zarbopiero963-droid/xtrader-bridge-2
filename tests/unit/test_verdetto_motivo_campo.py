"""«Prova messaggio» deve dire CHI ha svuotato il campo, non solo quale manca.

Ordine del proprietario (2026-08-04, dopo la #244). Oggi il verdetto sintetico dice:

    ⛔ Non pronto (NOT_READY) · mancanti: SelectionName

e lascia indovinare fra tre cause diverse: delimitatori sbagliati, testo estratto
che la **trasformazione** non sa leggere, o value-map che non trova l'alias. Il
motivo esiste già per-colonna in `parser_diagnostics` (codici `TRANSFORM_FAILED`,
`START_NOT_FOUND`, `VALUE_MAP_MISS`…) ma **non arriva** alla riga del verdetto: chi
prova un messaggio legge «manca SelectionName» e deve dedurre il resto.

Qui si pretende che il verdetto porti il motivo azionabile — con il **valore
davvero letto**, che è l'informazione che chiude il caso in un colpo d'occhio.
"""
from __future__ import annotations

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_diagnostics as pd
from xtrader_bridge.parser_builder import ParserBuilder

_BASE = [
    cp.FieldRule(target="Provider", fixed_value="TG"),
    cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
    cp.FieldRule(target="MarketType", fixed_value="OVER_UNDER", required=True),
    cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
    cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
]
_MSG = "Match: Juventus v Inter\nRisultato: primo tempo\nQuota: 1,85\n"


def _diagnosi(regola_selection):
    defn = cp.CustomParserDef(name="P", rules=[*_BASE, regola_selection])
    return defn, pd.diagnose(defn, _MSG, provider="TG", mode="NAME_ONLY", require_price=True)


def test_motivi_nomina_la_trasformazione_e_il_valore_letto():
    """Il caso reale: `score_to_over_ht` su un testo che non è un punteggio."""
    _defn, diag = _diagnosi(cp.FieldRule(
        target="SelectionName", start_after="Risultato:", end_before="\n",
        transform="score_to_over_ht", required=True))
    motivi = pd.motivi_campi_mancanti(diag)
    assert "SelectionName" in motivi
    testo = motivi["SelectionName"]
    assert "score_to_over_ht" in testo, testo      # CHI ha svuotato
    assert "primo tempo" in testo, testo           # COSA aveva letto


def test_motivi_distingue_il_delimitatore_sbagliato():
    """Stessa colonna vuota, causa diversa: il verdetto non deve accusare la
    trasformazione quando è l'estrazione a non aver trovato nulla."""
    _defn, diag = _diagnosi(cp.FieldRule(
        target="SelectionName", start_after="Punteggio:", end_before="\n",
        transform="score_to_over_ht", required=True))
    testo = pd.motivi_campi_mancanti(diag)["SelectionName"]
    assert "Inizia dopo" in testo, testo
    assert "score_to_over_ht" not in testo, testo


def test_motivi_ignora_le_colonne_a_posto():
    _defn, diag = _diagnosi(cp.FieldRule(
        target="SelectionName", start_after="Risultato:", end_before="\n", required=True))
    motivi = pd.motivi_campi_mancanti(diag)
    assert "SelectionName" not in motivi
    assert "EventName" not in motivi


def test_il_verdetto_porta_il_motivo_accanto_al_campo():
    """Il contratto visibile all'utente: la riga di «Prova messaggio»."""
    verdetto = ParserBuilder.test_verdict(
        [], [], diag_placeable=False, diag_status="NOT_READY", res_row={},
        res_missing_required=["SelectionName"], res_detail=None,
        missing_reasons={"SelectionName":
                         "la trasformazione «score_to_over_ht» non ha riconosciuto "
                         "un punteggio in «primo tempo»"})
    assert "mancanti: SelectionName" in verdetto
    assert "score_to_over_ht" in verdetto
    assert "primo tempo" in verdetto


def test_il_verdetto_resta_identico_senza_motivi():
    """Retrocompatibilità: i chiamanti che non passano i motivi (report batch,
    test esistenti) devono vedere ESATTAMENTE la riga di prima."""
    args = dict(diag_placeable=False, diag_status="NOT_READY", res_row={},
                res_missing_required=["SelectionName"], res_detail=None)
    assert (ParserBuilder.test_verdict([], [], **args)
            == "⛔ Non pronto (NOT_READY) · mancanti: SelectionName")


def test_motivo_taglia_e_appiattisce_il_testo_dell_utente():
    """Rilievo convergente Fable 5 + GPT-5.5 sulla #245: il valore letto viene dal
    messaggio Telegram — testo NON attendibile. Se finisse grezzo nel verdetto, un
    messaggio lungo lo renderebbe illeggibile e uno multilinea potrebbe «spoofare»
    le righe sotto (la stessa classe di rischio dei control-char nel CSV)."""
    lungo = "A" * 300
    regola = cp.FieldRule(target="SelectionName", start_after="Risultato:",
                          end_before="§", transform="score_to_over_ht", required=True)
    defn = cp.CustomParserDef(name="P", rules=[*_BASE, regola])
    msg = f"Match: J v I\nRisultato: {lungo}\nRIGA FALSA\n§\nQuota: 1,85\n"
    diag = pd.diagnose(defn, msg, provider="TG", mode="NAME_ONLY", require_price=True)
    testo = pd.motivi_campi_mancanti(diag)["SelectionName"]
    assert "\n" not in testo and "\r" not in testo, "a-capo non appiattiti"
    assert len(testo) < 200, f"motivo troppo lungo ({len(testo)}): riga illeggibile"
    assert "…" in testo, "il troncamento deve essere VISIBILE, non silenzioso"


def test_motivo_non_tronca_i_valori_corti():
    """Il caso normale resta intatto: nessun «…» quando non serve."""
    _defn, diag = _diagnosi(cp.FieldRule(
        target="SelectionName", start_after="Risultato:", end_before="\n",
        transform="score_to_over_ht", required=True))
    testo = pd.motivi_campi_mancanti(diag)["SelectionName"]
    assert "«primo tempo»" in testo and "…" not in testo


def _motivo_con_valore(valore: str) -> str:
    """Motivo prodotto quando la trasformazione fallisce su `valore`."""
    regola = cp.FieldRule(target="SelectionName", start_after="Risultato:",
                          end_before="§", transform="score_to_over_ht", required=True)
    defn = cp.CustomParserDef(name="P", rules=[*_BASE, regola])
    msg = f"Match: J v I\nRisultato: {valore}§\nQuota: 1,85\n"
    diag = pd.diagnose(defn, msg, provider="TG", mode="NAME_ONLY", require_price=True)
    return pd.motivi_campi_mancanti(diag)["SelectionName"]


def test_motivo_neutralizza_i_control_char_non_whitespace():
    """Rilievo Fable 5 (#245, bloccante): `split()` appiattisce solo lo whitespace.
    ESC/NUL e i **bidi override** (U+202E, che ribalta visivamente il testo a valle)
    passavano intatti — e il docstring prometteva il contrario. La promessa scritta
    dev'essere quella mantenuta."""
    testo = _motivo_con_valore("A\x1b[31mB\x00C‮D")
    for ch in ("\x1b", "\x00", "‮"):
        assert ch not in testo, f"control char {ch!r} sopravvissuto: {testo!r}"


def test_motivo_neutralizza_i_delimitatori_del_motivo_stesso():
    """Un valore che contiene «» chiuderebbe visivamente il delimitatore e potrebbe
    far sembrare «testo del bridge» quello scelto da chi manda il messaggio."""
    testo = _motivo_con_valore("X» e poi «finto motivo")
    corpo = testo.split("leggere ", 1)[1]
    assert corpo.count("«") == 1 and corpo.count("»") == 1, corpo


def test_motivo_appiattisce_tab_ritorni_e_spazi_ripetuti():
    """Completa la copertura chiesta da GPT-5.5: non solo `\\n`."""
    testo = _motivo_con_valore("A\tB\rC   D")
    assert "«A B C D»" in testo, testo


def test_motivo_conserva_i_valori_falsy_non_stringa():
    """`str(valore or "")` schiacciava `0`/`False` a vuoto perdendo l'informazione
    (rilievo GPT-5.5): il motivo deve dire cosa ha letto, anche se è «0»."""
    assert pd._leggibile(0) == "0"
    assert pd._leggibile(False) == "False"
    assert pd._leggibile(None) == ""


def test_contratto_esatto_del_troncamento():
    """Il contratto è fissato, non «< 200»: `_MAX_VALORE` caratteri + il segno «…»."""
    reso = pd._leggibile("B" * 500)
    assert len(reso) == pd._MAX_VALORE + 1
    assert reso.endswith("…") and reso[:-1] == "B" * pd._MAX_VALORE


def test_anche_il_ramo_value_map_e_sanificato():
    """L'altro percorso che interpola testo utente (GPT-5.5: non era coperto)."""
    regola = cp.FieldRule(target="SelectionName", start_after="Risultato:",
                          end_before="§", value_map="selectionname", required=True)
    defn = cp.CustomParserDef(name="P", rules=[*_BASE, regola])
    msg = "Match: J v I\nRisultato: X\x1b[31m» finto\nQuota: 1,85\n§\n"
    diag = pd.diagnose(defn, msg, provider="TG", mode="NAME_ONLY", require_price=True)
    testo = pd.motivi_campi_mancanti(diag)["SelectionName"]
    assert "value-map" in testo
    assert "\x1b" not in testo and "\n" not in testo
    corpo = testo.split("trovato ", 1)[1]
    assert corpo.count("«") == 1 and corpo.count("»") == 1, corpo
