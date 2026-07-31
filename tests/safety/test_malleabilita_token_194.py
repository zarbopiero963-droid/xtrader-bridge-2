"""Malleabilità del token licenza e revoca aggirabile — PR-C del piano #194 (B2).

Il buco, misurato prima della patch: aggiungere **un solo carattere** `=` in fondo a un token
lo lascia `VALID`, ma ne cambia il **serial** — e il serial è ciò con cui la lista di revoche
identifica una licenza. Un cliente revocato riattiva la propria licenza con un'operazione che
non richiede alcuna conoscenza tecnica.

```
onesto         valid=True   serial=LIC-598B9916DE34
token + '='    valid=True   serial=LIC-5EC5A2983E9B   ← la revoca non lo intercetta
token + '=='   valid=True   serial=LIC-562442A20C74
```

La causa è in `_b64u_decode`, che **aggiunge** il padding (`pad = "=" * (-len(text) % 4)`):
con un `=` in più la lunghezza torna valida e base64 accetta. Per la stessa ragione
`validate=True` **non** chiude il buco (misurato nella #194): `=` è padding legittimo, non un
carattere fuori alfabeto.

La correzione è un **controllo di canonicità per round-trip**: si decodifica e si ri-codifica,
e si pretende di riottenere la stringa identica. Chiude il buco **senza toccare un solo serial
esistente** — che è il vincolo decisivo, perché canonicalizzare il serial avrebbe riattivato in
silenzio **tutti** i clienti già revocati (misurato nella #194: il serial cambia anche per un
token del tutto onesto).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from license_manager import core, registry                      # noqa: E402
from xtrader_bridge.licensing import license as lic             # noqa: E402
from xtrader_bridge.licensing import revocation, revocation_client  # noqa: E402

HW = "HW-DEL-CLIENTE"
NOW = 1_700_000_000
DOPO = NOW + 100


@pytest.fixture(scope="module")
def coppia():
    """Una keypair throwaway e un token onesto emessi dal codice di produzione reale."""
    seed_hex, public_hex = core.generate_keypair()
    token = core.issue_license(seed_hex, "Mario Rossi", 30, HW, NOW)
    return seed_hex, public_hex, token


# ────────────────────────── B2 · il token malleato non è più valido ──────────────────────────

@pytest.mark.parametrize("coda", ["=", "==", "==="])
def test_il_token_con_padding_aggiunto_e_rifiutato(coppia, coda):
    """Il cuore di B2. Prima della patch tutte e tre le forme uscivano `valid=True`."""
    _seed, public_hex, token = coppia
    stato = lic.verify_license(token + coda, HW, DOPO, public_key_hex=public_hex)
    assert stato.valid is False, f"token + {coda!r} deve essere rifiutato"
    assert stato.reason == lic.MALFORMED


def test_il_padding_aggiunto_al_solo_payload_e_rifiutato(coppia):
    """La malleabilità non è solo in coda: anche una sola delle due parti basta a cambiare il
    serial lasciando la firma verificabile."""
    _seed, public_hex, token = coppia
    parte_payload, parte_firma = token.split(".", 1)
    manomesso = parte_payload + "=." + parte_firma
    stato = lic.verify_license(manomesso, HW, DOPO, public_key_hex=public_hex)
    assert stato.valid is False and stato.reason == lic.MALFORMED


# ─────────────────── le controprove: la patch non deve rompere il caso onesto ───────────────────

def test_il_token_onesto_resta_valido(coppia):
    """Controprova simmetrica, richiesta esplicitamente dal piano #194: senza di essa una patch
    che rifiuta *tutto* passerebbe il test precedente e bloccherebbe ogni cliente."""
    _seed, public_hex, token = coppia
    stato = lic.verify_license(token, HW, DOPO, public_key_hex=public_hex)
    assert stato.valid is True, f"il token onesto deve restare valido (motivo: {stato.reason})"
    assert stato.name == "Mario Rossi"


def test_il_serial_del_token_onesto_non_cambia(coppia):
    """**Il vincolo che ha dato forma a questa PR.** La direzione di correzione inizialmente
    indicata nella #192 era «calcolare il serial sui byte decodificati». Misurato nella #194,
    quel serial cambia **anche per un token onesto**: poiché `licenses.jsonl`, `revoked.jsonl` e
    ogni lista di revoche già pubblicata contengono i serial nella forma attuale, ogni revoca
    esistente avrebbe smesso di corrispondere — **tutti i clienti revocati sarebbero tornati
    attivi, in silenzio**.

    Questo test fissa che la correzione non tocchi il serial.
    """
    _seed, _public, token = coppia
    assert lic.license_serial(token) == registry.license_serial(token)
    # Il serial è funzione della sola stringa del token: se qualcuno cambiasse `license_serial`
    # questo valore cambierebbe e il test diventerebbe rosso invece di annullare le revoche.
    atteso = lic._SERIAL_PREFIX + __import__("hashlib").sha256(
        token.encode("utf-8")).hexdigest()[:lic._SERIAL_HEX_LEN].upper()
    assert lic.license_serial(token) == atteso


def test_un_token_noto_ha_un_serial_letterale_fisso():
    """Àncora di regressione con un **valore letterale**, come chiede il piano: se un domani
    `license_serial` venisse canonicalizzato, questo test diventa rosso **subito**, invece di
    riattivare in silenzio ogni cliente revocato."""
    assert lic.license_serial("token-di-prova.firma-di-prova") == "LIC-14BC922B87A1"


# ───────────────────── la revoca non è più aggirabile (misura end-to-end) ─────────────────────

def test_la_revoca_non_si_aggira_col_padding(coppia):
    """Lo scenario reale del bug, dal lato che conta: il cliente revocato **non** riattiva la
    licenza aggiungendo un `=`. Ora il token malleato non è nemmeno valido, quindi non arriva
    neppure al gate revoca."""
    seed_hex, public_hex, token = coppia
    entries = registry.revocation_entries([{"serial": lic.license_serial(token),
                                            "hardware_id": HW}])
    firmata = revocation.build_revocation_list(bytes.fromhex(seed_hex), entries, now=DOPO)
    lista = revocation.verify_revocation_list(firmata, public_key_hex=public_hex)

    assert revocation_client.license_revoked(lista, token=token, hardware_id=HW) is True
    # e il malleato non passa più dalla porta principale:
    assert lic.verify_license(token + "=", HW, DOPO, public_key_hex=public_hex).valid is False


# ──────────────── la revoca per hardware è OPZIONALE (decisione del proprietario) ────────────────

def test_di_default_la_revoca_non_blacklista_la_macchina(coppia):
    """Decisione del proprietario, presa misurando: emettere `hw` in **ogni** revoca renderebbe la
    revoca **irreversibile** — un cliente revocato che poi RICOMPRA resterebbe bloccato, perché il
    serial cambia ma la macchina no.

    Il default resta quindi «solo serial», coerente col docstring di `revocation_entries` che
    dichiara la revoca reversibile. Questo test fissa la reversibilità.
    """
    seed_hex, public_hex, vecchio = coppia
    nuovo = core.issue_license(seed_hex, "Mario Rossi", 365, HW, NOW + 500_000)
    assert lic.license_serial(vecchio) != lic.license_serial(nuovo)

    entries = registry.revocation_entries([{"serial": lic.license_serial(vecchio),
                                            "hardware_id": HW}])
    assert entries == [{"serial": lic.license_serial(vecchio)}], \
        "di default nessun `hw`: la macchina non va in blacklist"

    firmata = revocation.build_revocation_list(bytes.fromhex(seed_hex), entries, now=DOPO)
    lista = revocation.verify_revocation_list(firmata, public_key_hex=public_hex)
    assert revocation_client.license_revoked(lista, token=vecchio, hardware_id=HW) is True
    assert revocation_client.license_revoked(lista, token=nuovo, hardware_id=HW) is False, \
        "un cliente che RICOMPRA sulla stessa macchina non deve restare bloccato"


def test_la_blacklist_macchina_si_puo_chiedere_esplicitamente(coppia):
    """Quando il proprietario la chiede davvero, l'entry porta anche `hw` — ed è l'unica difesa
    che funziona su un bridge **non aggiornato**, dove il token malleato è ancora accettato."""
    seed_hex, public_hex, vecchio = coppia
    entries = registry.revocation_entries([{"serial": lic.license_serial(vecchio),
                                            "hardware_id": HW, "blacklist_hw": True}])
    assert entries == [{"serial": lic.license_serial(vecchio), "hw": HW}]

    firmata = revocation.build_revocation_list(bytes.fromhex(seed_hex), entries, now=DOPO)
    lista = revocation.verify_revocation_list(firmata, public_key_hex=public_hex)
    # Con la macchina in blacklist anche un token malleato (che un bridge vecchio accetterebbe)
    # viene bloccato dal gate revoca, perché l'Hardware ID non cambia.
    assert revocation_client.license_revoked(lista, token=vecchio + "=", hardware_id=HW) is True


def test_blacklist_senza_hardware_id_non_produce_entry_vuota(coppia):
    """Fail-safe: chiedere la blacklist su un record **senza** hardware id non deve produrre una
    entry `hw` vuota — che `normalize_entries` scarterebbe, ma è meglio non generarla affatto."""
    _seed, _public, token = coppia
    entries = registry.revocation_entries([{"serial": lic.license_serial(token),
                                            "hardware_id": "", "blacklist_hw": True}])
    assert entries == [{"serial": lic.license_serial(token)}]


def test_i_record_di_revoca_gia_su_disco_non_cambiano_comportamento(coppia):
    """Retro-compatibilità: i record già in `revoked.jsonl` non hanno il campo `blacklist_hw`.
    Devono continuare a produrre esattamente ciò che producevano — nessuna macchina finisce in
    blacklist a sorpresa dopo l'aggiornamento."""
    _seed, _public, token = coppia
    vecchio_record = {"serial": lic.license_serial(token), "name": "Mario Rossi",
                      "hardware_id": HW, "revoked_at": NOW}
    assert registry.revocation_entries([vecchio_record]) == [{"serial": lic.license_serial(token)}]


# ────────────────────────────── B44 · il test flaky del serial ──────────────────────────────

def test_il_formato_del_serial_regge_anche_a_sole_cifre():
    """B44 — difetto **del test**, non del prodotto.

    `str.isupper()` è `False` quando la stringa non contiene alcun carattere con
    maiuscola/minuscola. Il serial è `LIC-` + 12 esadecimali: quando quei 12 caratteri sono
    **tutte cifre**, l'assert `s[4:].isupper()` falliva. Misurato: **730 su 200.000 = 0,365%**,
    contro un atteso teorico di `(10/16)^12 = 0,355%`.

    Qui il caso è riprodotto in modo **deterministico** invece che sperando nel campione giusto.
    """
    assert "123456789012".isupper() is False, "la premessa del bug (se cade, il test non serve più)"

    for serial in ("LIC-450053341610", "LIC-123456789012", "LIC-ABCDEF123456"):
        coda = serial[4:]
        assert coda.isalnum() and coda == coda.upper(), \
            f"{serial}: il controllo di formato non deve dipendere dalla presenza di lettere"
