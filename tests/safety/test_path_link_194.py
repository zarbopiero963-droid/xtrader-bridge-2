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


from tests.conftest import crea_symlink, richiede_hardlink, richiede_link


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
    crea_symlink(reale, link)
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
    crea_symlink(reale, link)

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
    crea_symlink(reale, link)

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
    crea_symlink(str(vera), collegata)

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
    crea_symlink(str(estraneo), link)

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


@richiede_link
def test_stesso_file_riconosce_il_link(tmp_path):
    reale = tmp_path / "a.csv"
    reale.write_text("x", encoding="utf-8")
    link = str(tmp_path / "b.csv")
    crea_symlink(str(reale), link)

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


# ══════════════════════════════════════════════════════════════════════════════════
# LIMITE DICHIARATO — gli hard link (rilievo Fugu Ultra su #203).
#
# `realpath` risolve i link SIMBOLICI e le junction, non gli hard link: quelli non sono
# un puntatore da seguire, sono due voci di directory per lo stesso inode. `os.replace`
# ne sostituisce una e l'altro nome resta col contenuto vecchio.
#
# Non si corregge, e la ragione è uno scambio: l'unico modo di scrivere attraverso un
# hard link è scrivere IN PLACE, cioè rinunciare all'atomicità. Un crash a metà
# scrittura lascerebbe a XTrader un CSV troncato — una scommessa malformata invece di
# una configurazione insolita. Questi test PINNANO il comportamento reale, così è
# dichiarato e non scoperto per caso da chi ci inciampa.
# ══════════════════════════════════════════════════════════════════════════════════

@richiede_hardlink
def test_LIMITE_gli_hard_link_non_sono_attraversati_dalla_scrittura(tmp_path):
    bridge_scrive = str(tmp_path / "bridge.csv")
    altro_nome = str(tmp_path / "altro_nome.csv")
    csv_writer.write_rows([_riga_segnale()], bridge_scrive)
    try:
        os.link(bridge_scrive, altro_nome)
    except OSError:
        pytest.skip("hard link non consentiti qui")

    assert os.stat(bridge_scrive).st_ino == os.stat(altro_nome).st_ino   # premessa

    csv_writer.clear_stale_csv(bridge_scrive)

    assert not csv_writer.has_active_row(bridge_scrive)
    # IL LIMITE: l'altro nome conserva il contenuto vecchio. Se questo assert diventasse
    # rosso, qualcuno ha reso la scrittura hard-link-aware — e va verificato che NON
    # l'abbia fatto rinunciando all'atomicità.
    assert csv_writer.has_active_row(altro_nome), (
        "comportamento cambiato: la scrittura ora attraversa gli hard link. Verificare che "
        "l'atomicità (tmp + os.replace) sia ancora garantita e aggiornare la documentazione")
    assert os.stat(bridge_scrive).st_ino != os.stat(altro_nome).st_ino


@richiede_hardlink
def test_le_GUARDIE_invece_riconoscono_gli_hard_link(tmp_path):
    """L'asimmetria è voluta: il writer non li attraversa, le guardie sì. Bloccano di più,
    e bloccare è la direzione sicura — «Crea CSV» su un hard link al CSV attivo va
    rifiutato anche se la scrittura, in altro contesto, non lo attraverserebbe."""
    uno = str(tmp_path / "uno.csv")
    due = str(tmp_path / "due.csv")
    csv_writer.init_csv(uno)
    try:
        os.link(uno, due)
    except OSError:
        pytest.skip("hard link non consentiti qui")

    assert atomic_io.stesso_file(uno, due) is True
    # E `risolvi` da solo NON basta: è esattamente il motivo per cui `stesso_file` prova
    # `samefile` PRIMA di ricadere sul confronto dei path.
    assert atomic_io.risolvi(uno) != atomic_io.risolvi(due)


# ══════════════════════════════════════════════════════════════════════════════════
# Major di CodeRabbit su #203 — una REGRESSIONE introdotta da questa stessa PR.
#
# Risolvendo la destinazione, `atomic_write` ha spostato i temporanei nella cartella
# del file VERO. Ma `sweep_orphan_temps` continuava a guardare la cartella del LINK:
#
#   atomic_write crea i tmp in: .../vera
#   sweep_orphan_temps guarda : .../dove_punta_config
#   orfani rimossi: 0          ← si accumulano a ogni crash, per sempre
#
# Prima non succedeva: i tmp nascevano accanto al link e lo sweep li trovava. È lo
# stesso schema del Major sulla #202 — ho cambiato dove una funzione SCRIVE senza
# guardare chi altro dipendeva da quella posizione.
# ══════════════════════════════════════════════════════════════════════════════════

@richiede_link
def test_lo_sweep_trova_gli_orfani_accanto_al_FILE_VERO(tmp_path):
    cartella_vera = tmp_path / "vera"
    cartella_vera.mkdir()
    cartella_config = tmp_path / "dove_punta_config"
    cartella_config.mkdir()

    csv_vero = str(cartella_vera / "segnali.csv")
    csv_path = str(cartella_config / "link.csv")     # ← quello scritto in config
    csv_writer.init_csv(csv_vero)
    crea_symlink(csv_vero, csv_path)

    # Orfano com'è lasciato da un crash TRA `mkstemp` e il rename: sta dove
    # `atomic_write` crea i temporanei, cioè accanto al file VERO.
    orfano = cartella_vera / (csv_writer._CSV_TMP_PREFIX + "crash" + csv_writer._CSV_TMP_SUFFIX)
    orfano.write_text("", encoding="utf-8")

    assert csv_writer.sweep_orphan_temps(csv_path) == 1
    assert not orfano.exists(), (
        "l'orfano resta accanto al file vero: lo sweep guarda la cartella del link e non lo "
        "trova, quindi si accumula a ogni crash")


@richiede_link
def test_lo_sweep_trova_anche_gli_orfani_LASCIATI_DALLA_VERSIONE_PRECEDENTE(tmp_path):
    """Chi aggiorna ha già orfani accanto al LINK, lasciati dal comportamento vecchio.
    Se lo sweep guardasse solo la cartella risolta, resterebbero lì per sempre: la
    correzione deve ripulire entrambe."""
    cartella_vera = tmp_path / "vera"
    cartella_vera.mkdir()
    cartella_config = tmp_path / "dove_punta_config"
    cartella_config.mkdir()

    csv_vero = str(cartella_vera / "segnali.csv")
    csv_path = str(cartella_config / "link.csv")
    csv_writer.init_csv(csv_vero)
    crea_symlink(csv_vero, csv_path)

    vecchio = cartella_config / (csv_writer._CSV_TMP_PREFIX + "vecchio" + csv_writer._CSV_TMP_SUFFIX)
    nuovo = cartella_vera / (csv_writer._CSV_TMP_PREFIX + "nuovo" + csv_writer._CSV_TMP_SUFFIX)
    vecchio.write_text("", encoding="utf-8")
    nuovo.write_text("", encoding="utf-8")

    assert csv_writer.sweep_orphan_temps(csv_path) == 2
    assert not vecchio.exists() and not nuovo.exists()


def test_lo_sweep_non_conta_due_volte_quando_le_cartelle_COINCIDONO(tmp_path):
    """Controprova: senza link le due cartelle sono la stessa, e lo sweep non deve
    passarci due volte (né contare doppio, né rimuovere ciò che ha già rimosso)."""
    csv_path = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(csv_path)
    orfano = tmp_path / (csv_writer._CSV_TMP_PREFIX + "solo" + csv_writer._CSV_TMP_SUFFIX)
    orfano.write_text("", encoding="utf-8")

    assert csv_writer.sweep_orphan_temps(csv_path) == 1
    assert csv_writer.sweep_orphan_temps(csv_path) == 0      # idempotente


@richiede_hardlink
def test_LIMITE_le_guardie_NON_riconoscono_un_hard_link_se_samefile_non_risponde(tmp_path, monkeypatch):
    """Il secondo Major di CodeRabbit, e ha ragione: avevo scritto che «le guardie
    riconoscono gli hard link», senza qualificare.

    `stesso_file` prova `samefile` — che li riconosce — ma se solleva (file assente o
    lockato su Windows) ricade su `risolvi`, e `realpath` NON unifica gli hard link.
    In quel ramo due alias hard-link risultano file diversi. È un residuo reale e va
    pinnato, non dichiarato risolto.
    """
    uno = str(tmp_path / "uno.csv")
    due = str(tmp_path / "due.csv")
    csv_writer.init_csv(uno)
    try:
        os.link(uno, due)
    except OSError:
        pytest.skip("hard link non consentiti qui")

    assert atomic_io.stesso_file(uno, due) is True          # con samefile disponibile

    def samefile_lockato(*_a, **_k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(atomic_io.os.path, "samefile", samefile_lockato)
    assert atomic_io.stesso_file(uno, due) is False, (
        "comportamento cambiato: se ora gli hard link sono riconosciuti anche senza "
        "samefile, aggiornare la documentazione che dichiara questo limite")
