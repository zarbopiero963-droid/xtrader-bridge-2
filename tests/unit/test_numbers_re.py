"""Test del frammento regex decimale condiviso (audit L4): `numbers_re` è la fonte unica
usata da validator/custom_pipeline/csv_writer (il consumer `parser` è stato rimosso, P3-15 #76). Qui si verifica che i frammenti
matchino i casi attesi e che i consumer continuino a usarli (anti-drift)."""

import re

from xtrader_bridge import csv_writer, custom_pipeline, numbers_re, validator


def test_decimal_match_atteso():
    rx = re.compile(r"^" + numbers_re.DECIMAL + r"$")
    assert rx.fullmatch("1")
    assert rx.fullmatch("1.85")
    assert rx.fullmatch("0,5")
    assert not rx.fullmatch("1.2.3")     # niente doppio separatore
    assert not rx.fullmatch("-1")        # DECIMAL è senza segno
    assert not rx.fullmatch("1e2")       # niente esponenti


def test_signed_decimal_accetta_il_segno():
    rx = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$")
    assert rx.fullmatch("-1")
    assert rx.fullmatch("+1,5")
    assert rx.fullmatch("1.85")
    assert not rx.fullmatch("--1")


def test_decimal_rifiuta_cifre_non_ascii():
    # #318 L2-1 (fail-OPEN): `\d` in Python matcha le cifre Unicode (arabo-indiane,
    # devanagari, fullwidth). Un valore come «١٩» superava DECIMAL/SIGNED_DECIMAL e,
    # poiché float("١٩")==19.0, veniva accettato come numero valido ed entrava nel CSV.
    # Il frammento condiviso DEVE accettare SOLO cifre ASCII [0-9]. Regressione bloccata.
    dec = re.compile(r"^" + numbers_re.DECIMAL + r"$")
    sdec = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$")
    for bad in ("١٩", "٥", "१९", "５", "1٩", "1۵5"):   # arabo, devanagari, fullwidth, misti
        assert not dec.fullmatch(bad), f"DECIMAL non deve matchare {bad!r}"
        assert not sdec.fullmatch(bad), f"SIGNED_DECIMAL non deve matchare {bad!r}"
    # Controprova: le cifre ASCII (con ,/. e segno) restano valide.
    assert dec.fullmatch("19") and dec.fullmatch("1,85") and dec.fullmatch("2.10")
    assert sdec.fullmatch("-1") and sdec.fullmatch("+1,5")
    # Consumer Handicap reale. Da B5 (#194) il gate NON è più una regex in `custom_pipeline`
    # (ce n'erano due copie) ma `validator.handicap_status`, condiviso da entrambi i gate del
    # pipeline e da `validator.validate`. Si asserisce quindi il GATE, non il pattern: è ciò
    # che decide davvero se una riga raggiunge il CSV, e resta vero anche se un domani il
    # gate smettesse di essere implementato con una regex.
    for bad in ("١٩", "-١٩", "１９"):
        assert validator.handicap_status(bad) == validator.INVALID_HANDICAP, bad
    assert validator.handicap_status("-1") == validator.VALID
    assert validator.handicap_status("+1,5") == validator.VALID
    # E il gate del pipeline è LO STESSO (nessuna seconda implementazione che possa divergere).
    assert custom_pipeline._handicap_bloccante({"Handicap": "١٩"}) is True
    assert custom_pipeline._handicap_bloccante({"Handicap": "-1"}) is False


def test_consumer_usano_il_frammento_condiviso():
    # I tre moduli compongono il frammento unico (fonte unica, anti-drift): se uno
    # divergesse, questi pattern non corrisponderebbero più al frammento.
    # (P3-15 #76: il quarto consumer, `parser._NUM`, è stato rimosso col modulo P.Bet.)
    assert numbers_re.DECIMAL in validator._DECIMAL_PRICE.pattern
    # Il consumer Handicap è passato da `custom_pipeline._HANDICAP_RE` a
    # `validator._SIGNED_DECIMAL_RE` (B5 #194: le due copie del gate sono diventate una).
    assert numbers_re.SIGNED_DECIMAL in validator._SIGNED_DECIMAL_RE.pattern
    assert numbers_re.SIGNED_DECIMAL in csv_writer._NUMERIC_RE.pattern


def test_i_frammenti_sono_componibili_con_le_ancore():
    """I frammenti devono essere sicuri da comporre come `r"^" + FRAMMENTO + r"$"`, che è
    esattamente come li usano i loro consumer (rilievo Fable 5 + GPT-5.5 su #198).

    Il rischio non è teorico: se un frammento contenesse un'alternanza `|` di primo livello,
    le ancore si legherebbero a UN SOLO ramo e `^[+-]?[0-9]+…|INF$` accetterebbe «12abc» —
    un Price/Handicap spurio che supera la validazione ed entra nel CSV letto da XTrader.
    Fail-OPEN silenzioso, la stessa famiglia di #318 L2-1.

    Per questo i frammenti sono racchiusi in un gruppo non catturante. Questo test lo verifica
    dal COMPORTAMENTO, non dalla forma: se qualcuno togliesse il gruppo e aggiungesse un ramo,
    diventerebbe rosso.
    """
    for frammento in (numbers_re.DECIMAL, numbers_re.SIGNED_DECIMAL):
        ancorato = re.compile(r"^" + frammento + r"$")
        for spurio in ("12abc", "abc12", "1 2", "1.2.3", "--1", "1,"):
            assert not ancorato.match(spurio), (
                f"{spurio!r} accettato: il frammento {frammento!r} non è sicuro da ancorare. "
                "Se hai aggiunto un'alternanza, racchiudila in `(?:…)`, altrimenti le ancore "
                "si legano a un solo ramo e la validazione diventa fail-OPEN.")

    # e il gruppo non deve catturare: aggiungerne uno catturante sposterebbe la numerazione
    # dei gruppi in ogni consumer che usa `.group(n)` o riferimenti `\1`.
    assert re.compile(numbers_re.SIGNED_DECIMAL).groups == 0
    assert re.compile(numbers_re.DECIMAL).groups == 0
