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

    def __getattr__(self, _name):
        return lambda *a, **k: _Widget()


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        setattr(self, name, _Widget)
        return _Widget


@pytest.fixture()
def JournalPanel(monkeypatch):
    # Stub di customtkinter SOLO se assente (in CI lo è): non tocca un ctk reale.
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
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
