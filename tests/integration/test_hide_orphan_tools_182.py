"""Nascondimento degli strumenti orfani di una sorgente dati — #182 PR N.

**Perché esistono.** Tre pezzi di GUI leggono il **DB Betfair locale**, che senza il «Betfair
Sync» (rimosso) resta **vuoto e non popolabile dall'app**: `upsert_sport`/`upsert_competition`/
`upsert_event` esistono ma non hanno alcun chiamante nel codice di prodotto. All'utente
apparivano *rotti*, e il messaggio «Popola il dizionario locale, poi riprova» chiedeva una cosa
impossibile. Sono stati **nascosti**:

- la scheda **«🧹 Nomi squadra»** dell'hub Strumenti;
- la sotto-scheda **«🌳 Mapping guidato»** del pannello Mapping;
- il pulsante **«📥 Precompila da Betfair»** del pannello «⚽ Calcio».

**Nascondere non è rimuovere.** Etichette, pannelli, factory, metodi, DB e resolver restano
tutti: la riattivazione deve costare poche righe quando tornerà una sorgente dati. Perciò ogni
test qui ha **due metà**: la scheda/il pulsante non si vede più **E** il codice sottostante c'è
ancora. Una metà sola lascerebbe passare la cancellazione per errore.

La ritenzione è **verificata** (file su disco, sorgente ispezionata, metodo risolto), non
asserita a parole: un test che dicesse solo «è ritenuto» non si accorgerebbe di nulla.
"""

import ast
import importlib
import inspect
import os
import sys
import types

import pytest

import xtrader_bridge


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota.

    Stesso pattern di `tests/unit/test_name_mapping_gui_prefill.py`: i moduli GUI importano
    tkinter e non sono importabili headless, ma la logica sotto test è quella vera."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


def _importa_gui(monkeypatch, nome):
    """Importa un modulo GUI sotto un finto `customtkinter`, e lo TOGLIE da `sys.modules` a fine
    test.

    Il `try/except` conta: dove `customtkinter` è installato davvero (Windows CI) il finto **non
    viene mai messo**, quindi il modulo che resta in cache è quello vero. Il finto esiste solo
    dove tkinter manca — cioè la CI Linux, dove nessun test può comunque usare widget veri.

    La rimozione a teardown è la risposta al rilievo Fable (#222): `monkeypatch` ripristina la
    voce `customtkinter`, ma il modulo GUI **importato** resterebbe in cache costruito sulle
    classi finte. Qui lo si toglie, così l'ordine di esecuzione non conta."""
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, nome, raising=False)
    mod = importlib.import_module(nome)
    yield mod
    sys.modules.pop(nome, None)


@pytest.fixture()
def name_mapping_mod(monkeypatch):
    yield from _importa_gui(monkeypatch, "xtrader_bridge.name_mapping_gui")


@pytest.fixture()
def tools_mod(monkeypatch):
    yield from _importa_gui(monkeypatch, "xtrader_bridge.tools_gui")


def _bottoni_costruiti(func) -> list:
    """Etichette dei `CTkButton` davvero COSTRUITI in `func`, via AST.

    Non è una ricerca testuale: legge l'albero sintattico e prende l'argomento `text=` di ogni
    chiamata a `CTkButton`. Un pulsante commentato non è una chiamata, quindi non compare —
    e un refactor che cambia indentazione o spezza la riga non altera il risultato (rilievo
    CodeRabbit/Sourcery/GPT-5.5 sulla fragilità del match su stringhe).

    `i18n.tr("…")` è srotolato al suo argomento: nel sorgente le etichette sono avvolte lì."""
    import textwrap
    albero = ast.parse(textwrap.dedent(inspect.getsource(func)))
    etichette = []
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "CTkButton"):
            continue
        for kw in n.keywords:
            if kw.arg != "text":
                continue
            v = kw.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "tr" and v.args):
                v = v.args[0]
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                etichette.append(v.value)
    return etichette


def _pkg_path(*parti):
    return os.path.join(os.path.dirname(xtrader_bridge.__file__), *parti)


# ── 🧹 Nomi squadra ──────────────────────────────────────────────────────────────────

def test_known_teams_fuori_dalle_schede_ma_RITENUTA(tools_mod):
    """Fail-first: prima della patch «known_teams» era nel gruppo ③ e la scheda si vedeva."""
    grouped = [k for _p, _n, keys in tools_mod.TOOL_GROUPS for k in keys]
    assert "known_teams" not in grouped, (
        "la scheda «🧹 Nomi squadra» è tornata visibile: legge il DB Betfair, che è vuoto")

    # RITENUTA — le tre prove che la riattivazione è ancora possibile:
    assert tools_mod.TOOL_TITLES.get("known_teams") == "🧹 Nomi squadra"   # etichetta e traduzioni
    assert os.path.exists(_pkg_path("known_teams_gui.py"))                 # pannello su disco
    from xtrader_bridge import app as app_mod  # factory cablata
    src = inspect.getsource(app_mod.App._open_tools)
    assert '"known_teams":' in src, (
        "la factory di known_teams è sparita da app.py: la scheda non è più riattivabile "
        "con una riga in TOOL_GROUPS")


# ── 🌳 Mapping guidato ───────────────────────────────────────────────────────────────

def test_mapping_ha_esattamente_due_sottoschede(name_mapping_mod, monkeypatch):
    """Le sotto-schede del Mapping sono ⚽ Calcio e 🎯 Mercati, e nient'altro.

    **Esegue il vero `MappingPanel.__init__`** con una spia su `CTkTabview.add` e registra i
    titoli davvero aggiunti (rilievo CodeRabbit #222: il primo giro leggeva il *testo* del
    sorgente, quindi si rompeva su un refactor innocuo e non provava il comportamento).
    Stesso pattern delle spie già usate in `test_running_edit_wiring_176.py`.

    Fail-first: prima della patch i titoli aggiunti erano tre."""
    mod = name_mapping_mod
    aggiunte = []

    def _spia_pannello(nome):
        def _fake(parent, *a, **k):
            return types.SimpleNamespace(pack=lambda **kk: None, _quale=nome)
        return _fake

    monkeypatch.setattr(mod, "NameMappingPanel", _spia_pannello("calcio"))
    monkeypatch.setattr(mod, "MarketMappingPanel", _spia_pannello("mercati"))
    tabs = types.SimpleNamespace(add=lambda titolo: aggiunte.append(titolo) or None,
                                 pack=lambda **k: None)
    monkeypatch.setattr(mod.ctk, "CTkTabview", lambda master: tabs, raising=False)
    monkeypatch.setattr(mod.ctk.CTkFrame, "__init__", lambda self, *a, **k: None, raising=False)

    finto = object.__new__(mod.MappingPanel)
    mod.MappingPanel.__init__(finto, None)

    assert aggiunte == ["⚽ Calcio", "🎯 Mercati"], (
        f"sotto-schede davvero costruite: {aggiunte}")
    assert finto._guidato is None, (
        "«🌳 Mapping guidato» è tornata attiva: legge il DB Betfair vuoto")


def test_guided_mapping_RITENUTO():
    """Il pannello guidato non è stato cancellato: file, classe e provider restano."""
    assert os.path.exists(_pkg_path("guided_mapping_gui.py"))
    assert os.path.exists(_pkg_path("betfair", "guided_mapping.py"))

    from xtrader_bridge import app as app_mod
    src = inspect.getsource(app_mod.App._open_tools)
    # I provider restano cablati: riattivare la sotto-scheda non deve richiedere di ricablare app.py.
    assert "competitions_provider=" in src and "teams_provider=" in src, (
        "i provider Betfair sono spariti da app.py: riattivare il Mapping guidato non sarebbe "
        "più una modifica locale a name_mapping_gui")


def test_mapping_refresh_non_esplode_senza_la_sottoscheda_guidata(name_mapping_mod):
    """**Il consumatore, non il sito** (regola 2-bis).

    `MappingPanel.refresh` inoltrava a tutte e tre le aree, `self._guidato` inclusa. Nascondere
    la sotto-scheda senza toccare `refresh` lascia `self._guidato = None` e fa sollevare
    `AttributeError` a OGNI refresh del Mapping — un pannello rotto, non una scheda in meno.

    Fail-first: sul codice pre-patch questa chiamata sollevava
    `AttributeError: 'NoneType' object has no attribute 'refresh'`."""
    visti = []
    finto = types.SimpleNamespace(
        _calcio=types.SimpleNamespace(refresh=lambda cfg: visti.append(("calcio", cfg))),
        _mercati=types.SimpleNamespace(refresh=lambda cfg: visti.append(("mercati", cfg))),
        _guidato=None,
    )

    name_mapping_mod.MappingPanel.refresh(finto, {"name_mappings": {"p": []}})

    assert [nome for nome, _ in visti] == ["calcio", "mercati"], (
        "il refresh deve raggiungere le due aree ancora visibili")


# ── 📥 Precompila da Betfair ─────────────────────────────────────────────────────────

def test_pulsante_precompila_nascosto_ma_metodo_RITENUTO(name_mapping_mod):
    """Fail-first: prima della patch il pulsante era costruito in `NameMappingPanel._build_ui`.

    ⚠️ Il primo giro di questo test ispezionava `__init__`, dove il pulsante **non è mai stato**:
    passava sul codice pre-patch, cioè non provava niente. La funzione giusta è `_build_ui`, ed
    è per questo che il fail-first va **eseguito** e non dato per scontato."""
    bottoni = _bottoni_costruiti(name_mapping_mod.NameMappingPanel._build_ui)
    assert bottoni, "nessun CTkButton trovato: la scansione AST non funziona più"
    assert "📥 Precompila da Betfair" not in bottoni, (
        "il pulsante «📥 Precompila da Betfair» è tornato attivo: precompila dal DB Betfair, "
        f"che è vuoto e non popolabile dall'app. Pulsanti costruiti: {bottoni}")
    # controprova: gli altri due pulsanti della stessa barra ci sono ancora, quindi il test
    # non passa perché la scansione ha smesso di vedere qualunque cosa.
    assert "➕ Aggiungi riga" in bottoni and "💾 Salva profilo" in bottoni, bottoni

    # RITENUTO: il metodo è ancora risolvibile e chiamabile — non un commento, un attributo vero.
    assert callable(getattr(name_mapping_mod.NameMappingPanel, "_prefill_betfair_names", None)), (
        "`_prefill_betfair_names` è stato cancellato: il pulsante non sarebbe più riattivabile")


def test_le_etichette_i18n_delle_parti_nascoste_restano():
    """Le traduzioni non vanno potate insieme alla visibilità: servono alla riattivazione, e
    toglierle renderebbe la scheda riattivata monolingue."""
    from xtrader_bridge import i18n

    # Salva e RIPRISTINA la lingua vera invece di forzare "IT" a fine test (rilievo Sourcery
    # #222): rimettere una costante avrebbe lasciato la suite in uno stato diverso da quello in
    # cui l'ha trovata, creando dipendenza dall'ordine — il difetto che questo test non deve avere.
    lingua_prima = i18n.get_language()
    try:
        i18n.set_language("EN")
        assert i18n.tr("🧹 Nomi squadra") != "🧹 Nomi squadra"      # tradotta, non identità
        assert i18n.tr("📥 Precompila da Betfair") != "📥 Precompila da Betfair"
    finally:
        i18n.set_language(lingua_prima)
