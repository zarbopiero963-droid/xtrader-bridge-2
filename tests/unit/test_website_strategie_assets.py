"""Inventario degli screenshot XTrader sull'automazione (W9.5, issue #229).

Perché esiste: sono 103 file binari forniti una volta sola dal proprietario, scaricati da una
cartella Drive poi richiusa. Se un rebase, un `git add` parziale o una pulizia ne perdesse
qualcuno, **non se ne accorgerebbe nessuno** finché non serve per scrivere la guida — e a quel
punto la fonte non è più a portata di mano. Questi test bloccano quel silenzio.

Non verificano l'estetica: verificano che l'inventario dichiarato in `manifest.json` e i file su
disco coincidano, che ogni immagine sia un PNG vero (non un troncamento o una pagina di errore
Drive salvata col nome giusto) e che lo screenshot della Finestra Segnali — l'unico che il
manuale ufficiale non contiene — sia al suo posto.
"""

import json
import struct
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2] / "website" / "static" / "docs" / "strategie-xtrader"
_MANIFEST = _ROOT / "manifest.json"

# Conteggi attesi per cartella, dalla consegna del proprietario (Drive, 08/07/2026).
_EXPECTED = {
    "condizioni": 70,               # 69 PNG + FORMULA.pdf
    "azioni-se-vero": 21,
    "azioni-se-vero-se-falso": 2,
    "varie": 10,
}

# La Finestra Segnali: il capitolo «Segnali» del manuale la descrive a parole ma non la mostra,
# quindi questa immagine è insostituibile per la guida di collegamento a XTrader.
_FINESTRA_SEGNALI = "varie/02-20260708-170631.png"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _png_size(path: Path) -> tuple:
    """Larghezza/altezza dall'header IHDR, senza dipendenze esterne."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "firma PNG assente: %s" % path.name
    return struct.unpack(">II", header[16:24])


@pytest.mark.parametrize("folder,count", sorted(_EXPECTED.items()))
def test_conteggio_file_per_cartella(folder, count):
    on_disk = sorted(p.name for p in (_ROOT / folder).iterdir() if p.is_file())
    assert len(on_disk) == count, "%s: attesi %d file, trovati %d" % (folder, count, len(on_disk))


@pytest.mark.parametrize("folder", sorted(_EXPECTED))
def test_manifest_allineato_al_disco(folder):
    """Il manifest è l'unico ponte verso i nomi originali e gli id Drive: se si sfalsa,
    la tracciabilità della fonte è persa."""
    declared = {r["file"] for r in _manifest()[folder]}
    on_disk = {p.name for p in (_ROOT / folder).iterdir() if p.is_file()}
    assert declared == on_disk, "disallineamento in %s: solo nel manifest %s · solo su disco %s" % (
        folder, sorted(declared - on_disk), sorted(on_disk - declared))


@pytest.mark.parametrize("folder", sorted(_EXPECTED))
def test_ogni_immagine_e_un_png_valido(folder):
    """Un download interrotto o una pagina di login Drive salvata col nome giusto passerebbero
    un semplice controllo di esistenza: qui si legge davvero l'header."""
    for entry in _manifest()[folder]:
        path = _ROOT / folder / entry["file"]
        if path.suffix.lower() == ".pdf":
            assert path.read_bytes()[:5] == b"%PDF-", "PDF non valido: %s" % entry["file"]
            continue
        w, h = _png_size(path)
        assert w > 200 and h > 200, "immagine sospetta %s (%dx%d)" % (entry["file"], w, h)


def test_manifest_traccia_nomi_originali_e_id_drive():
    for folder, rows in _manifest().items():
        for row in rows:
            assert row["originale"], "%s/%s senza nome originale" % (folder, row["file"])
            assert len(row["drive_id"]) >= 25, "%s/%s senza id Drive" % (folder, row["file"])


def test_formula_pdf_presente():
    """`FORMULA.pdf` è la guida alle variabili delle condizioni di tipo formula: il proprietario
    lo indica esplicitamente come il riferimento del pulsante «guida variabili»."""
    pdf = _ROOT / "condizioni" / "FORMULA.pdf"
    assert pdf.is_file() and pdf.read_bytes()[:5] == b"%PDF-"


def test_finestra_segnali_presente():
    path = _ROOT / _FINESTRA_SEGNALI
    assert path.is_file(), "manca lo screenshot della Finestra Segnali (%s)" % _FINESTRA_SEGNALI
    w, h = _png_size(path)
    assert w >= 1000, "la Finestra Segnali dovrebbe essere a piena larghezza, trovato %dx%d" % (w, h)


def test_readme_spiega_provenienza_e_diritti():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    for atteso in ("TradingSportivo", "non affiliato", "Privacy", "manifest.json"):
        assert atteso in readme, "README senza la sezione «%s»" % atteso
