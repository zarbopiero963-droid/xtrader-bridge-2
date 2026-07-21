"""Redesign UI PR-3 — migrazione colori dei moduli GUI restanti ai token `ui_theme`.

Estende il pattern di PR-1 (`app.py`) e PR-2 (`name_mapping_gui`) agli altri 8 moduli GUI
(`guided_mapping_gui`, `profiles_gui`, `source_chats_gui`, `provider_gui`, `custom_parser_gui`,
`known_teams_gui`, `tools_gui`, `config_agent_gui`) più `signal_outcome` (modulo di LOGICA che
espone `last_color`, non un widget). Questi moduli GUI importano `customtkinter` e **non sono
testabili headless**: la verifica reale è un **source-scan** che (a) prova la migrazione, (b)
blocca ogni re-hardcode futuro (drift), (c) blocca la semantica di sicurezza dei pulsanti
distruttivi. Le logiche restano coperte dai rispettivi test unit (es. `test_signal_outcome.py`).
"""

import pathlib
import re

import pytest

from xtrader_bridge import live_guard, signal_outcome, ui_theme

_PKG = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"

# Moduli migrati in PR-3 (GUI + il modulo-logica signal_outcome che espone `last_color`).
_MODULES = ["guided_mapping_gui", "profiles_gui", "source_chats_gui", "provider_gui",
            "custom_parser_gui", "known_teams_gui", "tools_gui", "config_agent_gui",
            "signal_outcome"]
# Moduli con pulsanti DISTRUTTIVI (delete/remove) di cui bloccare la semantica rossa.
_DESTRUCTIVE_MODULES = ["profiles_gui", "source_chats_gui", "provider_gui",
                        "custom_parser_gui", "known_teams_gui"]

# Guard RAW (rafforzato dopo review #128 — Fable/GPT/Fugu): un guard sui soli kwarg `*color=`
# NON intercettava gli HEX in un ramo ternario (`… if ok else "#ef5350"`), nei valori di un dict
# (`{"text_color": "#ffa726"}`), in una tupla assegnata a variabile (`_COLOR_ERR = ("#c62828",
# "#ef5350")`) o passata a un helper (`color=None if … else "#ef5350"`) — casi tutti presenti nel
# codice. Perciò il guard è ora un raw-scan: **NESSUN** literal `"#rrggbb"`/`"#rgb"` deve restare in
# questi moduli (tutti i colori passano dai token). Ancorato alle virgolette → lunghezza esatta 3/6.
# Copre virgolette DOPPIE **e SINGOLE** (`'#ef5350'`) — review GLM/GPT #128: uno stile di quote
# diverso non deve aprire un bypass. Il backreference `\1` impone quote di apertura/chiusura uguali.
_RAW_HEX = re.compile(r'''(['"])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\1''')


def _src(mod):
    return (_PKG / f"{mod}.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("mod", _MODULES)
def test_zero_hex_hardcoded_nei_colori(mod):
    """Nessun literal HEX resta in QUALSIASI forma (kwarg, ternario, dict, tupla-costante,
    param helper) — tutti i colori passano dai token `ui_theme`."""
    offenders = _RAW_HEX.findall(_src(mod))
    assert offenders == [], f"{mod}.py: colori HEX hardcoded residui (usa ui_theme): {offenders}"


@pytest.mark.parametrize("mod", _MODULES)
def test_tutti_i_token_referenziati_esistono(mod):
    """Review Fugu #128: i moduli GUI non sono importabili headless, quindi un token
    INESISTENTE (es. un refuso `ui_theme.SUCESS`) darebbe `AttributeError` solo a runtime
    (all'apertura della GUI) — il source-scan «zero HEX» NON lo intercetterebbe. Qui si
    estrae ogni `ui_theme.X` referenziato dal modulo e si prova che è un attributo REALE."""
    refs = set(re.findall(r'\bui_theme\.([A-Z_][A-Z0-9_]*)', _src(mod)))
    missing = sorted(r for r in refs if not hasattr(ui_theme, r))
    assert not missing, f"{mod}.py referenzia token ui_theme inesistenti (AttributeError a runtime): {missing}"


@pytest.mark.parametrize("mod", _MODULES)
def test_importa_e_usa_ui_theme(mod):
    """Ogni modulo migrato importa e referenzia `ui_theme` (fonte unica dei colori)."""
    src = _src(mod)
    # Importato via `from . import …, ui_theme` (una riga) O in un blocco import multi-linea
    # (`from . import (\n … \n    ui_theme,\n)` — es. custom_parser_gui).
    assert (re.search(r'from \. import [^\n]*\bui_theme\b', src)
            or re.search(r'(?m)^\s*ui_theme,\s*$', src)), f"{mod}.py non importa ui_theme"
    assert "ui_theme." in src, f"{mod}.py non referenzia alcun token ui_theme.*"


def test_meta_guard_cattura_offender_sintetici():
    """Negative case: il raw-scan cattura l'HEX in TUTTE le forme reali che il vecchio guard
    `*color=` mancava (ternario, dict, tupla-costante, param helper) e a 3/6 cifre — e NON scatta
    su nomi/token legittimi né su HEX a lunghezza non-colore (4/5 cifre)."""
    for bad in ('text_color="#ef5350"',                       # kwarg diretto
                'x if ok else "#ef5350"',                     # ramo ternario (mancava!)
                '{"text_color": "#ffa726"}',                  # valore di dict (mancava!)
                '_COLOR_ERR = ("#c62828", "#ef5350")',        # tupla-costante (mancava!)
                'color=None if placeable else "#ef5350"',     # param helper (mancava!)
                "text_color='#ef5350'",                       # APICI SINGOLI (review #128)
                'fg_color="#f00"'):                           # 3 cifre
        assert _RAW_HEX.search(bad), f"il guard NON cattura {bad!r}"
    for good in ('fg_color=ui_theme.DANGER', 'text_color="gray"', '_COLOR = ui_theme.STATUS_OK',
                 '"#12345"', '"#abcd"',                       # 5/4 cifre: non-colore
                 '''"#fff'"'''):                              # quote disallineate → non matcha
        assert not _RAW_HEX.search(good), f"il guard scatta a vuoto su {good!r}"


@pytest.mark.parametrize("mod", _DESTRUCTIVE_MODULES)
def test_semantica_distruttiva_resta_danger(mod):
    """§13: ogni pulsante DISTRUTTIVO (label 🗑 Elimina/Rimuovi o ✕) resta rosso `DANGER` —
    un refactor non può trasformarlo in verde/blu in silenzio. Si ancorano TUTTE le occorrenze."""
    toks = re.findall(r'text=[^\n]*?(?:🗑|✕)[^\n]*?fg_color=ui_theme\.(\w+)', _src(mod))
    assert toks, f"{mod}.py: nessun pulsante distruttivo 🗑/✕ trovato (regex da rivedere?)"
    assert all(t == "DANGER" for t in toks), \
        f"{mod}.py: pulsante distruttivo con colore NON-DANGER: {toks}"


def test_warn_weak_token_e_uso():
    """Nuovo token `WARN_WEAK` (sfondo warning tenue) — coppia theme-aware valida, usata dalla
    barra "in attesa" dell'assistente (`config_agent_gui`)."""
    val = ui_theme.WARN_WEAK
    assert isinstance(val, tuple) and len(val) == 2
    for c in val:
        assert re.fullmatch(r'#[0-9a-fA-F]{6}', c), c
    assert val[0].lower() != val[1].lower(), "WARN_WEAK non theme-aware"
    assert "ui_theme.WARN_WEAK" in _src("config_agent_gui"), \
        "la barra 'in attesa' di config_agent_gui deve usare ui_theme.WARN_WEAK"


def test_signal_outcome_dry_run_usa_token_theme_aware():
    """`signal_outcome` è headless: si esercita la funzione REALE. DRY_RUN espone `last_color`
    = `STATUS_WARN` (coppia light/dark), che poi `_set_last` inoltra a `configure(text_color=…)`."""
    o = signal_outcome.describe_non_write(
        live_guard.DRY_RUN, {"EventName": "A v B", "SelectionName": "A", "Price": "1,5"})
    assert o is not None and o.last_color == ui_theme.STATUS_WARN
    assert isinstance(o.last_color, tuple) and len(o.last_color) == 2
