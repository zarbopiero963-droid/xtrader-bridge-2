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
# impostato a un HEX letterale. Copre:
#  - la stringa singola `="#…"`;
#  - un HEX in QUALSIASI posizione di una tupla `=("#…", …)` O `=(token, "#…")` — non solo il
#    PRIMO elemento (follow-up Fugu #127 / Fable #126: un re-hardcode nella variante dark
#    `("gray", "#000")` non deve sfuggire, altrimenti la garanzia «blocca ogni re-hardcode» è falsa);
#  - HEX a **6** e a **3** cifre (`#f00`), entrambi validi in Tk/CTk; il lookahead nega 4-5 cifre.
# `[^)\n]*` limita la ricerca dentro la STESSA tupla su una riga (niente over-reach a call successive).
_HEX = r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])'
_COLOR_KWARG_HEX = re.compile(r'\w*color\s*=\s*(?:"' + _HEX + r'|\([^)\n]*"' + _HEX + r')')


def test_zero_hex_hardcoded_nei_colori():
    """Nessun colore HEX letterale resta come `fg_color`/`hover_color`/`text_color`/… :
    tutti passano dai token `ui_theme`."""
    offenders = _COLOR_KWARG_HEX.findall(_SRC)
    assert offenders == [], (
        "name_mapping_gui.py contiene ancora colori HEX hardcoded (usa i token ui_theme): "
        + ", ".join(offenders))
    # Meta-check (negative case): la regex cattura davvero gli offender sintetici → il guard
    # non passa "a vuoto". Include HEX a 3 cifre (Fable #127) e HEX come 2° elemento di tupla
    # mista (Fugu #127): un re-hardcode nella variante dark non deve sfuggire.
    for bad in ('text_color="#ef5350"', 'fg_color=("#2e7d32", "#1b5e20")',
                'hover_color = "#7f0000"', 'text_color="#f00"',
                'fg_color=("gray", "#000")', 'text_color=(ui_theme.TEXT, "#000000")'):
        assert _COLOR_KWARG_HEX.search(bad), f"il guard NON cattura {bad!r}"
    # ...e NON scatta su non-colori (4-5 cifre) o su token/nomi legittimi: niente falsi positivi.
    for ok in ('text_color="#12345"', 'fg_color="#abcd"', 'fg_color=ui_theme.DANGER',
               'text_color="gray"', 'fg_color=("gray", "white")'):
        assert not _COLOR_KWARG_HEX.search(ok), f"il guard scatta a vuoto su {ok!r}"


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
    Follow-up Fable #127: si ancorano **TUTTE** le occorrenze (findall), non solo la prima —
    così una regressione sul pulsante omonimo del **secondo pannello** (MarketMappingPanel)
    non passa inosservata. Ogni etichetta precede il proprio `fg_color` nella stessa call."""
    def _tokens_after(label_regex, flags=re.DOTALL):
        return re.findall(label_regex + r'.*?fg_color=ui_theme\.(\w+)', _SRC, flags)

    # «Elimina» profilo → DANGER su OGNI pannello (2 occorrenze: Nome + Mercato).
    elimina = _tokens_after(r'"🗑 Elimina"\)')
    assert len(elimina) >= 2 and all(t == "DANGER" for t in elimina), \
        f"«Elimina» profilo deve restare DANGER (rosso) su ogni pannello, trovato: {elimina}"
    # Piccolo 🗑 di riga → DANGER su OGNI pannello (2 occorrenze).
    cestini = _tokens_after(r'text="🗑",', flags=0)   # su singola riga
    assert len(cestini) >= 2 and all(t == "DANGER" for t in cestini), \
        f"il 🗑 di riga deve restare DANGER (rosso) su ogni pannello, trovato: {cestini}"
    # «Salva profilo» → SUCCESS su OGNI pannello (2 occorrenze).
    salva = _tokens_after(r'"💾 Salva profilo"\)')
    assert len(salva) >= 2 and all(t == "SUCCESS" for t in salva), \
        f"«Salva profilo» deve restare SUCCESS (verde) su ogni pannello, trovato: {salva}"
    # «Precompila da Betfair» → ACCENT (solo NameMappingPanel: 1 occorrenza).
    betfair = _tokens_after(r'"📥 Precompila da Betfair"\)')
    assert betfair and all(t == "ACCENT" for t in betfair), \
        f"«Precompila da Betfair» deve restare ACCENT (blu), trovato: {betfair}"


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
