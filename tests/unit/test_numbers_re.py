"""Test del frammento regex decimale condiviso (audit L4): `numbers_re` è la fonte unica
usata da parser/validator/custom_pipeline/csv_writer. Qui si verifica che i frammenti
matchino i casi attesi e che i consumer continuino a usarli (anti-drift)."""

import re

from xtrader_bridge import csv_writer, custom_pipeline, numbers_re, parser, validator


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
    # Consumer Handicap reale (custom_pipeline._HANDICAP_RE, gate a custom_pipeline.py:302/518):
    # anche l'Handicap deve rifiutare le cifre non-ASCII (segno + cifre non-ASCII incluso).
    assert not custom_pipeline._HANDICAP_RE.match("١٩")
    assert not custom_pipeline._HANDICAP_RE.match("-١٩")
    assert custom_pipeline._HANDICAP_RE.match("-1") and custom_pipeline._HANDICAP_RE.match("+1,5")


def test_consumer_usano_il_frammento_condiviso():
    # I quattro moduli compongono il frammento unico (fonte unica, anti-drift): se uno
    # divergesse, questi pattern non corrisponderebbero più al frammento.
    assert numbers_re.DECIMAL in parser._NUM
    assert numbers_re.DECIMAL in validator._DECIMAL_PRICE.pattern
    assert numbers_re.SIGNED_DECIMAL in custom_pipeline._HANDICAP_RE.pattern
    assert numbers_re.SIGNED_DECIMAL in csv_writer._NUMERIC_RE.pattern
