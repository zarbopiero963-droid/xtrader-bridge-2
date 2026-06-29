#!/usr/bin/env python3
"""PoC Nuitka — smoke driver della logica CORE del bridge.

Scopo: dare una verifica *reale e automatica* che la catena di logica pura del
bridge (parser P.Bet. → normalizzazione quota → value-map) continui a produrre
lo stesso risultato quando il modulo non gira interpretato ma **compilato in C
nativo da Nuitka**. È il file che il workflow `nuitka-poc.yaml` compila ed esegue
su Windows, ed è anche riproducibile in locale (vedi `docs/nuitka_poc.md`).

NON tocca GUI, Telegram, CSV su disco o config: esercita solo funzioni pure, così
può girare headless sia interpretato sia compilato, senza display né rete.

Uso interpretato (dalla root del repo):
    python tools/nuitka_poc_core.py

Uso compilato (PoC vero):
    python -m nuitka --standalone --include-package=xtrader_bridge \
        tools/nuitka_poc_core.py
    ./nuitka_poc_core.dist/nuitka_poc_core.bin   # Windows: .exe

Exit code 0 + riga finale "PoC_OK" = la logica compilata si comporta come l'attesa.
Qualunque scostamento → AssertionError + exit code 1 (il PoC fallisce, come deve).
"""
import os
import sys

# Permette `python tools/nuitka_poc_core.py` dalla root senza PYTHONPATH.
# Sotto Nuitka il package è incluso con --include-package, quindi l'insert è innocuo.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from xtrader_bridge import value_maps  # noqa: E402
from xtrader_bridge.parser import parse_message  # noqa: E402

# Messaggio P.Bet. reale (stesso usato dai test di integrazione): include quota con
# la virgola (`1,85`), che il parser deve normalizzare in punto (`1.85`).
SAMPLE = "P.Bet. OVER 2.5 LIVE\nInter v Milan\nQuota 1,85"


def run_core_checks() -> dict:
    """Esegue la logica reale e ne verifica gli invarianti. Ritorna il parse."""
    parsed = parse_message(SAMPLE)

    # Invarianti hard: se la logica compilata diverge, il PoC fallisce.
    assert parsed["signal_type"] == "OVER 2.5", parsed["signal_type"]
    assert parsed["teams"] == "Inter v Milan", parsed["teams"]
    # Normalizzazione quota virgola→punto: è il classico bug "quota sbagliata".
    assert parsed["quota"] == "1.85", parsed["quota"]
    assert parsed["live"] is True, parsed["live"]

    # La registry delle value-map deve restare interrogabile dal binario compilato.
    available = value_maps.available_value_maps()
    assert isinstance(available, list), type(available)

    return parsed


def main() -> int:
    parsed = run_core_checks()
    print("PARSED signal_type =", parsed["signal_type"])
    print("PARSED quota       =", parsed["quota"], "(da '1,85' → punto)")
    print("PARSED live        =", parsed["live"])
    print("COMPILED           =", "__compiled__" in globals())  # True solo sotto Nuitka
    print("PoC_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
