"""Redesign UI PR-2 — migrazione colori di `name_mapping_gui.py` ai token `ui_theme`.

`name_mapping_gui.py` importa `customtkinter` a livello di modulo e **non è testabile
headless** (richiede un display; lo dichiara il suo stesso docstring). Come per il guard
di `app.py` (PR-1, `test_palette.py::test_app_py_migrato_ai_token…`), la verifica reale è
un **source-scan** sul file: prova che la migrazione è avvenuta davvero e **blocca ogni
re-hardcode futuro** dei colori dei controlli (drift) — che il diff, troncato per i
reviewer, non mostrerebbe. La logica del pannello è coperta da `tests/unit/test_name_mapping.py`.

Oltre a «zero HEX hardcoded», si **bloccano le semantiche di sicurezza** (§13 handoff): il
pulsante distruttivo «Elimina» resta rosso (`DANGER`), «Salva profilo» verde (`SUCCESS`),
«Precompila da Betfair» blu primario (`ACCENT`) — così un refactor non può cambiare in
silenzio il colore semantico di un'azione distruttiva.
"""

import pathlib
import re

from xtrader_bridge import ui_theme

_SRC_PATH = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge" / "name_mapping_gui.py"
_SRC = _SRC_PATH.read_text(encoding="utf-8")

# Stesso match ESAUSTIVO del guard di app.py: QUALSIASI kwarg che termina in `color`
# impostato a un HEX letterale (stringa `="#…"` O tupla inline `=("#…"`).
_COLOR_KWARG_HEX = re.compile(r'\w*color\s*=\s*\(?\s*"#[0-9a-fA-F]{6}"')


def test_zero_hex_hardcoded_nei_colori():
    """Nessun colore HEX letterale resta come `fg_color`/`hover_color`/`text_color`/… :
    tutti passano dai token `ui_theme`."""
    offenders = _COLOR_KWARG_HEX.findall(_SRC)
    assert offenders == [], (
        "name_mapping_gui.py contiene ancora colori HEX hardcoded (usa i token ui_theme): "
        + ", ".join(offenders))
    # Meta-check (negative case): la regex cattura davvero offender sintetici → il guard
    # non passa "a vuoto" per un pattern troppo stretto.
    for bad in ('text_color="#ef5350"', 'fg_color=("#2e7d32", "#1b5e20")',
                'hover_color = "#7f0000"'):
        assert _COLOR_KWARG_HEX.search(bad), f"il guard NON cattura {bad!r}"


def test_importa_ui_theme():
    """Il modulo deve importare `ui_theme` (fonte unica dei colori)."""
    assert re.search(r'^\s*ui_theme,\s*$', _SRC, re.MULTILINE) or "import ui_theme" in _SRC, \
        "name_mapping_gui.py non importa ui_theme"
    # I token semantici attesi sono effettivamente referenziati.
    for tok in ("ui_theme.STATUS_ERR", "ui_theme.STATUS_WARN", "ui_theme.STATUS_OK",
                "ui_theme.SUCCESS", "ui_theme.ACCENT", "ui_theme.DANGER"):
        assert tok in _SRC, f"token atteso non usato dopo la migrazione: {tok}"


def test_semantica_sicurezza_pulsanti_bloccata():
    """§13: azione distruttiva = rosso, salvataggio = verde, azione primaria = blu.
    Si àncora al testo del bottone e si controlla il colore semantico sulla STESSA riga
    (o nella riga di continuazione immediata del costruttore)."""
    # «Elimina» profilo → DANGER (rosso distruttivo), mai SUCCESS/ACCENT.
    m = re.search(r'"🗑 Elimina"\).*?fg_color=ui_theme\.(\w+)', _SRC, re.DOTALL)
    assert m and m.group(1) == "DANGER", "il bottone «Elimina» profilo deve restare DANGER (rosso)"
    # Piccolo 🗑 di riga → DANGER.
    m2 = re.search(r'text="🗑",[^\n]*fg_color=ui_theme\.(\w+)', _SRC)
    assert m2 and m2.group(1) == "DANGER", "il 🗑 di riga deve restare DANGER (rosso)"
    # «Salva profilo» → SUCCESS (verde).
    m3 = re.search(r'"💾 Salva profilo"\).*?fg_color=ui_theme\.(\w+)', _SRC, re.DOTALL)
    assert m3 and m3.group(1) == "SUCCESS", "«Salva profilo» deve restare SUCCESS (verde)"
    # «Precompila da Betfair» → ACCENT (blu primario).
    m4 = re.search(r'"📥 Precompila da Betfair"\).*?fg_color=ui_theme\.(\w+)', _SRC, re.DOTALL)
    assert m4 and m4.group(1) == "ACCENT", "«Precompila da Betfair» deve restare ACCENT (blu)"


def test_token_usati_sono_theme_aware():
    """I token referenziati dal modulo esistono in ui_theme e sono coppie (light, dark)
    valide — così la migrazione segue davvero il tema (non è un alias rotto)."""
    for name in ("STATUS_ERR", "STATUS_WARN", "STATUS_OK", "SUCCESS", "SUCCESS_HOV",
                 "ACCENT", "ACCENT_HOV", "DANGER", "DANGER_HOV"):
        val = getattr(ui_theme, name)
        assert isinstance(val, tuple) and len(val) == 2, f"{name} non è una coppia (light, dark)"
        for c in val:
            assert isinstance(c, str) and len(c) == 7 and c[0] == "#"
            int(c[1:], 16)   # hex valido
