"""Screenshot dell'app in IT/EN/ES per le sezioni per-software del sito.

Servono alle tre sezioni «BetRelay per XTrader / for BETTINGTOOLKIT.COM / para .ES-.LAT», secondo
la regola in `docs/policy_lingue_sito.md`. Sono rigenerabili (`tools/screenshots/shoot.sh`), quindi
il rischio non è perderli: è che una lingua resti **indietro** rispetto alle altre dopo un cambio
di interfaccia, e che il sito mostri a un utente inglese una schermata che non corrisponde più.

Questi test tengono le tre lingue allineate fra loro e verificano che le immagini siano PNG veri.
"""

import struct
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "docs" / "assets" / "screenshots" / "linux-xvfb"
_LINGUE = ("it", "en", "es")

# Le tre schermate che ogni lingua deve avere.
_ATTESE = ("main-01-generale.png", "main-02-sicurezza.png", "main-03-salute.png")


def _png_size(path: Path) -> tuple:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "non è un PNG: %s" % path
    return struct.unpack(">II", header[16:24])


@pytest.mark.parametrize("lang", _LINGUE)
@pytest.mark.parametrize("nome", _ATTESE)
def test_ogni_lingua_ha_le_stesse_schermate(lang, nome):
    """Se una lingua resta indietro, il sito mostra una sezione con schermate incomplete."""
    p = _DIR / lang / nome
    assert p.is_file(), "manca %s/%s: la lingua è rimasta indietro" % (lang, nome)


@pytest.mark.parametrize("lang", _LINGUE)
@pytest.mark.parametrize("nome", _ATTESE)
def test_le_immagini_sono_png_plausibili(lang, nome):
    """Una cattura andata storta produce spesso un PNG minuscolo o vuoto: qui si legge
    davvero l'header e si controlla che la finestra ci stia dentro."""
    w, h = _png_size(_DIR / lang / nome)
    assert w >= 600 and h >= 600, "%s/%s troppo piccola (%dx%d)" % (lang, nome, w, h)


def test_le_tre_lingue_hanno_la_stessa_finestra():
    """Stessa app, stessa finestra: dimensioni molto diverse fra lingue vorrebbero dire che una
    cattura ha preso la finestra sbagliata (o un dialog sovrapposto, come è successo con lo
    spagnolo prima di parametrizzare le coordinate)."""
    for nome in _ATTESE:
        misure = {lang: _png_size(_DIR / lang / nome) for lang in _LINGUE}
        assert len({m[0] for m in misure.values()}) == 1, \
            "%s: larghezze diverse fra lingue → %s" % (nome, misure)
        # anche le altezze: una cattura che prende un dialog sovrapposto o una finestra
        # tagliata di solito cambia l'altezza, non la larghezza — controllare solo quella
        # lasciava passare esattamente il caso che questo test esiste per bloccare
        assert len({m[1] for m in misure.values()}) == 1, \
            "%s: altezze diverse fra lingue → %s" % (nome, misure)


def test_lo_script_di_cattura_e_versionato_ed_eseguibile():
    """La pipeline va tenuta col materiale che produce: senza lo script, rigenerare gli
    screenshot dopo un cambio di interfaccia significherebbe ricostruire tutto a mano."""
    s = _ROOT / "tools" / "screenshots" / "shoot.sh"
    assert s.is_file(), "manca tools/screenshots/shoot.sh"
    testo = s.read_text(encoding="utf-8")
    for lang in _LINGUE:
        assert ("#   %s " % lang) in testo, "lo script non documenta le coordinate per «%s»" % lang


def test_il_readme_dichiara_le_lacune_di_traduzione():
    """Le catture EN/ES mostrano parti di interfaccia ancora in italiano. È un fatto, non un
    difetto delle immagini — ma va scritto, altrimenti chi le usa per il sito pensa che siano
    sbagliate e le rifà (o peggio, le ritocca)."""
    testo = (_DIR / "README.md").read_text(encoding="utf-8")
    assert "localizzazione EN/ES è incompleta" in testo
    for atteso in ("Righe attive", "Modalità bridge", "semafori"):
        assert atteso in testo, "il README non elenca più la lacuna «%s»" % atteso
