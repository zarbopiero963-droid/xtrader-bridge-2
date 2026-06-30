"""Sicurezza dei log del sottosistema Betfair (issue #86 PR-P2).

Regola assoluta del blocco personale: **nessun segreto** Betfair deve mai finire
nei log. In particolare non vanno mai scritti App Key, username, password,
sessionToken, certificato, private key, headers (`X-Authentication`,
`X-Application`) né payload/response grezzi del login.

Questo modulo offre tre difese complementari, tutte pure e testabili headless:

1. `redact(text)` — maschera nel testo i valori degli header sensibili e del
   sessionToken, **più** qualunque segreto registrato esplicitamente via
   `register_secret()` (così un valore noto — token in RAM, App Key, password —
   non compare mai in chiaro, anche se finisse in un'eccezione loggata).
2. `SecretRedactionFilter` — un `logging.Filter` che applica `redact()` a ogni
   record; va installato sui handler (vedi `install_global_log_redaction`).
3. `quiet_http_libraries()` — alza a WARNING i logger di `requests`/`urllib3`,
   che a DEBUG stampano header e corpo delle richieste (dove vivono i segreti).

Il registro dei segreti è additivo e thread-safe; `unregister_secret()` lo svuota
selettivamente (es. al logout, per il sessionToken).
"""

import logging
import re
import threading

_REDACTED = "[REDACTED]"

# Header sensibili dell'API Betfair: il loro VALORE non va mai nei log.
SENSITIVE_HEADERS = ("X-Authentication", "X-Application")

# Logger di librerie HTTP che a livello DEBUG riversano header/payload/response.
NOISY_HTTP_LOGGERS = ("requests", "urllib3", "urllib3.connectionpool")

# "X-Authentication: val" / "X-Application=val" / "'X-Authentication': 'val'".
_HEADER_RE = re.compile(
    r"(?i)(X-(?:Authentication|Application))(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]+)"
)
# sessionToken / session_token in JSON, querystring o attributo.
_SESSION_RE = re.compile(
    r"(?i)(session_?token)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]+)"
)

# Segreti esatti da mascherare ovunque compaiano. Soglia di lunghezza minima per
# non mascherare frammenti banali (es. "1") che produrrebbero rumore nei log.
_MIN_SECRET_LEN = 4
_lock = threading.Lock()
_secret_literals: set[str] = set()


def register_secret(value) -> bool:
    """Registra un valore segreto da mascherare ovunque nei log. Ritorna `True` se
    registrato. Valori vuoti/non-stringa o troppo corti (< 4 char) sono ignorati
    (`False`): meglio non mascherare un frammento banale che inquinerebbe i log."""
    if not value:
        return False
    s = str(value)
    if len(s) < _MIN_SECRET_LEN:
        return False
    with _lock:
        _secret_literals.add(s)
    return True


def unregister_secret(value) -> None:
    """Rimuove un segreto dal registro (es. il sessionToken al logout)."""
    if not value:
        return
    with _lock:
        _secret_literals.discard(str(value))


def clear_secrets() -> None:
    """Svuota il registro dei segreti (utile nei test e in un reset completo)."""
    with _lock:
        _secret_literals.clear()


def redact(text) -> str:
    """Maschera header sensibili, sessionToken e segreti registrati in `text`.

    Input non stringa è convertito (``None`` → stringa vuota)."""
    s = "" if text is None else str(text)
    s = _HEADER_RE.sub(lambda m: m.group(1) + m.group(2) + _REDACTED, s)
    s = _SESSION_RE.sub(lambda m: m.group(1) + m.group(2) + _REDACTED, s)
    with _lock:
        secrets = sorted(_secret_literals, key=len, reverse=True)
    for sec in secrets:
        if sec:
            s = s.replace(sec, _REDACTED)
    return s


class SecretRedactionFilter(logging.Filter):
    """`logging.Filter` che applica `redact()` al messaggio finale di ogni record.

    Calcola il messaggio già formattato (`record.getMessage()`), lo redige e azzera
    `args`, così nessun segreto può sopravvivere nell'interpolazione successiva.

    Redige anche il **traceback** di un `logger.exception()`/`exc_info=True` e l'eventuale
    `stack_info` (#166): senza, il `Formatter` espanderebbe `record.exc_info` in chiaro a
    valle del filtro, scrivendo sessionToken/App Key del corpo dell'eccezione. Il traceback
    formattato viene redatto e messo in cache in `record.exc_text`, che il `Formatter`
    standard riusa invece di ri-espandere `exc_info`.

    Non scarta mai record (ritorna sempre `True`): redige, non sopprime."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
            # Traceback dell'eccezione: pre-formatta (se non già in cache), redige e cacha in
            # exc_text così il Formatter usa la versione redatta e non ri-espande exc_info grezzo.
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = redact(record.exc_text)
            # stack_info (stack_info=True): redige il dump dello stack che può contenere segreti.
            if record.stack_info:
                record.stack_info = redact(record.stack_info)
        except Exception:  # pragma: no cover - non far mai crashare il logging
            pass
        return True


def quiet_http_libraries(level: int = logging.WARNING):
    """Alza il livello dei logger HTTP rumorosi (default WARNING) così non stampano
    header/payload/response a DEBUG. Ritorna i nomi dei logger toccati."""
    for name in NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(level)
    return NOISY_HTTP_LOGGERS


def _ensure_filter_on_handler(handler, flt: SecretRedactionFilter) -> None:
    """Aggiunge `flt` a `handler` se non ha già un `SecretRedactionFilter` (idempotente)."""
    try:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(flt)
    except Exception:  # pragma: no cover - non far mai crashare la configurazione del logging
        pass


# Hook su `logging.Logger.addHandler`: ogni handler aggiunto DOPO l'install (a qualunque
# logger) riceve automaticamente il filtro di redazione. Senza, un handler installato più tardi
# (sink applicativo, handler di una libreria) scriverebbe in chiaro (#166). `_orig_addHandler`
# conserva il metodo originale per `_uninstall_addhandler_hook` (reset/test).
_hook_lock = threading.Lock()
_orig_addHandler = None


def _install_addhandler_hook(flt: SecretRedactionFilter) -> None:
    """Avvolge `logging.Logger.addHandler` (una sola volta) così ogni handler aggiunto in
    seguito riceve `flt`. Idempotente: se già installato, non riavvolge."""
    global _orig_addHandler
    with _hook_lock:
        if _orig_addHandler is not None:
            return
        _orig_addHandler = logging.Logger.addHandler
        original = _orig_addHandler

        def addHandler(self, hdlr):
            # Aggancia il filtro PRIMA di pubblicare l'handler (Codex/CodeRabbit #251): l'addHandler
            # originale rende l'handler visibile al logger; se un altro thread logga nella finestra
            # tra la pubblicazione e l'attach del filtro, il record verrebbe gestito NON redatto —
            # esattamente il leak che questo hook deve chiudere. Attaccando prima, nessuna finestra.
            _ensure_filter_on_handler(hdlr, flt)
            original(self, hdlr)

        logging.Logger.addHandler = addHandler


def _uninstall_addhandler_hook() -> None:
    """Ripristina il `logging.Logger.addHandler` originale (reset completo/test)."""
    global _orig_addHandler
    with _hook_lock:
        if _orig_addHandler is not None:
            logging.Logger.addHandler = _orig_addHandler
            _orig_addHandler = None


def install_global_log_redaction() -> SecretRedactionFilter:
    """Installa la difesa globale: un `SecretRedactionFilter` sul root logger e su TUTTI i suoi
    handler — presenti **e futuri** — più il silenziamento delle librerie HTTP. Ritorna il
    filtro installato (idempotente: un solo filtro, stesso oggetto a ogni chiamata).

    Copertura completa (#166):
    - i filtri su un *logger* NON vedono i record **propagati** dai logger figli: solo i filtri
      sugli *handler* lo fanno. Per questo il filtro va su ogni handler di root, non solo sul
      logger;
    - gli handler aggiunti **dopo** l'install verrebbero scoperti: un hook su
      `logging.Logger.addHandler` (`_install_addhandler_hook`) glielo aggiunge automaticamente,
      a qualunque logger vengano agganciati."""
    root = logging.getLogger()
    existing = next(
        (f for f in root.filters if isinstance(f, SecretRedactionFilter)), None)
    flt = existing or SecretRedactionFilter()
    if existing is None:
        root.addFilter(flt)
    # Installa l'hook PRIMA dello sweep (Codex #251): se lo sweep girasse per primo, un handler
    # aggiunto nella finestra tra la fine del loop e l'install dell'hook passerebbe per
    # l'`addHandler` originale, non sarebbe nella lista già spazzata e non verrebbe mai
    # ri-visitato → scoperto. Con l'hook attivo prima, ogni handler aggiunto durante/dopo lo
    # sweep è coperto; lo sweep copre quelli pre-esistenti (l'attach è idempotente).
    _install_addhandler_hook(flt)
    for handler in root.handlers:
        _ensure_filter_on_handler(handler, flt)
    quiet_http_libraries()
    return flt
