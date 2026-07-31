"""B5 (#194 · PR-G) — `Points` e `Handicap` senza tetto né controllo di finitezza.

Il buco misurato prima della patch: la regex del contratto accetta SOLO cifre e un
separatore, quindi non può produrre `inf` per via *testuale* («inf», «1e400» sono
respinti) — ma una stringa di sole cifre abbastanza lunga sì: ``float("9"*400)`` è
``inf``. E un tetto scritto come confronto lascia passare l'infinito nel verso
sbagliato: ``inf <= 0.0`` è ``False``, quindi ``points_status`` rispondeva ``VALID``.

Perché conta: `Points` è il **moltiplicatore dello stake** quando la strategia XTrader
ha la spunta «Modula lo Stake con dato Points del segnale se disponibile»
(vedi `docs/xtrader_csv_contract.md` → «Lato XTrader»). Un Points fuori scala è uno
stake fuori scala. `Handicap` fuori scala è una linea che XTrader non riconosce, o
riconosce sulla selezione sbagliata.

Tetti decisi dal proprietario il 2026-07-31: `Points` ≤ 100 (i provider reali usano
1-10; 100 limita il danno di un valore errato a 100× invece che 1000×), `|Handicap|`
≤ 1000 (copre ogni linea Betfair reale, comprese quelle grandi dei mercati a
punti/run).
"""

import pytest

from xtrader_bridge import custom_pipeline, numbers_re, validator
from xtrader_bridge.betfair import dictionary_resolver

# Sole cifre: supera la regex del contratto, ma `float()` lo porta a infinito.
INFINITO_DI_SOLE_CIFRE = "9" * 400


def _riga(**override):
    """Riga CSV completa e VALIDA, su cui sovrascrivere il solo campo in esame."""
    riga = {"Provider": "PBet", "EventId": "", "EventName": "Inter v Milan",
            "MarketId": "", "MarketName": "", "MarketType": "MATCH_ODDS",
            "SelectionId": "", "SelectionName": "Inter", "Handicap": "0",
            "Price": "1.85", "MinPrice": "", "MaxPrice": "", "BetType": "PUNTA",
            "Points": ""}
    riga.update(override)
    return riga


# ─────────────────────────────── il buco misurato ────────────────────────────────

def test_una_stringa_di_sole_cifre_diventa_davvero_infinito():
    """Il presupposto del bug, reso esplicito: senza questo, il resto non ha senso."""
    assert validator._DECIMAL_PRICE.match(INFINITO_DI_SOLE_CIFRE)   # la regex la accetta
    assert float(INFINITO_DI_SOLE_CIFRE) == float("inf")            # ma float() esplode
    # E il confronto «> 0» da solo NON la ferma: è il verso in cui il bug passava.
    assert not (float(INFINITO_DI_SOLE_CIFRE) <= 0.0)


def test_points_infinito_e_respinto():
    assert validator.points_status(INFINITO_DI_SOLE_CIFRE) == validator.INVALID_POINTS


def test_riga_con_points_infinito_non_e_piazzabile():
    """Il test che conta: non il predicato isolato, ma la riga intera verso il CSV."""
    stato, _ = validator.validate(_riga(Points=INFINITO_DI_SOLE_CIFRE), "NAME_ONLY")
    assert stato == validator.INVALID_POINTS


def test_handicap_infinito_e_respinto():
    assert validator.handicap_status(INFINITO_DI_SOLE_CIFRE) == validator.INVALID_HANDICAP
    assert validator.handicap_status("-" + INFINITO_DI_SOLE_CIFRE) == validator.INVALID_HANDICAP


def test_riga_con_handicap_infinito_non_e_piazzabile():
    stato, _ = validator.validate(_riga(Handicap=INFINITO_DI_SOLE_CIFRE), "NAME_ONLY")
    assert stato == validator.INVALID_HANDICAP


# ──────────────────────────────── i tetti, ai bordi ───────────────────────────────

@pytest.mark.parametrize("valore, atteso", [
    ("1", validator.VALID),          # il moltiplicatore neutro
    ("2,5", validator.VALID),        # virgola decimale: il contratto la accetta
    ("100", validator.VALID),        # BORDO INCLUSO
    ("100.01", validator.INVALID_POINTS),   # primo valore oltre il bordo
    ("101", validator.INVALID_POINTS),
    ("0", validator.INVALID_POINTS),        # il vincolo > 0 preesistente resta
    ("", validator.VALID),                  # facoltativo: vuoto resta valido
])
def test_bordi_del_tetto_points(valore, atteso):
    assert validator.points_status(valore) == atteso


@pytest.mark.parametrize("valore, atteso", [
    ("0", validator.VALID),
    ("-1,5", validator.VALID),       # handicap asiatico col segno e la virgola
    ("+2.5", validator.VALID),
    ("1000", validator.VALID),       # BORDO INCLUSO
    ("-1000", validator.VALID),      # il tetto è sul VALORE ASSOLUTO
    ("1000.01", validator.INVALID_HANDICAP),
    ("-1000.01", validator.INVALID_HANDICAP),
    ("", validator.VALID),           # facoltativo (il default del contratto è "0")
    ("abc", validator.INVALID_HANDICAP),
    (".5", validator.INVALID_HANDICAP),   # forma che la regex del contratto già rifiutava
])
def test_bordi_del_tetto_handicap(valore, atteso):
    assert validator.handicap_status(valore) == atteso


# ────────────────── la classe: TUTTI i gate, non solo quello segnalato ──────────────

def test_il_gate_handicap_della_riga_BASE_applica_il_tetto():
    riga = _riga(Handicap=INFINITO_DI_SOLE_CIFRE)
    assert custom_pipeline._handicap_bloccante(riga) is True


def test_il_gate_handicap_della_riga_MULTI_applica_lo_STESSO_tetto():
    """Il secondo gate esisteva già (#192) ma controllava solo il formato: correggere
    solo quello base avrebbe lasciato il buco aperto sul percorso multi-riga."""
    riga = _riga(Handicap=INFINITO_DI_SOLE_CIFRE)
    assert custom_pipeline._handicap_bloccante(riga) is True
    # Controprova: un handicap legittimo NON viene bloccato da nessuno dei due.
    assert custom_pipeline._handicap_bloccante(_riga(Handicap="-1,5")) is False


def test_i_due_gate_condividono_la_STESSA_fonte():
    """Regola 3: se il predicato fosse copiato, un domani i due gate divergerebbero.
    Questo test è rosso se qualcuno reintroduce una seconda implementazione."""
    import inspect
    sorgente = inspect.getsource(custom_pipeline)
    # Il predicato compare una volta sola come DEFINIZIONE; i gate lo CHIAMANO.
    assert sorgente.count("def _handicap_bloccante") == 1
    assert sorgente.count("_handicap_bloccante(row)") == 2


# ──────────────── il sibling trovato dal grep: il resolver del dizionario ───────────

def test_il_resolver_del_dizionario_scarta_un_handicap_non_finito():
    """Stessa classe, altro modulo: `_num` faceva `float()` senza controllare la
    finitezza. Due handicap infiniti si sarebbero confrontati UGUALI, facendo
    combaciare una selezione sbagliata. Fail-closed = nessun match = fallback nomi."""
    assert dictionary_resolver._hcap_value(INFINITO_DI_SOLE_CIFRE) is None
    assert dictionary_resolver._hcap_value("-" + INFINITO_DI_SOLE_CIFRE) is None
    # Controprova: i valori reali continuano a risolversi.
    assert dictionary_resolver._hcap_value("1,5") == 1.5
    assert dictionary_resolver._hcap_value("-0.5") == -0.5


# ───────────────────── il prezzo non deve cambiare comportamento ────────────────────

@pytest.mark.parametrize("valore", [
    "1.85", "1000", "1.01", "999.99", "1.0", "0.5", "abc", "", "1e2", INFINITO_DI_SOLE_CIFRE,
])
def test_il_prezzo_si_comporta_esattamente_come_prima(valore):
    """`_price_status` viene instradato sul predicato condiviso per uniformità. Era già
    al sicuro (`inf <= 1000.0` è False), quindi il rifattore NON deve spostare nulla:
    qui si fissa l'equivalenza con la regola originale, ricalcolata a mano."""
    def regola_originale(v):
        if v is None:
            return validator.INVALID_MISSING_PRICE
        s = str(v).strip()
        if not s:
            return validator.INVALID_MISSING_PRICE
        if not validator._DECIMAL_PRICE.match(s):
            return validator.INVALID_PRICE
        prezzo = float(s.replace(",", "."))
        return validator.VALID if 1.0 < prezzo <= 1000.0 else validator.INVALID_PRICE

    assert validator.price_status(valore) == regola_originale(valore)


# ─────────────────────────── la fonte unica del predicato ───────────────────────────

def test_valore_finito_e_la_fonte_unica_del_parsing_numerico():
    assert numbers_re.valore_finito("1,85") == 1.85
    assert numbers_re.valore_finito("1.85") == 1.85
    assert numbers_re.valore_finito("-0,5") == -0.5
    assert numbers_re.valore_finito(INFINITO_DI_SOLE_CIFRE) is None
    assert numbers_re.valore_finito("-" + INFINITO_DI_SOLE_CIFRE) is None


def test_nessun_tetto_e_scritto_due_volte():
    """Regola 3 sui NUMERI, non solo sul codice: i tetti vivono in una costante sola."""
    import inspect
    sorgente = inspect.getsource(validator)
    assert sorgente.count("_MAX_POINTS = ") == 1
    assert sorgente.count("_MAX_HANDICAP = ") == 1
    # E non compaiono come letterali sparsi nei confronti.
    assert "<= 100.0" not in sorgente
    assert "<= 1000.0" not in sorgente


# ══════════════════════════════════════════════════════════════════════════════════
# Richiesti da GPT-5.5 sulla #202. Il suo rilievo era che instradare
# `dictionary_resolver._hcap_value` su `valore_finito` potesse fargli perdere la
# notazione scientifica, se `valore_finito` applicasse la regex del contratto CSV.
# Non la applica — ma la garanzia non era protetta da alcun test, e quella lacuna
# era reale: il dizionario legge da SQLite, dove un REAL piccolo si serializza
# proprio come «1e-05».
# ══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("valore, atteso", [
    ("1e-05", 1e-05),         # come SQLite serializza un REAL piccolo
    ("1E-05", 1e-05),         # maiuscola
    ("-1e-05", -1e-05),
    ("1e+2", 100.0),
    (1e-05, 1e-05),           # float nativo dal driver, non stringa
    (0.5, 0.5),
    (-1.5, -1.5),
    ("1,5", 1.5),             # virgola: il parser la produce, SQLite no
    ("1.5", 1.5),
    ("-0,5", -0.5),
    ("+2.5", 2.5),
    ("  1.5  ", 1.5),         # spazi
    ("0", 0.0),
])
def test_il_resolver_NON_ha_perso_i_formati_che_accettava(valore, atteso):
    """Regressione bloccata: il resolver del dizionario NON passa dalla regex del
    contratto CSV e deve continuare ad accettare tutto ciò che accettava prima —
    notazione scientifica compresa. Se un domani qualcuno ci mettesse la regex
    davanti, questi casi diventano rossi invece di degradare in silenzio gli ID a
    nomi su tutti gli handicap serializzati da SQLite."""
    assert dictionary_resolver._hcap_value(valore) == atteso


def test_il_resolver_differisce_dalla_regola_VECCHIA_SOLO_sui_non_finiti():
    """L'equivalenza dimostrata invece che asserita: si ricalcola a mano la regola
    precedente su tutta la matrice e si verifica che l'unica differenza siano i
    valori NON FINITI — cioè esattamente il fix, e nient'altro."""
    def regola_vecchia(v):
        s = str(v if v is not None else "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    non_finiti = {"inf", "-inf", "nan", INFINITO_DI_SOLE_CIFRE, "-" + INFINITO_DI_SOLE_CIFRE}
    matrice = ["1e-05", "1E-05", "-1e-05", "1,5", "1.5", "-0,5", "+2.5", "0", "", None,
               "abc", "  1.5  ", 1e-05, 0.5, 3, *non_finiti]

    for caso in matrice:
        nuovo, vecchio = dictionary_resolver._hcap_value(caso), regola_vecchia(caso)
        if caso in non_finiti:
            assert nuovo is None, f"{caso!r} doveva essere scartato, ha dato {nuovo!r}"
            assert vecchio is not None, f"{caso!r} doveva passare con la regola vecchia"
        else:
            assert repr(nuovo) == repr(vecchio), \
                f"{caso!r}: la regola e' cambiata dove non doveva (era {vecchio!r}, ora {nuovo!r})"


def test_end_to_end_multiriga_un_handicap_fuori_scala_blocca_base_E_derivate():
    """Non il predicato isolato, ma il percorso reale: un parser MultiSelection il cui
    override `handicap` è fuori scala non deve produrre NESSUNA riga piazzabile.

    È il test che il rilievo di GPT-5.5 chiedeva, e chiude il buco che la regola 2 ha
    fatto emergere: il gate della riga derivata era una SECONDA copia, e con la sola
    correzione della base il fuori-scala sarebbe passato proprio da qui.
    """
    from xtrader_bridge import custom_parser as cp

    def parser_con_handicap(valore_handicap):
        regole = [
            cp.FieldRule(target="Provider", fixed_value="PBet"),
            cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
            cp.FieldRule(target="Price", fixed_value="1.50", required=True),
            cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        ]
        defn = cp.CustomParserDef(name="MS", mode="NAME_ONLY", rules=regole)
        defn.multi_selection_enabled = True
        defn.multi_selections = [
            cp.MultiRowRule(selection_name="1 - 0", handicap=valore_handicap),
            cp.MultiRowRule(selection_name="2 - 1", handicap=valore_handicap),
        ]
        return defn

    testo = "P.Bet.\n🆚Al-Kholood Club v Al-Hilal\n"

    # Controprova PRIMA: con un handicap legittimo il parser produce righe piazzabili —
    # altrimenti il test sotto passerebbe per il motivo sbagliato (parser rotto).
    ok = custom_pipeline.build_validated_rows(parser_con_handicap("-1,5"), testo)
    assert ok, "il parser di controllo non ha prodotto righe: il test non proverebbe nulla"
    assert all(r.status == validator.VALID for r in ok), [r.status for r in ok]
    assert all(r.row["Handicap"] in ("-1.5", "-1,5") for r in ok), [r.row["Handicap"] for r in ok]

    # Fuori scala: NESSUNA riga piazzabile, su OGNI riga derivata.
    for fuori_scala in ("1000.01", "-1000.01", INFINITO_DI_SOLE_CIFRE):
        esiti = custom_pipeline.build_validated_rows(parser_con_handicap(fuori_scala), testo)
        assert esiti, "attese righe con esito, non una lista vuota"
        assert all(r.status == custom_pipeline.INVALID_HANDICAP for r in esiti), \
            f"{fuori_scala!r} → {[r.status for r in esiti]}"


# ══════════════════════════════════════════════════════════════════════════════════
# Major di CodeRabbit sulla #202 — e una REGRESSIONE introdotta da questa stessa PR.
#
# `_hcap_value` fail-closed non basta: `_match_selection` converte il suo `None` in
# `0.0`, quindi il fail-closed veniva ANNULLATO dal chiamante. Misurato:
#
#   handicap della riga     PRIMA (86a8a89)   DOPO il primo commit di questa PR
#   "9"*400                 None (nessun match)   '22'  ← SelectionId della LINEA 0
#
# Prima l'infinito confrontava `inf == 0.0` → False → nessun match. Rendendolo `None`
# è diventato `0.0`, cioè ha iniziato a combaciare con la selezione a handicap zero.
# Un handicap "abc" lo faceva GIÀ prima (difetto preesistente, stessa classe).
#
# Distinzione corretta: handicap ASSENTE → 0.0 (default di contratto: Match Odds e le
# selezioni senza linea); handicap VALORIZZATO ma non confrontabile → nessun match.
# ══════════════════════════════════════════════════════════════════════════════════

class _DizionarioFinto:
    """Dizionario con UNA selezione reale a handicap 0 (il caso Match Odds)."""

    def __init__(self, handicap_selezione="0"):
        self._h = handicap_selezione

    def get_selections(self, market_id):
        return [{"runner_name": "Inter", "selection_id": "22",
                 "handicap": self._h, "active": 1}]


def _resolver(handicap_selezione="0"):
    # Costruttore REALE, non `__new__`: la classe documenta `db` come seam di iniezione per i
    # test, e bypassare `__init__` significherebbe esercitare un oggetto costruito diversamente
    # da come lo costruisce la produzione (rilievo Fable 5 su #202).
    from xtrader_bridge.betfair.dictionary_resolver import DictionaryResolver
    return DictionaryResolver(_DizionarioFinto(handicap_selezione))


@pytest.mark.parametrize("handicap_riga", [
    INFINITO_DI_SOLE_CIFRE,          # la regressione introdotta da questa PR
    "-" + INFINITO_DI_SOLE_CIFRE,
    "abc",                           # difetto PREESISTENTE della stessa classe
    "1.2.3",
    "inf",
    "nan",
])
def test_un_handicap_NON_confrontabile_non_combacia_con_la_linea_zero(handicap_riga):
    """Il fail-closed deve arrivare fino alla decisione, non fermarsi al parsing.

    Se combaciasse, il `SelectionId` della linea 0 finirebbe nel CSV per un segnale la
    cui linea non si sa quale sia: XTrader piazzerebbe sulla selezione sbagliata.
    """
    assert _resolver()._match_selection("1.234", "Inter", handicap_riga) is None


@pytest.mark.parametrize("handicap_riga", [None, "", "   "])
def test_un_handicap_ASSENTE_resta_la_linea_zero(handicap_riga):
    """Controprova: l'assenza NON è un errore. È il default del contratto e deve
    continuare a combaciare, o Match Odds e tutte le selezioni senza linea
    smetterebbero di risolvere gli ID."""
    assert _resolver()._match_selection("1.234", "Inter", handicap_riga) == "22"


def test_le_linee_reali_continuano_a_combaciare_e_a_NON_combaciare():
    assert _resolver("0")._match_selection("1.234", "Inter", "0") == "22"
    assert _resolver("0")._match_selection("1.234", "Inter", "0,0") == "22"
    assert _resolver("-1.5")._match_selection("1.234", "Inter", "-1,5") == "22"
    # Linea diversa → nessun ID (l'invariante Codex P1: mai l'ID di un'altra linea).
    assert _resolver("0")._match_selection("1.234", "Inter", "1.5") is None
    assert _resolver("1.5")._match_selection("1.234", "Inter", "0") is None


def test_una_voce_di_DIZIONARIO_malformata_non_vale_come_linea_zero():
    """L'altro lato del confronto: una riga di dizionario con handicap illeggibile non
    deve essere trattata come se fosse a linea 0, o si aggancerebbe a un segnale
    legittimo senza handicap."""
    assert _resolver("abc")._match_selection("1.234", "Inter", "0") is None
    assert _resolver(INFINITO_DI_SOLE_CIFRE)._match_selection("1.234", "Inter", "0") is None
    # Ma una voce di dizionario VUOTA resta la linea 0 (default di contratto).
    assert _resolver("")._match_selection("1.234", "Inter", "0") == "22"
