"""Restyle #182 fase 2 — finestra principale, wizard e assistente sul kit card.

Controllo a livello sorgente (stesso stile della guardia anti-sdoppiamento): i
contenuti delle schede di monitoraggio, le tile della dashboard, il log box, il
corpo del wizard e il trascritto dell'assistente devono prendere lo stile dalla
FONTE UNICA `ui_cards.card_style()` — non da letterali duplicati (regola 3).

Il numero minimo di siti è un floor, non un conteggio esatto: aggiungere card è
lecito, scendere sotto il floor significa che un pezzo del restyle è regredito.
"""
from __future__ import annotations

import pathlib

PKG = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"


def _sorgente(nome: str) -> str:
    return (PKG / nome).read_text(encoding="utf-8")


def test_finestra_principale_usa_il_kit_card():
    src = _sorgente("app.py")
    # chats_card + stato_card + health_card + tile dashboard + log box = 5 siti minimi
    assert src.count("ui_cards.card_style()") >= 5


def test_dashboard_tile_hanno_il_valore_sopra_e_la_didascalia_sotto():
    """La composizione della tile è quella dello sketch: numero grande, poi label."""
    src = _sorgente("app.py")
    inizio = src.index("for col, (name, label) in enumerate(dashboard_stats.COUNTERS):")
    blocco = src[inizio:inizio + 700]
    assert "ui_cards.card_style()" in blocco
    assert blocco.index('text="0"') < blocco.index("text=i18n.tr(label)")


def test_wizard_e_assistente_usano_il_kit_card():
    assert _sorgente("wizard_gui.py").count("ui_cards.card_style()") >= 2
    assert _sorgente("config_agent_gui.py").count("ui_cards.card_style()") >= 1


def test_i_banner_di_sicurezza_non_sono_stati_toccati():
    """Invariante: i tre banner (REALE/COLLAUDO/LICENZA) restano label piene coi
    loro colori dedicati — MAI convertiti in card col bordo sottile."""
    src = _sorgente("app.py")
    for attr in ("_real_banner", "_collaudo_banner", "_license_banner"):
        idx = src.index(f"self.{attr} = ctk.CTkLabel(")
        costruzione = src[idx:idx + 300]
        assert "card_style" not in costruzione
        assert 'text_color="white"' in costruzione
