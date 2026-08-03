"""📇 Provider — marcatori d'uso per riga (#182 PR E).

L'elenco dei provider era già a vista, ma non diceva **quali parser dipendono** da ciascuna
voce. Il pulsante «🗑 Rimuovi» sta accanto a ogni riga, quindi la domanda «cosa rompo?» si pone
esattamente lì — e finora l'unica risposta era «è permanente».

Due differenze deliberate rispetto ai marcatori dei dizionari (PR B/C):

1. **lo zero si SCRIVE** («— non usato»). Nei dizionari «🧩 0» sarebbe rumore, perché un profilo
   appena creato e non ancora collegato è normale. Qui invece *non usato* è precisamente la
   condizione che rende la rimozione sicura: è l'informazione più utile della riga.
2. il confronto è **case-insensitive e senza spazi ai bordi**, come `provider_store`: un parser
   che scrive «Bet365 » dipende dalla voce «Bet365», e dirlo «non usato» sarebbe un falso
   rassicurante subito prima di una rimozione.
"""

import importlib
import json
import os
import sys
import types

import pytest

from xtrader_bridge import custom_parser


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def pg(monkeypatch):
    """Il modulo `provider_gui` importabile headless (customtkinter finto se assente)."""
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.provider_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.provider_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.provider_gui", None)


def _scrivi_parser(dir_path, nome, regole):
    """Scrive un parser salvato con le `regole` date (liste di dict `FieldRule`)."""
    with open(os.path.join(dir_path, f"{nome}.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": nome, "mode": "NAME_ONLY", "rules": regole}, fh)


def _regola_provider(valore):
    return {"target": "Provider", "fixed_value": valore}


# ── la mappa d'uso ──────────────────────────────────────────────────────────────────

def test_provider_usage_mappa_i_parser_che_fissano_il_provider(tmp_path):
    """Fail-first: `provider_usage` non esisteva."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", [_regola_provider("Bet365")])
    _scrivi_parser(d, "B", [_regola_provider("Bet365")])
    _scrivi_parser(d, "C", [_regola_provider("Pinnacle")])

    assert custom_parser.provider_usage(d) == {"Bet365": ["A", "B"], "Pinnacle": ["C"]}


def test_una_regola_che_ESTRAE_il_provider_non_conta(tmp_path):
    """Una regola con delimitatori e senza `fixed_value` legge il provider **dal messaggio**:
    non fissa un nome, quindi non dipende da una voce dell'anagrafica. Contarla direbbe che
    eliminare «Bet365» rompe un parser che non l'ha mai nominato."""
    d = str(tmp_path)
    _scrivi_parser(d, "Estrae", [{"target": "Provider",
                                  "start_after": "Fonte:", "end_before": "\n"}])
    assert custom_parser.provider_usage(d) == {}


def test_una_regola_su_altra_colonna_non_conta(tmp_path):
    """`fixed_value="Bet365"` su una colonna diversa da Provider non è un uso del provider."""
    d = str(tmp_path)
    _scrivi_parser(d, "Altrove", [{"target": "EventName", "fixed_value": "Bet365"}])
    assert custom_parser.provider_usage(d) == {}


def test_lo_stesso_parser_conta_UNA_volta_anche_con_regole_ripetute(tmp_path):
    """Stessa scelta di `_profile_usage` (e stessa ragione della regressione corretta nella
    PR #226): il marcatore conta **quanti parser dipendono**, non quante righe lo nominano."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", [_regola_provider("Bet365"), _regola_provider("Bet365")])
    assert custom_parser.provider_usage(d) == {"Bet365": ["A"]}


def test_un_parser_corrotto_non_fa_sparire_i_marcatori_degli_altri(tmp_path):
    d = str(tmp_path)
    _scrivi_parser(d, "Buono", [_regola_provider("Bet365")])
    with open(os.path.join(d, "Rotto.json"), "w", encoding="utf-8") as fh:
        fh.write("{ non e' json")
    assert custom_parser.provider_usage(d) == {"Bet365": ["Buono"]}


def test_parsers_using_provider_confronta_come_provider_store(tmp_path):
    """⚠️ Il caso che rende il marcatore affidabile o pericoloso.

    `provider_store` deduplica senza spazi ai bordi e case-insensitive. Se il confronto qui
    fosse esatto, un parser che scrive «bet365 » risulterebbe scollegato dalla voce «Bet365» e
    la riga direbbe «— non usato» **subito accanto al pulsante Rimuovi**: un falso rassicurante
    nel momento peggiore."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", [_regola_provider("bet365 ")])
    _scrivi_parser(d, "B", [_regola_provider("BET365")])

    assert sorted(custom_parser.parsers_using_provider("Bet365", d)) == ["A", "B"]
    assert custom_parser.parsers_using_provider("  bet365  ", d) != []
    assert custom_parser.parsers_using_provider("Pinnacle", d) == []
    assert custom_parser.parsers_using_provider("", d) == []
    assert custom_parser.parsers_using_provider("   ", d) == []


# ── il pannello ─────────────────────────────────────────────────────────────────────

def test_il_conteggio_del_pannello_normalizza_come_lo_store(pg):
    """La stessa invariante, dal lato GUI: `_quanti_usano` non deve essere più stretto della
    funzione che alimenta l'avviso di rimozione, altrimenti riga e conferma direbbero cose
    diverse sullo stesso provider."""
    uso = {"bet365 ": ["A"], "BET365": ["B"], "Pinnacle": ["C"]}
    assert pg.ProviderPanel._quanti_usano(uso, "Bet365") == 2
    assert pg.ProviderPanel._quanti_usano(uso, "  bet365 ") == 2
    assert pg.ProviderPanel._quanti_usano(uso, "Pinnacle") == 1
    assert pg.ProviderPanel._quanti_usano(uso, "Sconosciuto") == 0
    assert pg.ProviderPanel._quanti_usano({}, "Bet365") == 0
    assert pg.ProviderPanel._quanti_usano(None, "Bet365") == 0


def test_i_marcatori_spariscono_se_i_parser_non_sono_leggibili_ma_l_elenco_resta(pg, monkeypatch):
    """Fail-safe: senza i parser l'anagrafica dev'essere comunque gestibile."""
    finto = object.__new__(pg.ProviderPanel)

    def _esplode(*_a, **_k):
        raise OSError("cartella parser illeggibile")

    monkeypatch.setattr(pg.custom_parser, "provider_usage", _esplode)
    assert pg.ProviderPanel._provider_usage(finto) == {}


def _disegna(pg, monkeypatch, names, uso):
    """Esegue il VERO `_reload` con widget-spia e ritorna le etichette disegnate."""
    disegnate = []

    class _Label:
        def __init__(self, master=None, **k):
            disegnate.append(k.get("text", ""))
        def pack(self, **k): pass

    class _Frame:
        def __init__(self, master=None, **k): pass
        def pack(self, **k): pass
        def winfo_children(self): return []
        def destroy(self): pass

    class _Button:
        def __init__(self, master=None, **k): pass
        def pack(self, **k): pass

    monkeypatch.setattr(pg.ctk, "CTkLabel", _Label, raising=False)
    monkeypatch.setattr(pg.ctk, "CTkFrame", _Frame, raising=False)
    monkeypatch.setattr(pg.ctk, "CTkButton", _Button, raising=False)
    monkeypatch.setattr(pg.ctk, "CTkFont", lambda **k: None, raising=False)

    finto = object.__new__(pg.ProviderPanel)
    finto._rows_frame = _Frame()
    finto._load_names = lambda cfg=None: list(names)
    finto._provider_usage = lambda: uso
    pg.ProviderPanel._reload(finto)
    return disegnate


def test_la_riga_mostra_quanti_parser_usano_il_provider(pg, monkeypatch):
    """Fail-first: prima la riga mostrava solo il nome e il pulsante Rimuovi."""
    testi = _disegna(pg, monkeypatch, ["Bet365"], {"Bet365": ["A", "B"]})
    assert "Bet365" in testi
    assert any("🧩" in t and "2" in t for t in testi), testi


def test_un_provider_non_usato_LO_DICE(pg, monkeypatch):
    """La differenza voluta rispetto ai dizionari: qui lo zero è l'informazione più utile,
    perché è la condizione che rende la rimozione sicura."""
    testi = _disegna(pg, monkeypatch, ["Orfano"], {})
    assert any("non usato" in t for t in testi), testi
    assert not any("🧩" in t for t in testi), testi


def test_elenco_vuoto_lo_dice(pg, monkeypatch):
    testi = _disegna(pg, monkeypatch, [], {})
    assert any("Nessun provider salvato" in t for t in testi), testi


# ── la conferma di rimozione ────────────────────────────────────────────────────────

def _prova_rimozione(pg, monkeypatch, name, usato_da, *, conferma=False):
    """Esegue il VERO `_remove` intercettando la domanda mostrata all'utente."""
    domande = []

    def _ask(titolo, testo):
        domande.append(testo)
        return conferma

    monkeypatch.setattr(pg.gui_utils, "ask_confirm", _ask)
    monkeypatch.setattr(pg.custom_parser, "parsers_using_provider",
                        lambda n, *a, **k: list(usato_da))
    finto = object.__new__(pg.ProviderPanel)
    finto._status = types.SimpleNamespace(configure=lambda **k: None)
    finto._load_cfg_chiamata = []
    monkeypatch.setattr(pg.config_store, "load_config",
                        lambda *a, **k: finto._load_cfg_chiamata.append(1) or {})
    monkeypatch.setattr(pg.provider_store, "remove_provider", lambda cfg, n: cfg)
    finto._persist = lambda *a, **k: None
    pg.ProviderPanel._remove(finto, name)
    return domande[0] if domande else ""


def test_la_conferma_elenca_i_parser_colpiti(pg, monkeypatch):
    """⚠️ Il pannello Mapping elenca già i parser colpiti prima di eliminare un profilo in uso;
    il Provider diceva solo «è permanente». Stessa domanda — «cosa rompo?» — posta dove conta."""
    domanda = _prova_rimozione(pg, monkeypatch, "Bet365", ["A", "B"])
    assert "Bet365" in domanda
    assert "2" in domanda and "A, B" in domanda, domanda


def test_la_conferma_dice_che_i_parser_RESTANO_funzionanti(pg, monkeypatch):
    """Precisione che conta: rimuovere il provider **non** tocca i parser — continuano a
    scrivere quel valore nel CSV. Dire «li rompi» sarebbe falso e spaventerebbe a sproposito."""
    domanda = _prova_rimozione(pg, monkeypatch, "Bet365", ["A"])
    assert "Restano funzionanti" in domanda or "restano funzionanti" in domanda.lower(), domanda


def test_un_provider_non_usato_non_aggiunge_avvisi(pg, monkeypatch):
    domanda = _prova_rimozione(pg, monkeypatch, "Orfano", [])
    assert "Orfano" in domanda
    assert "⚠️ Usato da" not in domanda, domanda


def test_parser_illeggibili_non_bloccano_la_rimozione(pg, monkeypatch):
    """Fail-safe: se i parser non si leggono la conferma resta quella storica invece di
    impedire di gestire l'anagrafica."""
    def _esplode(*_a, **_k):
        raise OSError("cartella parser illeggibile")

    domande = []
    monkeypatch.setattr(pg.gui_utils, "ask_confirm",
                        lambda t, testo: domande.append(testo) or False)
    monkeypatch.setattr(pg.custom_parser, "parsers_using_provider", _esplode)
    finto = object.__new__(pg.ProviderPanel)
    finto._status = types.SimpleNamespace(configure=lambda **k: None)

    pg.ProviderPanel._remove(finto, "Bet365")          # non deve sollevare
    assert domande and "Bet365" in domande[0]
    assert "⚠️ Usato da" not in domande[0]


def test_rimozione_annullata_non_tocca_la_config(pg, monkeypatch):
    """Guardia anti-regressione: la conferma arricchita non deve aver cambiato il fail-closed
    del dialog — se l'utente annulla (o il dialog è rotto/headless), non si rimuove nulla."""
    chiamate = []
    monkeypatch.setattr(pg.gui_utils, "ask_confirm", lambda *a, **k: False)
    monkeypatch.setattr(pg.custom_parser, "parsers_using_provider", lambda *a, **k: [])
    monkeypatch.setattr(pg.config_store, "load_config",
                        lambda *a, **k: chiamate.append("load") or {})
    monkeypatch.setattr(pg.provider_store, "remove_provider",
                        lambda *a, **k: chiamate.append("remove") or {})
    finto = object.__new__(pg.ProviderPanel)
    finto._status = types.SimpleNamespace(configure=lambda **k: None)

    pg.ProviderPanel._remove(finto, "Bet365")
    assert chiamate == [], f"rimozione annullata ma la config è stata toccata: {chiamate}"


def test_le_etichette_nuove_sono_tradotte():
    """Valore esatto in EN/ES, non «diverso dall'italiano» (rilievo CodeRabbit sulla #225)."""
    from xtrader_bridge import i18n
    prima = i18n.get_language()
    try:
        i18n.set_language("EN")
        assert i18n.tr("🧩 {n} parser").format(n=2) == "🧩 2 parsers"
        assert i18n.tr("— non usato") == "— not used"
        i18n.set_language("ES")
        assert i18n.tr("— non usato") == "— sin usar"
    finally:
        i18n.set_language(prima)
