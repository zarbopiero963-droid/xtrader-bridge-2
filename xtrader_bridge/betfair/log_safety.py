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
    Non scarta mai record (ritorna sempre `True`): redige, non sopprime."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # pragma: no cover - non far mai crashare il logging
            pass
        return True


def quiet_http_libraries(level: int = logging.WARNING):
    """Alza il livello dei logger HTTP rumorosi (default WARNING) così non stampano
    header/payload/response a DEBUG. Ritorna i nomi dei logger toccati."""
    for name in NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(level)
    return NOISY_HTTP_LOGGERS


def install_global_log_redaction() -> SecretRedactionFilter:
    """Installa la difesa globale: aggiunge un `SecretRedactionFilter` al root logger
    e a tutti i suoi handler (idempotente) e silenzia le librerie HTTP. Ritorna il
    filtro installato. I sink applicativi (file di log) dovrebbero aggiungere lo
    stesso filtro ai propri handler per coprire anche i record propagati."""
    root = logging.getLogger()
    existing = next(
        (f for f in root.filters if isinstance(f, SecretRedactionFilter)), None)
    flt = existing or SecretRedactionFilter()
    if existing is None:
        root.addFilter(flt)
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(flt)
    quiet_http_libraries()
    return flt
