"""#182 restyle — `ui_cards`: card/badge/hint con i token e tolleranza ai doppi headless.

⚠️ MAI widget CustomTkinter VERI qui (incidente CI 2026-08-04: un `CTkFrame` reale senza
display uccide la suite): si usa un modulo `ctk` FINTO che registra le kwargs, così si
verifica il CONTRATTO (token giusti, best-effort sui doppi) senza toccare Tk."""

import types

import pytest

from xtrader_bridge import ui_cards, ui_theme


class _Registrati:
    """Base dei widget finti: registra kwargs e le chiamate pack/configure."""

    costruiti = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.packs = []
        type(self).costruiti.append(self)

    def pack(self, **kwargs):
        self.packs.append(kwargs)


class _SenzaMetodi:
    """Doppio OSTILE: nessun pack/configure — come le classi generate al volo nei test AST."""

    def __init__(self, *args, **kwargs):
        pass


def _ctk_finto(widget_cls):
    mod = types.ModuleType("ctk_finto")
    mod.CTkFrame = type("CTkFrame", (widget_cls,), {"costruiti": []})
    mod.CTkLabel = type("CTkLabel", (widget_cls,), {"costruiti": []})
    mod.CTkFont = lambda **kw: ("font", tuple(sorted(kw.items())))
    return mod


def test_card_usa_i_token_e_ritorna_il_frame():
    ctk = _ctk_finto(_Registrati)
    frame = ui_cards.card(ctk, parent="genitore", title="Sezione")
    assert isinstance(frame, ctk.CTkFrame)
    kw = frame.kwargs
    assert kw["fg_color"] == ui_theme.SURFACE
    assert kw["corner_radius"] == ui_theme.RADIUS_CARD
    assert kw["border_color"] == ui_theme.BORDER
    assert frame.packs, "la card si impacchetta da sola"
    # col titolo, la label è figlia della card (cornice costruita QUI, non nei pannelli)
    assert any(lbl.args and lbl.args[0] is frame for lbl in ctk.CTkLabel.costruiti)


def test_card_senza_titolo_non_crea_label():
    ctk = _ctk_finto(_Registrati)
    ui_cards.card(ctk, parent="genitore", title="")
    assert ctk.CTkLabel.costruiti == []


@pytest.mark.parametrize("kind, colore", [
    ("ok", ui_theme.STATUS_OK),
    ("muted", ui_theme.TEXT2),
    ("warn", ui_theme.STATUS_WARN),
    ("danger", ui_theme.STATUS_ERR),
])
def test_badge_colore_per_ruolo(kind, colore):
    ctk = _ctk_finto(_Registrati)
    shell = ui_cards.badge(ctk, "genitore", "testo", kind=kind)
    assert shell.kwargs["border_color"] == colore
    (lbl,) = ctk.CTkLabel.costruiti
    assert lbl.kwargs["text"] == "testo" and lbl.kwargs["text_color"] == colore


def test_badge_kind_ignoto_degrada_a_muted():
    ctk = _ctk_finto(_Registrati)
    shell = ui_cards.badge(ctk, "genitore", "x", kind="inesistente")
    assert shell.kwargs["border_color"] == ui_theme.TEXT2


def test_helpers_non_crollano_sui_doppi_senza_metodi():
    """Il contratto best-effort: doppi senza pack/configure → nessuna eccezione."""
    ctk = _ctk_finto(_SenzaMetodi)
    ui_cards.card(ctk, parent=None, title="t")
    ui_cards.badge(ctk, None, "b")
    ui_cards.hint(ctk, None, "h")


def test_card_style_e_la_fonte_unica_dei_token():
    """Rilievo CodeRabbit #236: i pannelli devono prendere lo stile da QUI, non duplicare
    i letterali. Il contratto: i 4 token, e il bordo alternativo per le colonne-lista."""
    kw = ui_cards.card_style()
    assert kw == {"fg_color": ui_theme.SURFACE,
                  "corner_radius": ui_theme.RADIUS_CARD,
                  "border_width": 1,
                  "border_color": ui_theme.BORDER}
    accent = ui_cards.card_style(border=ui_theme.ACCENT)
    assert accent["border_color"] == ui_theme.ACCENT
    assert {k: v for k, v in accent.items() if k != "border_color"} == \
           {k: v for k, v in kw.items() if k != "border_color"}


def test_nessun_pannello_duplica_i_token_della_card():
    """La classe, non il sito (regola 2): NESSUN modulo GUI fuori da ui_cards deve
    ripetere il letterale `corner_radius=ui_theme.RADIUS_CARD` — se ricompare, la
    fonte unica si è di nuovo sdoppiata."""
    import pathlib
    pkg = pathlib.Path(ui_cards.__file__).parent
    colpevoli = [p.name for p in pkg.glob("*.py")
                 if p.name != "ui_cards.py"
                 and "corner_radius=ui_theme.RADIUS_CARD" in p.read_text(encoding="utf-8")]
    assert colpevoli == []


def test_hint_usa_testo_e_colore_tenue():
    ctk = _ctk_finto(_Registrati)
    lbl = ui_cards.hint(ctk, "genitore", "aiuto")
    assert lbl.kwargs["text"] == "aiuto"
    assert lbl.kwargs["text_color"] == ui_theme.TEXT3
