"""Ed25519 firma/verifica — implementazione **pure-Python** (nessuna dipendenza esterna).

Perché pure-Python invece di `cryptography`/`pynacl`:

- Il bridge deve **solo VERIFICARE** le licenze con una **chiave pubblica** committata; non
  firma nulla (la firma con la chiave privata vive nel License Manager del proprietario, PR3).
- Trascinare `cryptography` (Rust) o `pynacl` (libsodium C) complicherebbe la build Windows
  (PyInstaller **e** Nuitka) e il lockfile riproducibile, per un guadagno nullo lato bridge.
- Ed25519 è deterministico e verificabile contro i **vettori di test ufficiali RFC 8032**
  (vedi `tests/unit/test_licensing_ed25519.py`): non si "inventa" un algoritmo, si riproduce
  fedelmente il riferimento e lo si blinda coi vettori canonici.

Modello di minaccia (issue #140): scoraggiare la condivisione/rivendita casuale, **non** fermare
un cracker esperto. Una verifica Ed25519 corretta (chiave privata mai distribuita) è più che
adeguata a questo scopo.

Riferimento: RFC 8032 (Edwards-Curve Digital Signature Algorithm), Appendice A — versione a
coordinate estese. `sign()` è incluso per i test round-trip e per il License Manager; il bridge
usa **solo** `verify()`.
"""

from __future__ import annotations

import hashlib

# ── Parametri della curva edwards25519 (RFC 8032 §5.1) ──────────────────────────────────────
_P = 2 ** 255 - 19                                        # campo primo
_L = 2 ** 252 + 27742317777372353535851937790883648493   # ordine del sottogruppo
_D = (-121665 * pow(121666, _P - 2, _P)) % _P             # coefficiente della curva
_I = pow(2, (_P - 1) // 4, _P)                            # sqrt(-1) mod p


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little")


def _inv(x: int) -> int:
    """Inverso moltiplicativo modulo p (piccolo teorema di Fermat)."""
    return pow(x, _P - 2, _P)


def _x_recover(y: int) -> int:
    """Ricostruisce la coordinata x dalla y (decompressione del punto)."""
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


# Punto base B in coordinate estese (X, Y, Z, T) con Z=1, T=X*Y.
_BY = (4 * _inv(5)) % _P
_BX = _x_recover(_BY) % _P
_B = (_BX, _BY, 1, (_BX * _BY) % _P)

# Punto identità (neutro) in coordinate estese.
_IDENT = (0, 1, 1, 0)


def _point_add(pt1, pt2):
    """Addizione di punti in coordinate estese (RFC 8032 §5.1.4)."""
    x1, y1, z1, t1 = pt1
    x2, y2, z2, t2 = pt2
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (t1 * 2 * _D * t2) % _P
    dd = (z1 * 2 * z2) % _P
    e = b - a
    f = dd - c
    g = dd + c
    h = b + a
    x3 = (e * f) % _P
    y3 = (g * h) % _P
    t3 = (e * h) % _P
    z3 = (f * g) % _P
    return (x3, y3, z3, t3)


def _scalar_mult(pt, e: int):
    """Moltiplicazione scalare (double-and-add), tempo ~costante sul numero di bit."""
    result = _IDENT
    while e > 0:
        if e & 1:
            result = _point_add(result, pt)
        pt = _point_add(pt, pt)
        e >>= 1
    return result


def _point_equal(pt1, pt2) -> bool:
    x1, y1, z1, _t1 = pt1
    x2, y2, z2, _t2 = pt2
    # x1/z1 == x2/z2  e  y1/z1 == y2/z2  (evita divisioni: prodotto incrociato).
    if (x1 * z2 - x2 * z1) % _P != 0:
        return False
    if (y1 * z2 - y2 * z1) % _P != 0:
        return False
    return True


def _point_compress(pt) -> bytes:
    """Codifica un punto in 32 byte (RFC 8032 §5.1.2)."""
    x, y, z, _t = pt
    zinv = _inv(z)
    x = (x * zinv) % _P
    y = (y * zinv) % _P
    return int(y | ((x & 1) << 255)).to_bytes(32, "little")


def _point_decompress(data: bytes):
    """Decodifica 32 byte in un punto; None se non è un punto valido sulla curva."""
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _x_recover(y)
    if x & 1 != sign:
        x = _P - x
    pt = (x, y, 1, (x * y) % _P)
    # Verifica che il punto sia effettivamente sulla curva.
    if not _on_curve(pt):
        return None
    return pt


def _on_curve(pt) -> bool:
    x, y, z, t = pt
    # -x^2 + y^2 = z^2 + d*t^2 , con t = x*y/z
    if (x * y - z * t) % _P != 0:
        return False
    lhs = (-x * x + y * y - z * z - _D * t * t) % _P
    return lhs == 0


def _secret_expand(secret: bytes):
    """Espande il seed privato (32 byte) → (scalare a, prefisso per la nonce)."""
    if len(secret) != 32:
        raise ValueError("il seed della chiave privata Ed25519 deve essere 32 byte")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8          # azzera i 3 bit bassi
    a |= (1 << 254)              # imposta il bit 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    """Deriva la chiave pubblica (32 byte) dal seed privato (32 byte)."""
    a, _prefix = _secret_expand(secret)
    return _point_compress(_scalar_mult(_B, a))


def sign(secret: bytes, msg: bytes) -> bytes:
    """Firma `msg` col seed privato (32 byte) → firma di 64 byte (RFC 8032 §5.1.6).

    Presente per i test round-trip e per il License Manager (PR3). Il bridge NON firma.
    """
    a, prefix = _secret_expand(secret)
    a_pub = _point_compress(_scalar_mult(_B, a))
    r = _sha512_int(prefix + msg) % _L
    rr = _point_compress(_scalar_mult(_B, r))
    k = _sha512_int(rr + a_pub + msg) % _L
    s = (r + k * a) % _L
    return rr + s.to_bytes(32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    """Verifica la firma di 64 byte su `msg` con la chiave pubblica di 32 byte.

    Ritorna `True` solo se la firma è valida; **fail-closed** su qualunque input malformato
    (lunghezze errate, punto non sulla curva, `s` fuori range) → `False`, mai eccezioni.
    """
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        a_point = _point_decompress(public)
        if a_point is None:
            return False
        rr = signature[:32]
        r_point = _point_decompress(rr)
        if r_point is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        k = _sha512_int(rr + public + msg) % _L
        # Controllo: [s]B == R + [k]A
        lhs = _scalar_mult(_B, s)
        rhs = _point_add(r_point, _scalar_mult(a_point, k))
        return _point_equal(lhs, rhs)
    except Exception:       # noqa: BLE001 — verifica fail-closed: qualunque errore = firma non valida
        return False
