"""Test del modulo tema `ui_theme` (redesign UI, integration_kit.md).

`ui_theme` è la fonte UNICA dei colori/geometria. È un modulo PURO (nessun import
customtkinter): testabile headless. Qui si blindano le proprietà che NON devono
regredire in un refactor futuro del tema:

- ogni token colore è una coppia `(light, dark)` di HEX validi e theme-aware;
- la SEMANTICA di sicurezza (§13) è coerente: verde=SUCCESS, rosso=DANGER, ecc.;
- gli sfondi-banner a testo bianco restano PROFONDI (leggibilità WCAG = invariante §13):
  il banner REALE non deve mai diventare il rosso brillante dei bottoni;
- i token "testo di stato" (usati come testo su superficie chiara) hanno contrasto
  WCAG ≥ 3.0 in ENTRAMBI i temi.
"""

from xtrader_bridge import ui_theme as t


# ── helper WCAG (duplicato minimale, il modulo tema è puro) ──────────────────
def _lum(hx):
    r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(fg, bg):
    l1, l2 = _lum(fg), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


_COLOR_TOKENS = [
    "WIN", "TITLEBAR", "SURFACE", "SURFACE2", "SURFACE3", "BORDER",
    "TEXT", "TEXT2", "TEXT3",
    "ACCENT", "ACCENT_HOV", "SUCCESS", "SUCCESS_HOV", "DANGER", "DANGER_HOV",
    "WARN", "INFO", "PURPLE", "PURPLE_HOV", "TEAL", "TEAL_HOV",
    "TITLE_TEXT", "STATUS_OK", "STATUS_ERR", "STATUS_WARN",
    "DANGER_BANNER", "WARN_BANNER",
]


def test_ogni_token_e_coppia_light_dark_hex_valida():
    for name in _COLOR_TOKENS:
        val = getattr(t, name)
        assert isinstance(val, tuple) and len(val) == 2, f"{name}: non è una coppia (light,dark)"
        for c in val:
            assert isinstance(c, str) and len(c) == 7 and c[0] == "#", f"{name}: HEX invalido {c!r}"
            int(c[1:], 16)   # solleva se non-hex


def test_token_theme_aware_dove_serve():
    # I token colore devono avere varianti light/dark DIVERSE (altrimenti non seguono il tema).
    # Eccezioni legittime: nessuna qui — tutti i ruoli hanno due sfumature.
    for name in _COLOR_TOKENS:
        light, dark = getattr(t, name)
        assert light.lower() != dark.lower(), f"{name}: non theme-aware ({light})"


def test_semantica_sicurezza_bloccata():
    # §13: i ruoli semantici NON vanno rimappati. Verde ≠ rosso ≠ arancione, e ciascuno
    # nella famiglia cromatica attesa (guard contro uno swap accidentale che invertirebbe
    # il significato di sicurezza di AVVIA/STOP/REALE).
    def _rgb(hx):
        return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
    for tok in ("SUCCESS", "STATUS_OK"):
        r, g, b = _rgb(getattr(t, tok)[1])
        assert g > r and g > b, f"{tok} dark non è verde: {getattr(t, tok)[1]}"
    for tok in ("DANGER", "STATUS_ERR", "DANGER_BANNER"):
        r, g, b = _rgb(getattr(t, tok)[1])
        assert r > g and r > b, f"{tok} dark non è rosso: {getattr(t, tok)[1]}"


def test_banner_reale_e_profondo_non_brillante():
    # Invariante §13 (leggibilità = sicurezza): il banner REALE ha testo BIANCO su fondo
    # esteso → deve restare un rosso PROFONDO (contrasto alto), non il DANGER brillante dei
    # bottoni. Verifica: bianco sul banner ha contrasto ≥ 4.5 (soglia testo normale), mentre
    # bianco sul DANGER-bottone NON lo raggiungerebbe (perché è pensato per essere un fill).
    for idx, theme in ((0, "light"), (1, "dark")):
        c_banner = _contrast("#ffffff", t.DANGER_BANNER[idx])
        assert c_banner >= 4.5, f"banner REALE {theme}: bianco/{t.DANGER_BANNER[idx]} = {c_banner:.2f} < 4.5"
    # Il banner è più scuro (profondo) del DANGER-bottone in ENTRAMBi i temi.
    assert _lum(t.DANGER_BANNER[1]) < _lum(t.DANGER[1])
    assert _lum(t.DANGER_BANNER[0]) < _lum(t.DANGER[0])


def test_status_text_wcag_su_superfici():
    # I token "testo di stato" devono essere leggibili (≥3.0, large text WCAG) sull'header
    # in entrambi i temi — sono usati come testo colorato, non come fill.
    bg = t.TITLEBAR
    for tok in ("TITLE_TEXT", "STATUS_OK", "STATUS_ERR", "STATUS_WARN"):
        for idx, theme in ((0, "light"), (1, "dark")):
            c = _contrast(getattr(t, tok)[idx], bg[idx])
            assert c >= 3.0, f"{tok} {theme}: {c:.2f} < 3.0 su header {bg[idx]}"


def test_geometria_e_font_presenti():
    assert t.RADIUS_CTRL > 0 and t.RADIUS_CARD > 0 and t.RADIUS_WIN > 0
    assert t.H_CTRL > 0 and t.H_ACTION >= t.H_CTRL
    assert isinstance(t.FONT_UI, str) and isinstance(t.FONT_MONO, str)
