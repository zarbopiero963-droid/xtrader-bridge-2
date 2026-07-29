"""Le quattro voci MINORI dell'audit #137, tracciate nella #176.

Nessuna tocca il percorso soldi: sono robustezza e coerenza. Ma una delle quattro era
etichettata «teorica» e alla misura non lo e' affatto — stesso schema del reset del
backoff marcato «cosmetico» che erano 60 secondi contro 2 (#173).
"""

import os

import pytest

from xtrader_bridge import atomic_io


def _fd_aperti():
    """Descrittori aperti dal processo. Su Linux `/proc/self/fd` e' la fonte diretta."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:                      # pragma: no cover — non-Linux
        pytest.skip("conteggio fd disponibile solo dove esiste /proc/self/fd")


def test_atomic_write_non_perde_descrittori_se_fdopen_solleva(tmp_path):
    """FAIL-FIRST — la voce «`atomic_io` fd-leak TEORICO» dell'audit, misurata.

    `mkstemp` restituisce un fd gia' APERTO; solo `os.fdopen` ne prende possesso. Se
    `fdopen` solleva (modo non valido), il fd resta orfano: il blocco d'errore rimuoveva
    il file temporaneo ma non chiudeva il descrittore.

    Misurato prima della correzione: 20 chiamate fallite → 20 fd persi. Non teorico."""
    percorso = str(tmp_path / "x.txt")
    prima = _fd_aperti()

    for _ in range(20):
        with pytest.raises(Exception):   # noqa: B017 — il TIPO non conta, conta il leak
            atomic_io.atomic_write(percorso, lambda f: f.write("x"), mode="qz")

    perdita = _fd_aperti() - prima
    assert perdita == 0, f"{perdita} descrittori persi su 20 chiamate fallite"


def test_atomic_write_non_lascia_il_file_temporaneo(tmp_path):
    """Contro-prova che rende non vacuo il test sopra: la pulizia gia' esistente del
    temporaneo deve restare. Se il fix chiudesse il fd ma smettesse di rimuovere il
    `.tmp`, questo diventa rosso."""
    percorso = str(tmp_path / "y.txt")
    with pytest.raises(Exception):       # noqa: B017
        atomic_io.atomic_write(percorso, lambda f: f.write("x"), mode="qz")

    residui = [n for n in os.listdir(tmp_path) if n != "y.txt"]
    assert residui == [], f"temporanei rimasti: {residui}"


def test_atomic_write_funziona_ancora(tmp_path):
    """Il caso felice: la correzione non deve rompere la scrittura normale."""
    percorso = str(tmp_path / "ok.txt")
    atomic_io.atomic_write(percorso, lambda f: f.write("ciao"))
    # `with`: un handle non chiuso in un test SUI DESCRITTORI PERSI sarebbe una beffa
    # (rilievo Fable 5), e falserebbe il conteggio se questo test girasse per primo.
    with open(percorso, encoding="utf-8") as f:
        assert f.read() == "ciao"


# ── config_agent_gui: guardia `(data or {})` mancante su un ramo ─────────────

def test_handle_event_regge_data_None_su_ogni_ramo():
    """`ConfigAgentController._emit` ha `data=None` come DEFAULT. Quattro rami della view
    usavano `(data or {})`, il ramo «state» no: con `data=None` sollevava `AttributeError`.

    Non sarebbe nemmeno crashato in modo visibile — il controller avvolge la chiamata alla
    view in un blind except, quindi l'errore veniva INGHIOTTITO e la view smetteva di
    aggiornarsi in silenzio. Un guasto muto e' peggio di uno rumoroso."""
    from xtrader_bridge import config_agent_gui

    a = object.__new__(config_agent_gui.AssistantPanel)
    visti = []
    a._refresh_state = lambda stato, errore: visti.append((stato, errore))

    config_agent_gui.AssistantPanel._handle_event(a, "state", None)

    assert visti == [(None, "")], visti
