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
