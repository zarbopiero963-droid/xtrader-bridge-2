"""B8 (#194 · PR-F, audit #188) — le guardie dell'app non risolvevano i link.

`_is_active_session_csv` confrontava `normcase`+`abspath`. Un link al CSV della sessione
ATTIVA non veniva riconosciuto come lo stesso file, quindi la guardia non scattava e
«Crea CSV» **troncava il CSV vivo**, cancellando un segnale che XTrader non aveva ancora
letto. Misurato sul codice pre-patch:

```text
stesso path           → True
LINK allo stesso file → False        ← la guardia non scatta
os.path.samefile(link, reale) → True
```

Lo stesso difetto, nello stesso verso, viveva in `_same_csv_path`: se dice «diverso» per un
link, `_retry_stop_clear` crede che nessuna sessione possieda il path e **cancella la riga
viva** della sessione nuova. Il docstring dichiarava il limite come accettabile perché «nel
runtime non esiste alcun percorso che crei o attraversi link» — l'audit #188 mostra che
`csv_path` è un campo di testo e l'assunzione non regge.

Le guardie devono anche **non diventare un crash**: `samefile` solleva su file assente o
lockato, ed è il caso ordinario per un `csv_path` appena digitato o tenuto aperto da
XTrader. Il fallback è coperto qui e in `tests/safety/test_path_link_194.py`.
"""

import os

import pytest

from xtrader_bridge import csv_writer, dirty_csv_store

richiede_link = pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt",
    reason="creare symlink richiede privilegi non garantiti su Windows")


def _csv_con_link(tmp_path, nome_reale="sessione.csv", nome_link="scorciatoia.csv"):
    reale = str(tmp_path / nome_reale)
    link = str(tmp_path / nome_link)
    csv_writer.init_csv(reale)
    os.symlink(reale, link)
    return reale, link


# ───────────────── la guardia che protegge il CSV della sessione ATTIVA ──────────────

@richiede_link
def test_la_guardia_riconosce_il_CSV_ATTIVO_raggiunto_da_un_LINK(make_app, tmp_path):
    reale, link = _csv_con_link(tmp_path)
    a = make_app(csv_path=reale, running=True)

    assert a._is_active_session_csv(link) is True, (
        "la guardia non riconosce il link → «Crea CSV» troncherebbe il CSV della sessione VIVA")


@richiede_link
def test_crea_CSV_e_RIFIUTATO_su_un_link_al_CSV_della_sessione_attiva(make_app, tmp_path):
    """Non la guardia isolata, ma l'effetto che conta: il file vivo non deve essere toccato."""
    reale, link = _csv_con_link(tmp_path)
    riga = {c: "" for c in csv_writer.CSV_HEADER}
    riga.update({"Provider": "PBet", "EventName": "Inter v Milan", "MarketType": "MATCH_ODDS",
                 "SelectionName": "Inter", "Handicap": "0", "Price": "1.85", "BetType": "PUNTA"})
    csv_writer.write_rows([riga], reale)

    a = make_app(csv_path=reale, running=True)
    assert a._create_and_save_csv(link, force=True) is False, (
        "«Crea CSV» è passato su un link al CSV attivo — nemmeno `force` deve bypassare "
        "questa guardia")
    assert csv_writer.has_active_row(reale), "il segnale della sessione VIVA è stato cancellato"


@richiede_link
def test_la_guardia_NON_scatta_su_un_file_davvero_diverso(make_app, tmp_path):
    """Controprova: risolvere i link non deve far bloccare tutto. Un CSV diverso resta
    creabile mentre il bridge gira, altrimenti la correzione sarebbe una regressione d'uso."""
    reale, _link = _csv_con_link(tmp_path)
    altro = str(tmp_path / "un_altro.csv")
    a = make_app(csv_path=reale, running=True)

    assert a._is_active_session_csv(altro) is False
    # Anche un link a un file DIVERSO deve restare fuori dalla guardia: il criterio è
    # «è lo stesso file?», non «è un link?».
    link_ad_altro = str(tmp_path / "link_ad_altro.csv")
    csv_writer.init_csv(altro)
    os.symlink(altro, link_ad_altro)
    assert a._is_active_session_csv(link_ad_altro) is False


def test_la_guardia_resta_inattiva_a_bridge_FERMO(make_app, tmp_path):
    """L'altra controprova: la guardia vale solo a bridge AVVIATO. A STOP il CSV si ricrea."""
    reale = str(tmp_path / "sessione.csv")
    csv_writer.init_csv(reale)
    a = make_app(csv_path=reale, running=False)

    assert a._is_active_session_csv(reale) is False


def test_la_guardia_non_esplode_su_un_path_inesistente_o_malformato(make_app, tmp_path):
    """`samefile` solleva su file assente: la guardia deve rispondere, non propagare."""
    reale = str(tmp_path / "sessione.csv")      # MAI creato
    a = make_app(csv_path=reale, running=True)

    assert a._is_active_session_csv(reale) is True          # stesso path, entrambi assenti
    assert a._is_active_session_csv(str(tmp_path / "altro.csv")) is False
    assert a._is_active_session_csv("") is False
    assert a._is_active_session_csv("\x00path-non-valido") is False


# ──────────────── il possesso del retry post-STOP: stesso verso, altro sito ───────────

@richiede_link
def test_il_retry_post_stop_riconosce_il_link_e_NON_cancella_la_riga_viva(make_app, tmp_path):
    reale, link = _csv_con_link(tmp_path)
    a = make_app(csv_path=reale, running=True)

    assert a._same_csv_path(link, reale) is True, (
        "il retry post-STOP crederebbe che nessuna sessione possieda il path e cancellerebbe "
        "la riga viva della sessione nuova")


@richiede_link
def test_due_nomi_dello_stesso_CSV_danno_UNA_sola_catena_di_retry(make_app, tmp_path):
    """`_stop_clear_key` prometteva nel suo docstring «mai due catene per lo stesso CSV»,
    ma due nomi dello stesso file davano due chiavi diverse — quindi due catene."""
    reale, link = _csv_con_link(tmp_path)
    a = make_app(csv_path=reale, running=True)

    assert a._stop_clear_key(reale) == a._stop_clear_key(link)


def test_il_confronto_del_retry_resta_quello_di_prima_sui_casi_ordinari(make_app, tmp_path):
    """Controprova sui casi che il confronto copriva già: forma relativa, «.», path
    diversi, vuoti. Nessuno deve cambiare esito."""
    a = make_app(csv_path=None, running=False)
    uno = str(tmp_path / "out.csv")

    assert a._same_csv_path(uno, os.path.join(str(tmp_path), ".", "out.csv")) is True
    assert a._same_csv_path(uno, str(tmp_path / "sub" / ".." / "out.csv")) is True
    assert a._same_csv_path(uno, str(tmp_path / "diverso.csv")) is False
    assert a._same_csv_path(uno, "") is False
    assert a._same_csv_path("", "") is False
    assert a._same_csv_path(uno, None) is False


# ─────────────────────── il marker «CSV sporco» deduplicato ──────────────────────────

@richiede_link
def test_il_marker_csv_sporco_vede_UN_solo_file_dietro_due_nomi(tmp_path):
    """Due marker per lo stesso CSV significano che uno viene pulito e l'altro resta: al
    riavvio l'app crede che ci sia un crash da recuperare su un file già a posto."""
    reale, link = _csv_con_link(tmp_path)

    assert dirty_csv_store._norm(reale) == dirty_csv_store._norm(link)


def test_il_marker_csv_sporco_non_confonde_file_diversi(tmp_path):
    a = str(tmp_path / "a.csv")
    b = str(tmp_path / "b.csv")

    assert dirty_csv_store._norm(a) != dirty_csv_store._norm(b)
    assert dirty_csv_store._norm("") == ""
    assert dirty_csv_store._norm(None) == ""
