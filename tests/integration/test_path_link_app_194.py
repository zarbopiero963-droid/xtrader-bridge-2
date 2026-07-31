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


from tests.conftest import crea_symlink, richiede_link


def _csv_con_link(tmp_path, nome_reale="sessione.csv", nome_link="scorciatoia.csv"):
    reale = str(tmp_path / nome_reale)
    link = str(tmp_path / nome_link)
    csv_writer.init_csv(reale)
    crea_symlink(reale, link)
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
    crea_symlink(altro, link_ad_altro)
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
    # Un path MALFORMATO ora BLOCCA (era `False` prima del fail-closed di #203). È il
    # comportamento voluto e non un indebolimento del test: se non si può nemmeno
    # stabilire che cosa sia quel percorso, rifiutare «Crea CSV» è gratuito — la
    # creazione fallirebbe comunque — mentre procedere significherebbe decidere alla
    # cieca su un'azione distruttiva. La cosa che questo test verifica davvero, cioè che
    # la guardia NON esploda, continua a valere.
    assert a._is_active_session_csv("\x00path-non-valido") is True


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


# ══════════════════════════════════════════════════════════════════════════════════
# Bloccante di Fugu Ultra su #203, e il rilievo è più fine di come avevo dichiarato
# il residuo.
#
# La mia giustificazione per non rendere la guardia fail-closed era: «bloccherebbe la
# creazione di un CSV su un percorso NUOVO, dove `samefile` solleva solo perché il file
# non esiste ancora». Vero — ma copre il caso ASSENTE, non il caso ESISTENTE-ma-non-
# confrontabile (su Windows un file che XTrader tiene aperto, o su cui manca il permesso).
# Sono due situazioni diverse e le avevo trattate come una.
#
# La correzione non dipende da chi ha ragione sul lock di Windows: se la domanda
# autorevole non ha risposta **e il file esiste**, si blocca. Il percorso nuovo continua
# a funzionare perché lì il file NON esiste.
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_guardia_BLOCCA_se_il_file_ESISTE_ma_l_identita_non_e_verificabile(
        make_app, tmp_path, monkeypatch):
    from xtrader_bridge import atomic_io

    attivo = str(tmp_path / "sessione.csv")
    alias = str(tmp_path / "alias.csv")
    csv_writer.init_csv(attivo)
    csv_writer.init_csv(alias)          # ESISTE, ma non sapremo dire se è lo stesso file
    a = make_app(csv_path=attivo, running=True)

    def samefile_muto(*_args, **_kwargs):
        raise OSError(13, "Permission denied")   # file lockato / permesso negato

    monkeypatch.setattr(atomic_io.os.path, "samefile", samefile_muto)

    assert a._is_active_session_csv(alias) is True, (
        "il file esiste ma non si è potuto stabilire se è il CSV attivo: la guardia deve "
        "bloccare, non tirare a indovinare — «Crea CSV» lo troncherebbe")


def test_ma_un_percorso_NUOVO_resta_creabile_anche_se_samefile_tace(
        make_app, tmp_path, monkeypatch):
    """La controprova che rende la correzione accettabile: il caso più comune — creare un
    CSV su un percorso che non esiste ancora — NON deve essere bloccato. È lì che
    `samefile` solleva per il motivo più innocuo che ci sia."""
    from xtrader_bridge import atomic_io

    attivo = str(tmp_path / "sessione.csv")
    csv_writer.init_csv(attivo)
    a = make_app(csv_path=attivo, running=True)

    def samefile_muto(*_args, **_kwargs):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(atomic_io.os.path, "samefile", samefile_muto)

    nuovo = str(tmp_path / "mai_creato.csv")          # NON esiste
    assert a._is_active_session_csv(nuovo) is False


def test_il_confronto_autorevole_distingue_i_tre_esiti(tmp_path, monkeypatch):
    """`confronto_autorevole` è tri-stato: sì / no / **non lo so**. È la distinzione che
    mancava — `stesso_file` collassava «non lo so» su «no», e un «no» inventato su una
    guardia di sicurezza è la direzione sbagliata."""
    from xtrader_bridge import atomic_io

    uno = tmp_path / "uno.csv"
    uno.write_text("x", encoding="utf-8")
    due = tmp_path / "due.csv"
    due.write_text("y", encoding="utf-8")

    assert atomic_io.confronto_autorevole(str(uno), str(uno)) is True
    assert atomic_io.confronto_autorevole(str(uno), str(due)) is False

    def muto(*_a, **_k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(atomic_io.os.path, "samefile", muto)
    assert atomic_io.confronto_autorevole(str(uno), str(due)) is None


# ══════════════════════════════════════════════════════════════════════════════════
# Bloccante di Fable 5 su #203: il mio fail-closed era ILLUSORIO.
#
# `os.path.exists()` NON solleva — assorbe l'errore e ritorna `False` (verificato:
# `exists('/tmp/\\x00x.csv')` → False, mentre `os.stat` sullo stesso path solleva
# ValueError). Quindi il ramo `except (OSError, ValueError): return True` era codice
# MORTO, e su un file esistente ma non ispezionabile — ACL Windows, il caso che la
# correzione dichiarava di coprire — la guardia rispondeva `False` e NON bloccava.
#
# Serve `os.stat`, che distingue: `FileNotFoundError` = assente (percorso nuovo, si
# può creare) da qualunque altro errore = non ispezionabile (si blocca).
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_guardia_BLOCCA_se_il_file_non_e_nemmeno_ISPEZIONABILE(
        make_app, tmp_path, monkeypatch):
    from xtrader_bridge import atomic_io

    attivo = str(tmp_path / "sessione.csv")
    csv_writer.init_csv(attivo)
    altro = str(tmp_path / "altro.csv")
    csv_writer.init_csv(altro)
    a = make_app(csv_path=attivo, running=True)

    monkeypatch.setattr(atomic_io.os.path, "samefile",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError(13, "Permission denied")))

    # `stat` che fallisce per PERMESSI (non per assenza): il file c'è, non lo si può
    # ispezionare. È il caso ACL di Windows.
    vero_stat = os.stat

    def stat_negato(percorso, *args, **kwargs):
        if str(percorso) == altro:
            raise PermissionError(13, "Permission denied")
        return vero_stat(percorso, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat_negato)

    assert a._is_active_session_csv(altro) is True, (
        "il file non è ispezionabile: la guardia deve bloccare. Con `os.path.exists` "
        "rispondeva False, perché exists() assorbe l'errore invece di sollevarlo")


def test_un_percorso_ASSENTE_resta_creabile_anche_con_samefile_muto(
        make_app, tmp_path, monkeypatch):
    """La distinzione che rende accettabile il fail-closed: `FileNotFoundError` significa
    «non c'è nulla da troncare», ed è il caso più comune (creare un CSV nuovo)."""
    from xtrader_bridge import atomic_io

    attivo = str(tmp_path / "sessione.csv")
    csv_writer.init_csv(attivo)
    a = make_app(csv_path=attivo, running=True)

    monkeypatch.setattr(atomic_io.os.path, "samefile",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError(2, "No such file")))

    assert a._is_active_session_csv(str(tmp_path / "mai_creato.csv")) is False


def test_SCELTA_DICHIARATA_se_il_CSV_ATTIVO_sparisce_la_guardia_blocca_di_piu(
        make_app, tmp_path):
    """Secondo rilievo di Fable: se il CSV **attivo** viene cancellato a sessione viva,
    `samefile` solleva per lui e la guardia blocca la creazione su qualsiasi path
    esistente diverso.

    È over-blocking, ed è **voluto**: a bridge avviato con l'attivo sparito lo stato è già
    anomalo, e rifiutare «Crea CSV» costa un click (STOP e si riprova) mentre permetterlo
    può costare un segnale. Pinnato qui perché sia una scelta e non una sorpresa.
    """
    attivo = str(tmp_path / "sessione.csv")
    altro = str(tmp_path / "altro.csv")
    csv_writer.init_csv(altro)
    a = make_app(csv_path=attivo, running=True)      # `attivo` NON creato

    assert a._is_active_session_csv(altro) is True
    # Ma un percorso ANCHE lui assente resta creabile: nulla da proteggere.
    assert a._is_active_session_csv(str(tmp_path / "nuovo.csv")) is False
