"""Test di leggibilità della palette semantica theme-aware (#288 Delta 3).

La #288 Delta 1 ha introdotto il toggle tema chiaro/scuro ma i colori di STATO erano hardcoded per
lo scuro. Delta 3 li rende `(light, dark)`. Questo test verifica **automaticamente** ciò che prima
era solo «smoke manuale»: che ogni colore semantico abbia **contrasto sufficiente** (WCAG) sul
proprio sfondo in ENTRAMBI i temi — così «Crea CSV»/OFFLINE/ATTIVO/righe attive/banner restano
leggibili anche in chiaro. Usa le costanti REALI di `app.py`.
"""


def _luminance(hex_color):
    # Luminanza relativa WCAG di un colore "#rrggbb".
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def _lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    R, G, B = _lin(r), _lin(g), _lin(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def _contrast(fg, bg):
    l1, l2 = _luminance(fg), _luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# Sfondo di default dei frame/tab CustomTkinter ("gray86" / "gray17") su cui vive il warning chat.
_FRAME_BG = ("#dbdbdb", "#2b2b2b")
_WHITE = ("#ffffff", "#ffffff")

# Soglia di contrasto: testo di STATO grande/bold nell'header → WCAG "large text" ≥ 3.0. Puntiamo
# comunque a un margine ampio; una soglia più alta romperebbe su colori di stato accesi legittimi.
_MIN_CONTRAST = 3.0


def _pairs(m):
    """Coppie (nome, testo(light,dark), sfondo(light,dark)) da verificare in entrambi i temi."""
    hdr = m._COLOR_HEADER_BG
    return [
        ("titolo",        m._COLOR_HEADER_TITLE,     hdr),
        ("OFFLINE",       m._COLOR_STATUS_OFFLINE,   hdr),
        ("ATTIVO",        m._COLOR_STATUS_ACTIVE,    hdr),
        ("RICONNESSIONE", m._COLOR_STATUS_RECONNECT, hdr),
        ("righe attive",  m._COLOR_ACTIVE_ROWS,      hdr),
        ("warning chat",  m._COLOR_WARNING,          _FRAME_BG),
        ("banner reale",  _WHITE,                    m._COLOR_REAL_BANNER_BG),
    ]


def test_palette_contrasto_sufficiente_in_entrambi_i_temi(app_mod):
    for name, fg, bg in _pairs(app_mod):
        for theme, idx in (("light", 0), ("dark", 1)):
            c = _contrast(fg[idx], bg[idx])
            assert c >= _MIN_CONTRAST, \
                f"{name} in tema {theme}: contrasto {c:.2f} < {_MIN_CONTRAST} ({fg[idx]} su {bg[idx]})"


def test_palette_colori_theme_aware_e_hex_validi(app_mod):
    m = app_mod
    tuples = [m._COLOR_HEADER_BG, m._COLOR_HEADER_TITLE, m._COLOR_STATUS_OFFLINE,
              m._COLOR_STATUS_ACTIVE, m._COLOR_STATUS_RECONNECT, m._COLOR_ACTIVE_ROWS,
              m._COLOR_WARNING, m._COLOR_REAL_BANNER_BG]
    for t in tuples:
        assert isinstance(t, tuple) and len(t) == 2, t
        for c in t:
            assert isinstance(c, str) and len(c) == 7 and c[0] == "#", c
            int(c[1:], 16)   # hex valido (solleva se no)
        # variante chiara e scura DIVERSE (altrimenti non è theme-aware)
        assert t[0].lower() != t[1].lower(), f"colore non theme-aware: {t}"


def test_nessun_colore_di_stato_hardcoded_fuori_dalle_costanti(app_mod):
    # Regression guard (GLM #334): i colori SEMANTICI storici non devono ricomparire hardcoded
    # come `text_color="#…"`/`fg_color="#…"` — né alla costruzione né nei `configure` dinamici
    # (OFFLINE/ATTIVO/RICONNESSIONE) — ma passare SEMPRE dalle costanti `_COLOR_*` theme-aware.
    # Il test di contrasto valida solo le costanti; questo cattura un futuro re-hardcode che
    # quello non vedrebbe. NB: verifica solo gli hex ESCLUSIVI dello stato (non `#2e7d32`/
    # `#c62828`, usati anche dai pulsanti d'azione tinta-unita, fuori scope).
    import pathlib
    src = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
    for hx in ("#1a1a2e", "#4fc3f7", "#ef5350", "#66bb6a", "#ffa726", "#ffb74d", "#7f1d1d"):
        assert f'text_color="{hx}"' not in src, \
            f"colore di stato {hx} hardcoded come text_color (usa le costanti _COLOR_*)"
        assert f'fg_color="{hx}"' not in src, \
            f"colore di stato {hx} hardcoded come fg_color (usa le costanti _COLOR_*)"


def test_app_py_migrato_ai_token_nessun_hex_hardcoded_nei_colori(app_mod):
    """Redesign UI PR-1 (review GPT/GLM #126): PROVA che `app.py` è davvero migrato ai token
    `ui_theme` — nessun HEX letterale resta come `fg_color`/`hover_color`/`text_color`. Il
    diff che i reviewer ricevono tronca `app.py` (troppo grande), quindi non "vedono" la
    migrazione: questo guard la rende verificabile in CI e blocca ogni re-hardcode futuro dei
    colori dei controlli (drift). I colori DEVONO passare dai token o dalle costanti `_COLOR_*`.
    """
    import pathlib
    import re
    src = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
    # Copre sia il literal stringa (`fg_color="#…"`) SIA la tupla inline
    # (`fg_color=("#…", "#…")`) — review GLM #126: un re-hardcode futuro come tupla inline
    # non deve sfuggire al guard. I colori DEVONO passare da un token/costante, mai da un
    # HEX letterale in una proprietà colore.
    offenders = re.findall(
        r'(?:fg_color|hover_color|text_color|border_color)\s*=\s*\(?\s*"#[0-9a-fA-F]{6}"', src)
    assert offenders == [], (
        "app.py contiene ancora colori HEX hardcoded (usa ui_theme / _COLOR_*): "
        + ", ".join(offenders))


def test_dark_variant_allineata_al_design_system(app_mod):
    # Redesign UI (integration_kit.md): la variante DARK (tema primario) segue ora il design
    # system centralizzato in `ui_theme`. Questo test resta un guard contro drift ACCIDENTALI,
    # ma dalla NUOVA baseline design — non più dai valori storici pre-redesign. La leggibilità
    # WCAG in entrambi i temi è comunque verificata da `test_palette_contrasto_sufficiente…`.
    from xtrader_bridge import ui_theme as t
    m = app_mod
    assert m._COLOR_HEADER_BG == t.TITLEBAR
    assert m._COLOR_HEADER_TITLE == t.TITLE_TEXT
    assert m._COLOR_STATUS_OFFLINE == t.STATUS_ERR
    assert m._COLOR_STATUS_ACTIVE == t.STATUS_OK
    assert m._COLOR_STATUS_RECONNECT == t.STATUS_WARN
    assert m._COLOR_ACTIVE_ROWS == t.STATUS_WARN
    assert m._COLOR_REAL_BANNER_BG == t.DANGER_BANNER
    # Il banner REALE resta un rosso PROFONDO (testo bianco leggibile = invariante §13):
    # variante dark scura, non il DANGER brillante dei bottoni.
    assert m._COLOR_REAL_BANNER_BG[1] == "#7f1d1d"


def test_set_last_accetta_tupla_light_dark_come_colore(app_mod):
    """Review Fugu #126: `_set_last(..., color)` prima riceveva una stringa (es. "white",
    "#66bb6a"); il redesign passa ora una coppia `(light,dark)` da `ui_theme`. CTk accetta
    la coppia per `text_color` (è il meccanismo già usato ovunque nell'app coi `_COLOR_*`),
    e `_set_last` la INOLTRA invariata a `configure(text_color=…)` senza parsing su stringa.
    Qui si prova col metodo REALE su un `self` finto: la label riceve la TUPLA tale e quale."""
    import types
    from xtrader_bridge import ui_theme
    m = app_mod
    captured = {}

    class _Lbl:
        def configure(self, **k):
            captured.update(k)

    fake = types.SimpleNamespace(
        _last_vals={},
        _last_lbls={"error": _Lbl()},
        _refresh_health=lambda *a, **k: None,   # difensivo (review GLM #126)
    )
    # Metodo REALE della classe App, invocato sul finto self.
    m.App._set_last(fake, "error", "recuperato", ui_theme.STATUS_OK)
    assert captured.get("text_color") == ui_theme.STATUS_OK   # tupla inoltrata invariata
    assert isinstance(captured["text_color"], tuple) and len(captured["text_color"]) == 2
