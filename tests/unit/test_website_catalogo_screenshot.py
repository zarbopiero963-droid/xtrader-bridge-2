"""Il catalogo delle descrizioni deve restare allineato agli screenshot (W9.5, issue #229).

Perché conta: il catalogo è ciò che rende gli screenshot utilizzabili da un **assistente AI**, che
le immagini non le sa leggere. Se una descrizione manca, per il modello quell'immagine semplicemente
non esiste; se il file a cui punta è stato rinominato, il modello cita un percorso rotto. Nessuno dei
due errori si vede guardando la cartella — ma entrambi rendono il catalogo inaffidabile proprio nel
momento in cui serve.

I test verificano la corrispondenza biunivoca immagini↔descrizioni, la completezza dei campi, e che
le voci dichiarate «altissima rilevanza» siano davvero quelle del percorso di collegamento a
XTrader (fonte segnali, azione da segnali, guardie anti-doppione).
"""

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "website" / "static" / "docs" / "strategie-xtrader"
_JSONL = _DIR / "catalogo.jsonl"
_MD = _DIR / "catalogo.md"

_CAMPI = ("file", "finestra", "rilevanza_bridge", "descrizione", "usare_per", "privacy")
_RILEVANZE = {"altissima", "alta", "media", "bassa"}

# Le schermate senza le quali la guida di collegamento non si può scrivere.
_INDISPENSABILI = {
    "varie/02-20260708-170631.png",          # finestra Segnali
    "varie/03-20260708-170658.png",          # dialog Fonte Segnali
    "varie/04-20260708-170716.png",          # Fonte Segnali + Lingua Palinsesto
    "azioni-se-vero/04-20260708-165534.png", # azione «Piazza Scommesse su Segnali»
    "condizioni/42-20260706-192032.png",     # condizione «Conta scommesse» (anti-doppione)
}


def _voci() -> list:
    return [json.loads(riga) for riga in _JSONL.read_text(encoding="utf-8").splitlines() if riga.strip()]


def test_ogni_immagine_ha_la_sua_descrizione():
    """Corrispondenza biunivoca: nessuna immagine muta, nessuna voce orfana."""
    catalogate = {v["file"] for v in _voci()}
    su_disco = {f"{p.parent.name}/{p.name}" for p in _DIR.rglob("*.png")}
    assert catalogate == su_disco, "senza descrizione: %s · descritte ma assenti: %s" % (
        sorted(su_disco - catalogate), sorted(catalogate - su_disco))


def test_nessun_file_duplicato_nel_catalogo():
    files = [v["file"] for v in _voci()]
    assert len(files) == len(set(files)), "voci duplicate nel catalogo"


@pytest.mark.parametrize("campo", _CAMPI)
def test_tutti_i_campi_presenti_e_non_vuoti(campo):
    vuoti = [v.get("file", "?") for v in _voci() if not str(v.get(campo, "")).strip()]
    assert not vuoti, "campo «%s» vuoto in: %s" % (campo, vuoti)


def test_rilevanza_e_un_valore_ammesso():
    ignoti = {v["rilevanza_bridge"] for v in _voci()} - _RILEVANZE
    assert not ignoti, "rilevanze non ammesse: %s" % sorted(ignoti)


def test_descrizioni_non_generiche():
    """Una descrizione di due parole non dice al modello dove guardare: è peggio di niente,
    perché sembra copertura senza esserlo."""
    corte = [(v["file"], len(v["descrizione"])) for v in _voci() if len(v["descrizione"]) < 80]
    assert not corte, "descrizioni troppo brevi per essere utili: %s" % corte


def test_le_schermate_indispensabili_sono_catalogate_al_massimo_livello():
    per_file = {v["file"]: v for v in _voci()}
    for f in sorted(_INDISPENSABILI):
        assert f in per_file, "manca dal catalogo la schermata indispensabile %s" % f
        assert per_file[f]["rilevanza_bridge"] == "altissima", (
            "%s non è marcata «altissima»: un assistente non la proporrebbe per prima" % f)


def test_i_rilievi_privacy_sono_registrati():
    """I due rilievi trovati nella verifica esaustiva devono restare tracciati: se qualcuno
    li cancella dal catalogo, la pubblicazione avverrebbe senza saperlo."""
    voci = _voci()
    attenzioni = [v for v in voci if v["privacy"].startswith("ATTENZIONE")]
    assert len(attenzioni) >= 10, "i rilievi privacy sono spariti dal catalogo"
    assert any("Abbonamento" in v["privacy"] for v in voci), "manca il rilievo sulla barra del titolo"
    assert any("SIG_PREMATCH_BASE" in v["privacy"] for v in voci), "manca il rilievo sul nome strategia"


def test_catalogo_markdown_rigenerato_dallo_jsonl():
    """Il .md è generato dallo .jsonl: se qualcuno aggiunge una voce e dimentica di rigenerarlo,
    la versione leggibile resta indietro."""
    md = _MD.read_text(encoding="utf-8")
    mancanti = [v["file"].split("/")[1] for v in _voci() if v["file"].split("/")[1] not in md]
    assert not mancanti, "catalogo.md non rigenerato, mancano: %s" % mancanti[:5]


def test_guide_esistono_e_citano_gli_screenshot():
    """Le guide devono puntare a immagini che esistono davvero: un riferimento rotto manda
    l'assistente a citare uno screenshot inesistente."""
    import re

    su_disco = {f"{p.parent.name}/{p.name}" for p in _DIR.rglob("*.png")}
    for nome in ("xtrader_integration.md", "xtrader_formule.md"):
        testo = (_ROOT / "docs" / nome).read_text(encoding="utf-8")
        citati = set(re.findall(r"`((?:varie|condizioni|azioni-se-vero(?:-se-falso)?)/[\w.-]+\.png)`", testo))
        rotti = sorted(citati - su_disco)
        assert not rotti, "%s cita screenshot inesistenti: %s" % (nome, rotti)
