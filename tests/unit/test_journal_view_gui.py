"""Test della glue della scheda GUI «📒 Diario» (`JournalPanel`, #236 PR 9).

`journal_view_gui` importa `customtkinter` (un display) e non è importabile headless;
qui stubbiamo SOLO la libreria GUI con widget finti (istanze che accettano qualunque
metodo come no-op, es. `.pack()`), così il modulo si importa e possiamo esercitare i
VERI metodi del pannello su un `self` finto, senza aprire finestre.

Si verifica la logica reale del pannello:
- `_selected_types` / `_selected_last` traducono i filtri UI in argomenti di
  `journal_view.filter_events` (incluso «Tutti» → nessun taglio);
- `_refresh` legge un ledger REALE via `event_journal.read_events`, filtra e costruisce
  le righe con `journal_view.table_rows` (esercita il codice reale del progetto, non una
  reimplementazione), e riporta i conteggi corretti;
- `_refresh` è **read-only**: non modifica il file (mtime invariato) e non de-redige un
  token già redatto sul ledger;
- guardia strutturale: il modulo non apre il ledger in scrittura.
"""

import importlib
import inspect
import os
import sys
import types

import pytest

from xtrader_bridge import event_journal as ej


class _Widget:
    """Widget finto: costruttore che ingoia tutto e qualunque metodo (`pack`, `configure`,
    `winfo_children`, …) è un no-op che ritorna un altro `_Widget` (così le catene
    `ctk.CTkLabel(...).pack(...)` non rompono)."""

    def __init__(self, *a, **k):
        pass

    def winfo_children(self):
        # Iterabile vuoto: così il `_clear` REALE del pannello (che itera
        # `winfo_children()`) non esplode quando si COSTRUISCE un vero `JournalPanel`
        # headless (vedi `test_selected_types_coerente_con_la_lingua`, che istanzia il
        # pannello per verificare che `__init__` localizzi davvero i valori-filtro).
        return ()

    def __getattr__(self, _name):
        return lambda *a, **k: _Widget()


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        setattr(self, name, _Widget)
        return _Widget


@pytest.fixture()
def JournalPanel(monkeypatch):
    # Stub di customtkinter SEMPRE (anche quando è installato, es. in CI su Windows/Linux con
    # display): questo test esercita `_refresh`, che COSTRUISCE widget (`CTkFont`/`CTkLabel`/
    # `CTkFrame`). Con il customtkinter REALE headless questi crashano subito
    # («RuntimeError: Too early to use font: no default root window») perché non c'è un root Tk.
    # Sostituendolo con widget no-op possiamo esercitare la logica reale del pannello
    # (read_events → filter_events → table_rows) senza aprire alcuna finestra. monkeypatch
    # ripristina sia customtkinter sia il modulo a fine test, quindi non leaka verso i test che
    # importano il customtkinter reale (es. lo smoke `test_journal_view_gui_import_opzionale`).
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.journal_view_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.journal_view_gui")
    return mod.JournalPanel


def _ledger(tmp_path):
    p = str(tmp_path / "event_journal.jsonl")
    ej.append_event(p, "CSV_WRITTEN", {"rows": 1}, now=1002.0, event_id="b")
    ej.append_event(p, "START", {"mode": "DRY_RUN"}, now=1000.0, event_id="a")
    ej.append_event(p, "CSV_CLEARED", {"reason": "timeout"}, now=1003.0, event_id="c")
    return p


def _fake_self(JournalPanel, path, *, type_val="(tutti i tipi)", last_val="100"):
    """`self` finto con i metodi REALI del pannello bindati; i widget sono sink no-op."""
    counts = []
    fake = types.SimpleNamespace(
        _path=path,
        _type=types.SimpleNamespace(get=lambda: type_val),
        _last=types.SimpleNamespace(get=lambda: last_val),
        # #343 slice 4f: `_selected_types` confronta con `self._all_types` (valore
        # localizzato alla costruzione). In CI la lingua è IT → il valore canonico.
        _all_types="(tutti i tipi)",
        _header=_Widget(),
        _rows_frame=_Widget(),
        _counts=types.SimpleNamespace(configure=lambda **k: counts.append(k)),
    )
    for name in ("_selected_types", "_selected_last", "_clear", "_refresh"):
        setattr(fake, name, types.MethodType(getattr(JournalPanel, name), fake))
    # _clear reale itera winfo_children(): sul sink no-op ritorna un _Widget non iterabile,
    # quindi lo sostituiamo con un no-op (non è la logica sotto test).
    fake._clear = lambda frame: None
    return fake, counts


# ── selezione filtri ─────────────────────────────────────────────────────────

def test_selected_types_e_last(JournalPanel, tmp_path):
    fake, _ = _fake_self(JournalPanel, _ledger(tmp_path))
    assert fake._selected_types() is None            # «tutti i tipi» → nessun filtro
    assert fake._selected_last() == 100

    fake2, _ = _fake_self(JournalPanel, _ledger(tmp_path),
                          type_val="START", last_val="Tutti")
    assert fake2._selected_types() == ["START"]      # tipo specifico
    assert fake2._selected_last() is None            # «Tutti» → nessun taglio


def test_selected_types_coerente_con_la_lingua(JournalPanel, tmp_path):
    """#343 slice 4f: «(tutti i tipi)» è display E chiave di confronto. Due livelli:

    (1) un `JournalPanel` REALE costruito in EN/ES deve avere `_all_types` (e la voce
        «Tutti» in `_last_choices`) localizzati da `__init__` via `i18n.tr` — chiude il
        gap d'integrazione: prova che la COSTRUZIONE traduce davvero i valori-filtro, non
        solo che il confronto funzioni in astratto (una regressione che ri-hardcoda
        `self._all_types = "(tutti i tipi)"` fa fallire qui);
    (2) `_selected_types` ritorna `None` quando la selezione è quel valore tradotto, e la
        lista del tipo quando è un tipo reale (non confuso col sentinel)."""
    from xtrader_bridge import i18n
    try:
        for lang, tradotto in (("EN", "(all types)"), ("ES", "(todos los tipos)")):
            i18n.set_language(lang)
            # (1) costruzione reale: __init__ deve localizzare i valori-filtro.
            real = JournalPanel(path=_ledger(tmp_path))
            assert real._all_types == tradotto             # __init__ chiama davvero i18n.tr
            assert i18n.tr("Tutti") in real._last_choices  # anche il filtro «Ultimi»
            # (2) coerenza del confronto in `_selected_types` col valore tradotto.
            fake, _ = _fake_self(JournalPanel, _ledger(tmp_path), type_val=tradotto)
            fake._all_types = tradotto                # come farebbe __init__ in quella lingua
            assert fake._selected_types() is None     # sentinel tradotto → nessun filtro
            fake._type = types.SimpleNamespace(get=lambda: "START")
            assert fake._selected_types() == ["START"]
    finally:
        i18n.set_language("IT")


# ── _refresh esercita read_events + filter_events + table_rows reali ───────────

def test_refresh_conta_eventi_reali(JournalPanel, tmp_path):
    fake, counts = _fake_self(JournalPanel, _ledger(tmp_path))
    fake._refresh()
    assert counts, "il pannello deve aggiornare la riga conteggi"
    text = counts[-1]["text"]
    assert "3 eventi totali" in text and "mostrati 3" in text


def test_refresh_filtra_per_tipo(JournalPanel, tmp_path):
    fake, counts = _fake_self(JournalPanel, _ledger(tmp_path), type_val="START")
    fake._refresh()
    text = counts[-1]["text"]
    assert "3 eventi totali" in text and "mostrati 1" in text   # solo START tra i 3


def test_refresh_file_assente_non_crasha(JournalPanel, tmp_path):
    fake, counts = _fake_self(JournalPanel, str(tmp_path / "non_esiste.jsonl"))
    fake._refresh()                                   # nessuna eccezione
    assert "mostrati 0" in counts[-1]["text"]


# ── read-only + niente de-redazione via il pannello ───────────────────────────

def test_refresh_read_only_e_non_de_redige(JournalPanel, tmp_path):
    p = str(tmp_path / "event_journal.jsonl")
    token = "123456789:LiveBotTokenSecretValue_xyz"
    ej.append_event(p, "SIGNAL_RECEIVED", {"raw": f"msg {token}"}, now=5.0, event_id="x")
    mtime_prima = os.path.getmtime(p)
    captured = []
    fake, _ = _fake_self(JournalPanel, p)
    # Cattura le celle renderizzate intercettando table_rows del modulo sotto test.
    mod = sys.modules["xtrader_bridge.journal_view_gui"]
    orig = mod.journal_view.table_rows
    mod.journal_view.table_rows = lambda events: captured.extend(orig(events)) or orig(events)
    try:
        fake._refresh()
    finally:
        mod.journal_view.table_rows = orig
    joined = " ".join(str(cell) for row in captured for cell in row)
    assert token not in joined                        # mai il token in chiaro
    assert "[REDACTED_TOKEN]" in joined                # mostrato redatto, com'è sul file
    assert os.path.getmtime(p) == mtime_prima          # read-only: file non toccato


# ── guardia strutturale: nessuna scrittura del ledger ─────────────────────────

def test_modulo_non_apre_ledger_in_scrittura(JournalPanel):
    src = inspect.getsource(sys.modules["xtrader_bridge.journal_view_gui"])
    # Nessuna scrittura sul ledger: niente open() builtin in scrittura né .write().
    assert "open(self._path" not in src                 # non apre mai il ledger a mano
    assert ', "w"' not in src and ", 'w'" not in src     # nessun open in write mode
    assert ', "a"' not in src and ", 'a'" not in src     # nessun open in append mode
    assert ".write(" not in src                          # nessuna scrittura file
    assert ".read_events" in src                         # legge solo via l'API read-only
    assert "de_redact" not in src and "unredact" not in src


# ── AC-M11: cap di render del Diario (audit #114) ─────────────────────────────

class _CountingFrame:
    """`_rows_frame` che conta le righe (frame) create al suo interno, per verificare il
    cap di render senza aprire Tk."""
    def __init__(self):
        self.rows = 0

    def winfo_children(self):
        return ()


def _fake_self_counting(JournalPanel, path, mod, *, last_val="Tutti"):
    counts = []
    frame = _CountingFrame()
    fake = types.SimpleNamespace(
        _path=path,
        _type=types.SimpleNamespace(get=lambda: "(tutti i tipi)"),
        _last=types.SimpleNamespace(get=lambda: last_val),
        _all_types="(tutti i tipi)",
        _header=_Widget(),
        _rows_frame=frame,
        _counts=types.SimpleNamespace(configure=lambda **k: counts.append(k)),
    )
    for name in ("_selected_types", "_selected_last", "_refresh"):
        setattr(fake, name, types.MethodType(getattr(JournalPanel, name), fake))
    fake._clear = lambda f: None
    # Conta quante righe passano a `table_rows` (== righe effettivamente disegnate): il
    # pannello itera l'output di `table_rows(render_events)`, quindi la sua lunghezza è il
    # numero di widget-riga creati.
    orig = mod.journal_view.table_rows
    def _counting_table_rows(events):
        out = list(orig(events))
        frame.rows = len(out)
        return out
    mod.journal_view.table_rows = _counting_table_rows
    return fake, counts, frame, orig


def test_refresh_cappa_le_righe_renderizzate(JournalPanel, tmp_path, monkeypatch):
    """AC-M11 audit #114: con «Tutti» su un ledger enorme, il Diario disegna al massimo
    `_ROW_RENDER_CAP` righe (non una per evento → niente freeze del thread Tk), ma il
    conteggio TOTALE resta veritiero e avvisa del taglio. Prima del fix: nessun cap →
    una riga-widget per ogni evento."""
    mod = sys.modules["xtrader_bridge.journal_view_gui"]
    cap = mod._ROW_RENDER_CAP
    p = str(tmp_path / "event_journal.jsonl")
    total = cap + 250
    for i in range(total):
        ej.append_event(p, "CSV_WRITTEN", {"rows": 1}, now=1000.0 + i, event_id=f"e{i}")
    fake, counts, frame, orig = _fake_self_counting(JournalPanel, p, mod)
    try:
        fake._refresh()
    finally:
        mod.journal_view.table_rows = orig
    assert frame.rows == cap                          # righe disegnate cappate a 500
    text = counts[-1]["text"]
    assert str(total) in text                         # totale VERO mostrato
    assert str(cap) in text                           # e il numero mostrato
    assert "primi" in text or "first" in text or "primeros" in text   # avviso di taglio


def test_refresh_sotto_cap_mostra_tutte(JournalPanel, tmp_path):
    """Sotto il cap: nessun taglio, tutte le righe disegnate e messaggio normale."""
    mod = sys.modules["xtrader_bridge.journal_view_gui"]
    p = str(tmp_path / "event_journal.jsonl")
    for i in range(5):
        ej.append_event(p, "START", {"mode": "DRY_RUN"}, now=1000.0 + i, event_id=f"s{i}")
    fake, counts, frame, orig = _fake_self_counting(JournalPanel, p, mod)
    try:
        fake._refresh()
    finally:
        mod.journal_view.table_rows = orig
    assert frame.rows == 5
    assert "mostrati 5" in counts[-1]["text"] or "showing 5" in counts[-1]["text"]
