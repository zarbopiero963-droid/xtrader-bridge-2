"""Test hard #311 §3.5: DPI awareness esplicita + clamp larghezza in fit_to_screen.

Tutto deterministico e headless: `enable_dpi_awareness` ha `platform`/`windll`
iniettabili (niente Windows richiesto), `fit_to_screen` è esercitata su una
finestra fake che cattura `geometry`/`minsize`."""

import types

from xtrader_bridge import dpi_awareness, gui_utils


# ── enable_dpi_awareness ──────────────────────────────────────────────────────

class _Api:
    """API fake: registra le chiamate; ritorna `ret` (HRESULT/BOOL) o solleva."""

    def __init__(self, calls, name, raises=False, ret=0):
        self._calls, self._name, self._raises, self._ret = calls, name, raises, ret

    def __call__(self, *args):
        if self._raises:
            raise OSError(f"{self._name} non disponibile")
        self._calls.append((self._name, args))
        return self._ret


def _windll(calls, *, shcore_raises=False, user32_raises=False,
            shcore_ret=0, user32_ret=1):
    # Default: shcore S_OK (0), user32 BOOL TRUE (1) — i valori di successo reali.
    return types.SimpleNamespace(
        shcore=types.SimpleNamespace(
            SetProcessDpiAwareness=_Api(calls, "shcore", raises=shcore_raises,
                                        ret=shcore_ret)),
        user32=types.SimpleNamespace(
            SetProcessDPIAware=_Api(calls, "user32", raises=user32_raises,
                                    ret=user32_ret)))


def test_dpi_windows_usa_shcore_con_per_monitor():
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(platform="nt", windll=_windll(calls))
    assert esito == dpi_awareness.SHCORE
    # stesso valore di customtkinter (PER_MONITOR=2): mai in conflitto
    assert calls == [("shcore", (2,))]


def test_dpi_fallback_user32_se_shcore_manca():
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(
        platform="nt", windll=_windll(calls, shcore_raises=True))
    assert esito == dpi_awareness.USER32
    assert calls == [("user32", ())]


def test_dpi_fail_open_se_entrambe_le_api_falliscono():
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(
        platform="nt", windll=_windll(calls, shcore_raises=True, user32_raises=True))
    assert esito == dpi_awareness.FAILED          # MAI un raise: l'app parte comunque
    assert calls == []


def test_dpi_hresult_gia_impostata_e_esito_positivo():
    """CodeRabbit #355: ctypes NON solleva sugli HRESULT — E_ACCESSDENIED significa
    «awareness già impostata»: il processo È DPI-aware, esito positivo, niente
    fallback user32."""
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(
        platform="nt", windll=_windll(calls, shcore_ret=-2147024891))
    assert esito == dpi_awareness.SHCORE
    assert calls == [("shcore", (2,))]            # user32 MAI chiamata


def test_dpi_hresult_di_errore_cade_sul_fallback():
    """CodeRabbit #355: un HRESULT di errore diverso (es. E_INVALIDARG) non deve
    essere spacciato per successo — si prova user32."""
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(
        platform="nt", windll=_windll(calls, shcore_ret=-2147024809))
    assert esito == dpi_awareness.USER32
    assert calls == [("shcore", (2,)), ("user32", ())]


def test_dpi_user32_bool_false_e_failed():
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(
        platform="nt", windll=_windll(calls, shcore_raises=True, user32_ret=0))
    assert esito == dpi_awareness.FAILED          # BOOL 0 = fallita, mai un raise


def test_dpi_non_windows_non_tocca_nulla():
    calls = []
    esito = dpi_awareness.enable_dpi_awareness(platform="posix", windll=_windll(calls))
    assert esito == dpi_awareness.UNSUPPORTED
    assert calls == []                            # nessuna API chiamata fuori da Windows


def test_dpi_default_platform_e_os_name():
    """Il default (platform=None → os.name) è verificato su ENTRAMBI i rami
    (CodeRabbit #355): POSIX/CI → UNSUPPORTED senza toccare windll; Windows reale
    → uno degli esiti Windows, MAI UNSUPPORTED."""
    import os
    esito = dpi_awareness.enable_dpi_awareness()
    if os.name != "nt":
        assert esito == dpi_awareness.UNSUPPORTED
    else:
        assert esito in (dpi_awareness.SHCORE, dpi_awareness.USER32,
                         dpi_awareness.FAILED)


# ── clamp_to_screen / fit_to_screen ──────────────────────────────────────────

def test_clamp_riduce_entrambe_le_dimensioni_con_pavimento():
    # schermo 1024x768, margine 80 → area 944x688
    assert gui_utils.clamp_to_screen(1140, 720, 780, 480, 1024, 768) == (944, 688)
    # dentro l'area: nessun clamp
    assert gui_utils.clamp_to_screen(720, 600, 600, 500, 1920, 1080) == (720, 600)
    # pavimento ai minimi: schermo minuscolo non scende MAI sotto il minsize
    assert gui_utils.clamp_to_screen(1140, 720, 780, 480, 640, 400) == (780, 480)


class _FakeWin:
    def __init__(self, screen_w=1024, screen_h=768, winfo_raises=False):
        self._w, self._h, self._raises = screen_w, screen_h, winfo_raises
        self.geometry_calls, self.minsize_calls = [], []

    def winfo_screenwidth(self):
        if self._raises:
            raise RuntimeError("finestra non mappata")
        return self._w

    def winfo_screenheight(self):
        if self._raises:
            raise RuntimeError("finestra non mappata")
        return self._h

    def geometry(self, spec):
        self.geometry_calls.append(spec)

    def minsize(self, w, h):
        self.minsize_calls.append((w, h))


def test_fit_to_screen_clampa_anche_la_larghezza():
    """#311 §3.5 fail-first: col vecchio codice (solo altezza) la finestra Strumenti
    da 1140px usciva di lato su uno schermo 1024."""
    win = _FakeWin(screen_w=1024, screen_h=768)
    gui_utils.fit_to_screen(win, 1140, 720, 780, 480)
    assert win.geometry_calls == ["944x688"]
    assert win.minsize_calls == [(780, 480)]


def test_fit_to_screen_dentro_lo_schermo_resta_identica():
    win = _FakeWin(screen_w=1920, screen_h=1080)
    gui_utils.fit_to_screen(win, 720, 760, 720, 600)
    assert win.geometry_calls == ["720x760"]      # finestra principale: invariata


def test_fit_to_screen_winfo_fallito_nessun_clamp():
    win = _FakeWin(winfo_raises=True)
    gui_utils.fit_to_screen(win, 1140, 720, 780, 480)
    assert win.geometry_calls == ["1140x720"]     # dimensioni richieste così come sono
    assert win.minsize_calls == [(780, 480)]
