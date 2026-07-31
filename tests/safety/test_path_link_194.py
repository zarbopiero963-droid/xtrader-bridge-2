"""B7 (#194 · PR-F) — un `csv_path` che è un link non veniva risolto in SCRITTURA.

`clear_stale_csv` legge con `open()`, che **segue** il link, quindi vede l'header giusto e
decide di ripulire. Poi scrive con `atomic_write`, che fa `os.replace(tmp, path)` — e
`os.replace` sostituisce **il link stesso**, non il file puntato. Risultato misurato sul
codice pre-patch:

```text
clear_stale_csv ha detto: True («ripulito»)
righe nel file REALE:     2      ← la riga stantia c'e' ancora
il link e' ancora un link? False ← sostituito da un file normale
```

Il segnale orfano sopravvive su disco, XTrader lo rilegge, e l'app crede di averlo tolto.
È la difesa anti-segnale-stantio che riporta successo senza aver fatto nulla — il modo
peggiore di fallire, perché nessuno va a controllare.

La correzione risolve il link **alla radice** (`atomic_io.atomic_write`), quindi vale per
ogni scrittura CSV e non solo per lo svuotamento: scrivere attraverso un link deve
aggiornare il file puntato e lasciare il link al suo posto.
"""

import os

import pytest

from xtrader_bridge import atomic_io, csv_writer

# I link simbolici su Windows richiedono privilegi che la CI non ha: i test che ne creano
# uno si saltano lì. La logica pura di `atomic_io.risolvi`/`stesso_file` resta coperta.
richiede_link = pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt",
    reason="creare symlink richiede privilegi non garantiti su Windows")


def _riga_segnale():
    riga = {c: "" for c in csv_writer.CSV_HEADER}
    riga.update({"Provider": "PBet", "EventName": "Inter v Milan",
                 "MarketType": "MATCH_ODDS", "SelectionName": "Inter",
                 "Handicap": "0", "Price": "1.85", "BetType": "PUNTA"})
    return riga


def _righe_su_disco(path):
    with open(path, encoding=csv_writer.CSV_ENCODING) as f:
        return [r for r in f.read().strip().split("\n") if r]


# ─────────────────────── B7: la scrittura attraversa il link ────────────────────────

@richiede_link
def test_svuotare_un_csv_raggiunto_da_un_LINK_svuota_il_file_VERO(tmp_path):
    reale = str(tmp_path / "reale.csv")
    link = str(tmp_path / "link.csv")
    csv_writer.write_rows([_riga_segnale()], reale)
    os.symlink(reale, link)
    assert csv_writer.has_active_row(reale)          # premessa: c'è una riga stantia

    assert csv_writer.clear_stale_csv(link) is True

    # Il punto: `True` deve voler dire che la riga è DAVVERO sparita dal file vero.
    assert not csv_writer.has_active_row(reale), (
        "clear_stale_csv ha riportato «ripulito» ma la riga stantia è ancora nel file reale: "
        "XTrader la rileggerebbe come un segnale vivo")
    assert len(_righe_su_disco(reale)) == 1          # solo header


@richiede_link
def test_scrivere_attraverso_un_link_NON_lo_sostituisce_con_un_file(tmp_path):
    """L'altra metà del difetto: il link deve restare un link. Se viene sostituito, la
    prossima scrittura va a finire altrove e il file vero resta indietro per sempre."""
    reale = str(tmp_path / "reale.csv")
    link = str(tmp_path / "link.csv")
    csv_writer.init_csv(reale)
    os.symlink(reale, link)

    csv_writer.write_rows([_riga_segnale()], link)

    assert os.path.islink(link), "il link è stato sostituito da un file normale"
    assert os.path.samefile(link, reale)
    assert csv_writer.has_active_row(reale), "la riga è finita altrove, non nel file puntato"


@richiede_link
def test_scritture_ripetute_attraverso_il_link_restano_sul_file_VERO(tmp_path):
    """Regressione della regressione: basta che UNA scrittura sostituisca il link perché
    tutte le successive scrivano su un file diverso da quello che XTrader legge."""
    reale = str(tmp_path / "reale.csv")
    link = str(tmp_path / "link.csv")
    csv_writer.init_csv(reale)
    os.symlink(reale, link)

    for _ in range(3):
        csv_writer.write_rows([_riga_segnale()], link)
        csv_writer.clear_stale_csv(link)

    assert os.path.islink(link)
    assert os.path.samefile(link, reale)
    assert len(_righe_su_disco(reale)) == 1          # solo header, nessun accumulo


@richiede_link
def test_una_cartella_raggiunta_da_un_link_funziona_uguale(tmp_path):
    """Non solo il file: anche il caso in cui è la CARTELLA a essere un link."""
    vera = tmp_path / "vera"
    vera.mkdir()
    collegata = str(tmp_path / "collegata")
    os.symlink(str(vera), collegata)

    dentro_il_link = os.path.join(collegata, "segnali.csv")
    csv_writer.write_rows([_riga_segnale()], dentro_il_link)

    assert csv_writer.has_active_row(str(vera / "segnali.csv"))
    assert csv_writer.clear_stale_csv(dentro_il_link) is True
    assert not csv_writer.has_active_row(str(vera / "segnali.csv"))


# ───────────────────────── il file NON-bridge resta protetto ─────────────────────────

@richiede_link
def test_un_link_a_un_file_ESTRANEO_non_viene_toccato(tmp_path):
    """La guardia anti data-loss non deve indebolirsi risolvendo i link: se il file puntato
    non è un CSV del bridge, non si tocca — né il link né il file vero."""
    estraneo = tmp_path / "documento_dell_utente.csv"
    estraneo.write_text("colonna1,colonna2\nvalore,importante\n", encoding="utf-8")
    link = str(tmp_path / "link.csv")
    os.symlink(str(estraneo), link)

    assert csv_writer.clear_stale_csv(link) is False
    assert estraneo.read_text(encoding="utf-8") == "colonna1,colonna2\nvalore,importante\n"
    assert os.path.islink(link)


# ───────────────────────── la fonte unica e il suo FALLBACK ──────────────────────────

def test_risolvi_non_solleva_mai_su_un_path_impossibile(tmp_path):
    """Il fallback che il piano #194 chiede esplicitamente: «serve il fallback quando
    samefile solleva su file assente o lockato, o una guardia diventa un crash».

    `risolvi` deve restituire SEMPRE qualcosa di confrontabile, anche su path inesistenti,
    vuoti o malformati — mai sollevare, perché i suoi chiamanti sono guardie di sicurezza.
    """
    for caso in ["", "   ", str(tmp_path / "non" / "esiste" / "mai.csv"),
                 str(tmp_path), "relativo.csv", "\x00non-valido"]:
        risultato = atomic_io.risolvi(caso)
        assert isinstance(risultato, str)


def test_stesso_file_riconosce_il_link(tmp_path):
    reale = tmp_path / "a.csv"
    reale.write_text("x", encoding="utf-8")
    if hasattr(os, "symlink") and os.name != "nt":
        link = str(tmp_path / "b.csv")
        os.symlink(str(reale), link)
        assert atomic_io.stesso_file(link, str(reale)) is True
        assert atomic_io.stesso_file(str(reale), link) is True


def test_stesso_file_su_file_ASSENTI_ricade_sul_confronto_dei_path(tmp_path):
    """`os.path.samefile` SOLLEVA se un file non esiste. Le guardie che lo useranno vengono
    chiamate anche su path mai creati (csv_path appena digitato nella GUI) e su file
    lockati da XTrader: lì il fallback deve rispondere, non esplodere."""
    assente_a = str(tmp_path / "mai_creato.csv")
    assente_b = str(tmp_path / "nemmeno_questo.csv")

    assert atomic_io.stesso_file(assente_a, assente_a) is True      # stesso path
    assert atomic_io.stesso_file(assente_a, assente_b) is False     # path diversi
    # E la forma relativa/«.» dello stesso path assente resta riconosciuta come prima.
    assert atomic_io.stesso_file(
        assente_a, os.path.join(str(tmp_path), ".", "mai_creato.csv")) is True


def test_stesso_file_non_solleva_se_samefile_esplode(tmp_path, monkeypatch):
    """Il caso Windows che il piano chiama per nome: il file esiste ma è LOCKATO, e
    `samefile` solleva `OSError`. La guardia deve degradare al confronto dei path, non
    propagare — o «Crea CSV» diventerebbe un crash invece di un rifiuto."""
    a = tmp_path / "a.csv"
    a.write_text("x", encoding="utf-8")

    def esplode(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(atomic_io.os.path, "samefile", esplode)
    assert atomic_io.stesso_file(str(a), str(a)) is True
    assert atomic_io.stesso_file(str(a), str(tmp_path / "altro.csv")) is False


def test_stesso_file_su_input_vuoti_e_falso():
    for a, b in [("", ""), ("", "x.csv"), ("x.csv", ""), (None, None), (None, "x.csv")]:
        assert atomic_io.stesso_file(a, b) is False
