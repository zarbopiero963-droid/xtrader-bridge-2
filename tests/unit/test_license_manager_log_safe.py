"""Redazione dei segreti sul percorso di log del License Manager (#215 seguito).

Il package maneggia il **token GitHub** della pubblicazione revoche e finora si difendeva solo
con una convenzione ripetuta a mano in 31 punti («logga solo `type(exc).__name__`»). Qui si
verifica la rete sotto: qualunque cosa passi dal logger esce redatta.
"""

import logging

import pytest

from license_manager import log_safe, publish_store
from xtrader_bridge import event_log

_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
# 40 hex: la forma che NESSUNA regex può riconoscere senza redigere anche gli SHA git.
_TOKEN_OPACO = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def _registro_pulito():
    """Il registro dei segreti è globale di processo: va lasciato come si è trovato, altrimenti
    un token registrato qui redigerebbe l'output di test successivi."""
    prima = set(event_log._secret_literals)
    yield
    event_log._secret_literals.clear()
    event_log._secret_literals.update(prima)


class _Raccoglitore(logging.Handler):
    """Handler che tiene i record FORMATTATI: è la forma che finirebbe nel file di log."""

    def __init__(self):
        super().__init__()
        self.righe = []

    def emit(self, record):
        self.righe.append(self.format(record))


def _logger_con_raccoglitore(nome):
    logger = log_safe.get_logger(nome)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    h = _Raccoglitore()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(h)
    return logger, h


def test_token_passato_come_ARGOMENTO_non_finisce_nel_log():
    """Il caso che la convenzione dei 31 siti previene a mano: `_log.warning("... %s", exc)` con
    un'eccezione che incorpora il token. Qui esce redatto anche se qualcuno lo scrive così."""
    logger, cap = _logger_con_raccoglitore("license_manager.test_arg")
    logger.warning("Richiesta fallita: %s", f"401 per Authorization: token {_TOKEN}")
    assert cap.righe, "nessun record raccolto"
    assert _TOKEN not in cap.righe[0], f"token in CHIARO: {cap.righe[0]!r}"
    assert "[REDACTED_TOKEN]" in cap.righe[0]
    assert "Richiesta fallita" in cap.righe[0], "contesto diagnostico perso"


def test_il_traceback_di_exc_info_viene_redatto():
    """Il buco meno ovvio, e il motivo per cui il filtro non si limita a `record.msg`: il
    traceback lo rende l'HANDLER, dopo i filtri. Senza trattarlo qui, un `exc_info=True`
    aggiunto in buona fede per rendere diagnosticabile un guasto scriverebbe il token in chiaro
    proprio mentre si crede di aver solo migliorato la diagnostica."""
    logger, cap = _logger_con_raccoglitore("license_manager.test_exc")
    try:
        raise RuntimeError(f"HTTP 401 con Authorization: token {_TOKEN}")
    except RuntimeError:
        logger.exception("Pubblicazione non riuscita")
    assert cap.righe, "nessun record raccolto"
    riga = cap.righe[0]
    assert _TOKEN not in riga, f"token in CHIARO nel traceback: {riga!r}"
    assert "[REDACTED_TOKEN]" in riga
    assert "RuntimeError" in riga, "il traceback è stato perso invece che redatto"


def test_un_messaggio_normale_resta_intatto():
    """Contro-prova: la rete non deve rendere illeggibili i log ordinari."""
    logger, cap = _logger_con_raccoglitore("license_manager.test_ok")
    logger.info("Lista revoche pubblicata: %d voci, branch %s", 3, "main")
    assert cap.righe[0] == "INFO Lista revoche pubblicata: 3 voci, branch main"


def test_il_filtro_non_si_impila_a_ogni_chiamata():
    """`get_logger` è chiamato a ogni import: senza il marcatore i filtri si accumulerebbero,
    e ogni record verrebbe redatto N volte — spreco silenzioso che cresce con gli import."""
    nome = "license_manager.test_idempotente"
    primo = log_safe.get_logger(nome)
    quanti = len(primo.filters)
    for _ in range(5):
        log_safe.get_logger(nome)
    assert len(logging.getLogger(nome).filters) == quanti


def test_il_filtro_non_fa_MAI_cadere_una_chiamata_di_log():
    """Un filtro che solleva farebbe sparire la riga di log — o peggio, propagherebbe
    l'eccezione nel chiamante: un problema di diagnostica trasformato in guasto."""
    logger, cap = _logger_con_raccoglitore("license_manager.test_robusto")
    logger.warning("percentuale %d%% e argomento mancante %s")   # args incoerenti di proposito
    assert cap.righe, "la chiamata di log è stata persa"


# ── Secondo livello: il token vivo registrato come literal ───────────────────────────────────

def test_il_token_letto_dal_keyring_viene_registrato_per_la_redazione(monkeypatch):
    """Copre la forma che nessuna regex può riconoscere: 40 hex, identici a uno SHA git.

    Il punto di registrazione è la LETTURA e non solo il salvataggio, perché all'avvio normale
    il token è già nel keyring da una sessione precedente e nessuno lo risalva: registrare solo
    in `save_publish_token` lascerebbe scoperta esattamente la sessione tipica."""
    assert "[REDACTED_TOKEN]" not in event_log.redact_secrets(_TOKEN_OPACO), \
        "precondizione: 40 hex non deve essere redatto da una regex di shape"

    class _FintoKeyring:
        @staticmethod
        def get_password(_servizio, _account):
            return _TOKEN_OPACO

    monkeypatch.setattr(publish_store, "_keyring", lambda: _FintoKeyring)
    assert publish_store.load_publish_token() == _TOKEN_OPACO
    redatto = event_log.redact_secrets(f"errore con {_TOKEN_OPACO} dentro")
    assert _TOKEN_OPACO not in redatto, "il token vivo non è stato registrato"
    assert "[REDACTED_TOKEN]" in redatto


def test_un_keyring_vuoto_non_registra_nulla(monkeypatch):
    """Fail-safe: nessun token → niente da registrare, e soprattutto niente stringa vuota nel
    registro (maschererebbe ovunque)."""
    class _Vuoto:
        @staticmethod
        def get_password(_servizio, _account):
            return None

    monkeypatch.setattr(publish_store, "_keyring", lambda: _Vuoto)
    prima = set(event_log._secret_literals)
    assert publish_store.load_publish_token() is None
    assert set(event_log._secret_literals) == prima


# ── La rete non deve poter essere aggirata da un modulo futuro ───────────────────────────────

def test_nessun_modulo_del_package_usa_un_logger_NUDO():
    """Rilievo convergente di GPT-5.5 e Fable 5 sulla #216, ed è il rilievo giusto.

    Il filtro protegge i logger creati da `log_safe.get_logger`. Un modulo nuovo scritto domani
    con `logging.getLogger(__name__)` — cioè il gesto più naturale del mondo, quello che facevano
    tutti e quattro i moduli prima di questa PR — nascerebbe **fuori** dalla barriera, e nessuno
    se ne accorgerebbe finché un token non compare in un log.

    L'analisi è **sull'AST, non sul testo** (secondo giro GPT-5.5): una ricerca di stringa
    sbaglierebbe in entrambe le direzioni, e la direzione che conta è la seconda —
    `from logging import getLogger` seguito da `getLogger(__name__)` non contiene mai la stringa
    `logging.getLogger`, quindi passerebbe **inosservato** riaprendo esattamente il buco. (Nella
    direzione innocua, un `logging.getLogger` citato in un commento o in un docstring darebbe un
    falso allarme: qui non ne dà, perché l'AST i commenti non li vede.)

    Ricorsivo (`rglob`): il package oggi è piatto, ma la garanzia dichiarata dal docstring non
    deve essere più larga della copertura reale, o il primo sottopackage nascerebbe scoperto.

    `log_safe.py` è l'unica eccezione ammessa: è il posto dove il logger nudo viene creato **una
    volta** e subito filtrato."""
    import ast
    import pathlib

    pacchetto = pathlib.Path(__file__).resolve().parents[2] / "license_manager"
    assert pacchetto.is_dir(), f"package non trovato in {pacchetto}"

    def _chiamate_nude(albero):
        """Nomi delle chiamate che creano un logger fuori da `log_safe`, viste dall'AST."""
        alias_di_getlogger = set()
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.ImportFrom) and nodo.module == "logging":
                for a in nodo.names:
                    if a.name == "getLogger":
                        alias_di_getlogger.add(a.asname or a.name)
        trovate = []
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Call):
                continue
            f = nodo.func
            if isinstance(f, ast.Attribute) and f.attr == "getLogger" \
                    and isinstance(f.value, ast.Name) and f.value.id == "logging":
                trovate.append("logging.getLogger(...)")
            elif isinstance(f, ast.Name) and f.id in alias_di_getlogger:
                trovate.append(f"{f.id}(...) importato da logging")
        return trovate

    colpevoli = []
    for modulo in sorted(pacchetto.rglob("*.py")):
        if modulo.name == "log_safe.py":
            continue                       # l'unica sede legittima, per costruzione
        albero = ast.parse(modulo.read_text(encoding="utf-8"), filename=str(modulo))
        for chiamata in _chiamate_nude(albero):
            colpevoli.append(f"{modulo.relative_to(pacchetto)}: {chiamata}")

    assert not colpevoli, (
        "logger NUDO (fuori dalla redazione) — usare `log_safe.get_logger(__name__)`:\n  "
        + "\n  ".join(colpevoli))
