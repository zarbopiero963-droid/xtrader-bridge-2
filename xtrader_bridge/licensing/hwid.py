"""Hardware ID — impronta **stabile e offline** della macchina, per legare una licenza al PC.

Obiettivo (issue #140): dare all'utente una stringa breve da comunicare al proprietario; la
licenza firmata vale **solo** su quella macchina. Nessuna rete, nessuna dipendenza esterna.

Design testabile:
- `fingerprint(parts)` è **puro** (hash + formattazione deterministici): i test lo esercitano con
  componenti iniettati, senza dipendere dall'hardware reale;
- `components()` raccoglie le sorgenti reali **best-effort** (ognuna in `try`, fail-safe): su
  Windows il `MachineGuid` del registro e il seriale del volume di sistema (le più stabili),
  più il MAC come fallback multipiattaforma. Se una sorgente non è disponibile viene semplicemente
  omessa: l'impronta resta stabile sulla stessa macchina.

Nota onesta: nessuna impronta client è perfetta (reinstallazioni/cambi hardware la cambiano; una
VM può clonarla). È adeguata al modello di minaccia «scoraggiare la condivisione casuale», non a
fermare un attaccante determinato.
"""

from __future__ import annotations

import hashlib
import sys
import uuid

# Versione dello schema di impronta: se un giorno cambiamo le sorgenti/formato, il prefisso rende
# le vecchie e nuove impronte distinguibili (una licenza vecchia non "combacia per caso").
_HW_VERSION = "HW1"


def _mac_component() -> "str | None":
    """MAC address via `uuid.getnode()`. Omesso se è un valore casuale (nessuna NIC reale):
    `getnode()` segnala questo caso col bit multicast (bit 40) impostato."""
    try:
        node = uuid.getnode()
        if (node >> 40) & 1:      # bit multicast: valore casuale, non un MAC hardware reale
            return None
        return f"mac={node:012x}"
    except Exception:             # noqa: BLE001 — sorgente best-effort: assente = omessa
        return None


def _windows_machine_guid() -> "str | None":
    """`MachineGuid` dal registro di Windows: identificatore stabile dell'installazione."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg  # noqa: PLC0415 — import locale: modulo solo-Windows
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        guid = str(guid).strip()
        return f"mguid={guid}" if guid else None
    except Exception:             # noqa: BLE001 — assente/non leggibile = omesso
        return None


def _windows_volume_serial() -> "str | None":
    """Seriale del volume dell'unità di sistema (Windows): stabile finché il disco non è
    riformattato. Letto via `GetVolumeInformationW` (ctypes), senza dipendenze."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes  # noqa: PLC0415 — import locale
        import os  # noqa: PLC0415
        root = os.environ.get("SystemDrive", "C:") + "\\"
        serial = ctypes.c_uint(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0,
            ctypes.byref(serial), None, None, None, 0)
        if not ok:
            return None
        return f"vol={serial.value:08x}"
    except Exception:             # noqa: BLE001 — assente = omesso
        return None


def components() -> list:
    """Sorgenti reali dell'impronta, in ordine stabile. Ognuna best-effort (può mancare).

    L'ordine è fisso così l'impronta è deterministica sulla stessa macchina. Sorgenti assenti
    vengono omesse senza rompere le altre.
    """
    parts = []
    for src in (_windows_machine_guid(), _windows_volume_serial(), _mac_component()):
        if src:
            parts.append(src)
    return parts


def fingerprint(parts) -> str:
    """Funzione **pura**: dai componenti a una stringa d'impronta breve e stabile.

    Formato: ``HW1-XXXX-XXXX-XXXX-XXXX`` (16 hex maiuscoli da SHA-256, a gruppi di 4). Se
    `parts` è vuoto (nessuna sorgente disponibile) resta comunque una stringa valida ma marcata
    ``HW1-0000-…`` derivata da un seme costante, così il chiamante può accorgersene.
    """
    joined = "|".join(str(p) for p in parts) if parts else "no-hardware-sources"
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest().upper()
    block = digest[:16]
    grouped = "-".join(block[i:i + 4] for i in range(0, 16, 4))
    return f"{_HW_VERSION}-{grouped}"


def hardware_id() -> str:
    """Impronta hardware corrente della macchina (deterministica sullo stesso PC)."""
    return fingerprint(components())
