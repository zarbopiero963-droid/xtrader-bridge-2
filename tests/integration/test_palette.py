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


def test_dark_variant_invariata_rispetto_allo_storico(app_mod):
    # La variante DARK resta quella storica (nessuna regressione visiva nel tema di default).
    m = app_mod
    assert m._COLOR_HEADER_BG[1] == "#1a1a2e"
    assert m._COLOR_HEADER_TITLE[1] == "#4fc3f7"
    assert m._COLOR_STATUS_OFFLINE[1] == "#ef5350"
    assert m._COLOR_STATUS_ACTIVE[1] == "#66bb6a"
    assert m._COLOR_STATUS_RECONNECT[1] == "#ffa726"
    assert m._COLOR_ACTIVE_ROWS[1] == "#ffb74d"
    assert m._COLOR_REAL_BANNER_BG[1] == "#7f1d1d"
