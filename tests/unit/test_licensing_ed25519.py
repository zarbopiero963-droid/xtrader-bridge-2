"""Test hard dell'Ed25519 pure-Python (#140 PR 1).

Blindaggio della correttezza crittografica coi **vettori di test ufficiali RFC 8032 §7.1**
(non ci si fida dell'implementazione: la si confronta col riferimento canonico), più round-trip
e fail-closed su input malformati.
"""

import os

import pytest

from xtrader_bridge.licensing import ed25519


# Vettori ufficiali RFC 8032 §7.1 (Ed25519). (seed, pubkey, msg, signature) in hex.
_RFC_VECTORS = [
    # TEST 2 (1 byte di messaggio)
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    # TEST 3 (2 byte di messaggio)
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("seed_hex,pub_hex,msg_hex,sig_hex", _RFC_VECTORS)
def test_rfc8032_public_key(seed_hex, pub_hex, msg_hex, sig_hex):
    assert ed25519.public_key(bytes.fromhex(seed_hex)).hex() == pub_hex


@pytest.mark.parametrize("seed_hex,pub_hex,msg_hex,sig_hex", _RFC_VECTORS)
def test_rfc8032_sign_matches_vector(seed_hex, pub_hex, msg_hex, sig_hex):
    sig = ed25519.sign(bytes.fromhex(seed_hex), bytes.fromhex(msg_hex))
    assert sig.hex() == sig_hex


@pytest.mark.parametrize("seed_hex,pub_hex,msg_hex,sig_hex", _RFC_VECTORS)
def test_rfc8032_verify_accepts_vector(seed_hex, pub_hex, msg_hex, sig_hex):
    assert ed25519.verify(bytes.fromhex(pub_hex), bytes.fromhex(msg_hex),
                          bytes.fromhex(sig_hex)) is True


def test_rfc8032_verify_empty_message_vector():
    # TEST 1 (messaggio vuoto): vettore verify-only (pubkey + firma canoniche).
    pub = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a3"
        "3bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert ed25519.verify(pub, b"", sig) is True


def test_verify_rejects_tampered_message():
    seed = bytes.fromhex(_RFC_VECTORS[0][0])
    pub = ed25519.public_key(seed)
    sig = ed25519.sign(seed, b"messaggio originale")
    assert ed25519.verify(pub, b"messaggio ALTERATO", sig) is False


def test_verify_rejects_tampered_signature():
    seed = bytes.fromhex(_RFC_VECTORS[0][0])
    pub = ed25519.public_key(seed)
    msg = b"ciao"
    sig = bytearray(ed25519.sign(seed, msg))
    sig[0] ^= 0x01
    assert ed25519.verify(pub, msg, bytes(sig)) is False


def test_verify_rejects_wrong_key():
    seed_a = bytes.fromhex(_RFC_VECTORS[0][0])
    pub_b = ed25519.public_key(bytes.fromhex(_RFC_VECTORS[1][0]))
    sig_a = ed25519.sign(seed_a, b"x")
    assert ed25519.verify(pub_b, b"x", sig_a) is False


@pytest.mark.parametrize("pub,msg,sig", [
    (b"troppo-corta", b"m", bytes(64)),        # pubkey lunghezza errata
    (bytes(32), b"m", b"firma-corta"),         # firma lunghezza errata
    (bytes(32), b"m", bytes(64)),              # pubkey non decomprimibile a un punto valido
])
def test_verify_fail_closed_su_input_malformato(pub, msg, sig):
    # Fail-closed: nessuna eccezione, sempre False.
    assert ed25519.verify(pub, msg, sig) is False


def test_sign_verify_round_trip_random():
    # Consistenza interna su chiavi/messaggi casuali: accetta il valido, rifiuta i tamper.
    for _ in range(50):
        seed = os.urandom(32)
        pub = ed25519.public_key(seed)
        msg = os.urandom(24)
        sig = ed25519.sign(seed, msg)
        assert ed25519.verify(pub, msg, sig) is True
        flipped = bytearray(msg) or bytearray(b"\x00")
        flipped[0] ^= 0x01
        assert ed25519.verify(pub, bytes(flipped), sig) is False


def test_sign_rejects_bad_seed_length():
    with pytest.raises(ValueError):
        ed25519.sign(b"seed-corto", b"m")
