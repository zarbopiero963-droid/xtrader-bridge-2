"""Client di autenticazione Betfair.it (issue #86 PR-P4) — read-only, token in RAM.

Login non-interattivo Betfair.it con **certificato** (cert + private key) e
**Delayed App Key**, su `identitysso-cert.betfair.it/api/certlogin`. Vincoli:

- il `sessionToken` ottenuto vive **solo in RAM** (`BetfairSession`): mai su disco,
  mai nei log (è registrato nel redattore globale);
- **nessuna operazione di scommessa**: l'unica operazione è il login/logout; passa
  comunque dal guard `safety.assert_read_only` per contratto;
- **errori safe**: in caso di fallimento si solleva `LoginError`/`CertificateError`
  senza mai incorporare la response grezza, gli header o i segreti nel messaggio.

La chiamata HTTP reale usa solo la **stdlib** (`urllib` + `ssl.load_cert_chain`):
nessuna nuova dipendenza. È isolata in `_default_transport` e **iniettabile** via
`transport=`, così i test girano offline con un trasporto finto e il percorso di
rete reale resta una verifica manuale (Windows, certificato vero).
"""

import json
import logging
import os

from . import credential_store, safety
from .credential_store import BetfairCredentials
from .session import BetfairSession

logger = logging.getLogger(__name__)

# Endpoint di login con certificato del dominio italiano.
CERTLOGIN_URL = "https://identitysso-cert.betfair.it/api/certlogin"

# Endpoint di LOGOUT (invalidazione della sessione lato server) del dominio italiano. NON è
# l'endpoint cert: il logout autentica col solo `sessionToken` nell'header `X-Authentication`
# (più l'App Key in `X-Application`), senza certificato client (#168).
LOGOUT_URL = "https://identitysso.betfair.it/api/logout"

# Nomi "operazione" per il guard read-only (NON sono operazioni di scommessa).
LOGIN_OPERATION = "certlogin"
LOGOUT_OPERATION = "logout"

# Timeout della richiesta di login (secondi): un login non deve bloccare all'infinito.
LOGIN_TIMEOUT = 20

# Timeout del logout (secondi): più corto del login — è best-effort e non deve trattenere a
# lungo il chiamante (es. il `finally` dell'auto-sync o la chiusura della tab).
LOGOUT_TIMEOUT = 10


class LoginError(RuntimeError):
    """Login Betfair non riuscito (credenziali errate, rete, stato != SUCCESS).

    Il messaggio è sempre **safe**: non contiene response grezza, header o segreti."""


class CertificateError(LoginError):
    """Certificato / private key mancanti o non trovati su disco."""


def _default_transport(creds: BetfairCredentials) -> dict:
    """Esegue il certlogin reale via stdlib e ritorna il JSON di risposta come dict.

    Usa un `ssl.SSLContext` con `load_cert_chain` (autenticazione TLS client) e POST
    urlencoded. Non logga nulla. Importata lazy così l'assenza di rete/SSL non pesa
    sull'import del modulo."""
    import ssl
    import urllib.parse
    import urllib.request

    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=creds.cert_path, keyfile=creds.key_path)
    body = urllib.parse.urlencode(
        {"username": creds.username, "password": creds.password}).encode("utf-8")
    req = urllib.request.Request(
        CERTLOGIN_URL, data=body, method="POST",
        headers={
            "X-Application": creds.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=LOGIN_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _default_logout_transport(session_token, app_key) -> dict:
    """Esegue il logout reale (invalidazione lato server) via stdlib e ritorna il JSON come dict.

    POST a `LOGOUT_URL` con il `sessionToken` nell'header `X-Authentication` e l'App Key in
    `X-Application` (NESSUN body, nessun segreto in URL/body). Niente certificato client (a
    differenza del login). Non logga nulla; importata lazy come il transport di login."""
    import ssl
    import urllib.request

    # Context TLS ESPLICITO (come `_default_transport` del login): NON affidarsi al default
    # globale di processo, che un ambiente potrebbe aver indebolito (override di
    # `ssl._create_default_https_context`). Qui viaggiano credenziali (sessionToken + App Key),
    # quindi la verifica del certificato server non deve poter essere abbassata da fuori (Codex).
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        LOGOUT_URL, data=b"", method="POST",
        headers={
            "X-Application": app_key,
            "X-Authentication": session_token,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=LOGOUT_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


class BetfairAuthClient:
    """Login/logout Betfair.it con certificato. Custodisce il token in RAM.

    `session`: la `BetfairSession` condivisa col bridge. `transport`: callable
    `(BetfairCredentials) -> dict` per iniettare un trasporto finto nei test; se
    ``None`` usa `_default_transport` (rete reale). `logout_transport`: callable
    `(session_token, app_key) -> dict` analogo per il logout server-side (#168)."""

    def __init__(self, session: BetfairSession = None, transport=None,
                 logout_transport=None):
        self.session = session if session is not None else BetfairSession()
        self._transport = transport
        self._logout_transport = logout_transport
        # App Key dell'ULTIMO login: serve a comporre l'header `X-Application` del logout
        # server-side (#168). Vive solo in RAM, come il token; azzerata al logout. NON è un
        # segreto come username/password ma resta in memoria e basta (mai loggata).
        self._app_key = None

    @property
    def is_logged_in(self) -> bool:
        return self.session.is_logged_in

    def login(self, creds: BetfairCredentials = None) -> str:
        """Esegue il login e mette il `sessionToken` in RAM; lo ritorna.

        Se `creds` è ``None`` carica le credenziali locali cifrate dal keyring.
        Solleva `CertificateError` se cert/key mancano o non esistono,
        `LoginError` se le credenziali sono incomplete, la rete fallisce o lo stato
        di login non è ``SUCCESS``. Nessun dato sensibile finisce nel messaggio."""
        # Contratto read-only: il login NON è una operazione di scommessa.
        safety.assert_read_only(LOGIN_OPERATION)

        if creds is None:
            creds = credential_store.load_credentials()

        if not (creds.app_key.strip() and creds.username.strip()
                and creds.password.strip()):
            raise LoginError("Credenziali Betfair incomplete (App Key/username/password).")
        if not (creds.cert_path.strip() and creds.key_path.strip()):
            raise CertificateError("Certificato o private key non configurati.")
        if not (os.path.isfile(creds.cert_path) and os.path.isfile(creds.key_path)):
            raise CertificateError("File certificato/private key non trovati su disco.")

        transport = self._transport or _default_transport
        try:
            data = transport(creds)
        except CertificateError:
            raise
        except Exception as ex:   # noqa: BLE001 — errore safe: niente response/segreti nel messaggio
            # Solo il TIPO dell'errore, mai il contenuto (può includere body/header). `from None`
            # SOPPRIME la causa (#168, Codex): con `from ex` l'eccezione originale del trasporto
            # resterebbe in `__cause__` e un traceback / `logger.exception(exc_info=True)`
            # stamperebbe il suo messaggio grezzo (potenzialmente body/segreti del login).
            raise LoginError(
                f"Login Betfair fallito ({type(ex).__name__}).") from None

        status = (data or {}).get("loginStatus")
        token = (data or {}).get("sessionToken")
        if status != "SUCCESS" or not token:
            # `status` è un codice safe (es. INVALID_USERNAME_OR_PASSWORD), non un segreto.
            raise LoginError(f"Login Betfair non riuscito: {status or 'risposta non valida'}.")

        self.session.set_token(token)   # solo in RAM + registrato per la redazione log
        self._app_key = creds.app_key.strip()   # cache per il logout server-side (#168)
        return token

    def logout(self) -> None:
        """Logout: invalida la sessione **lato server** (best-effort) e poi cancella il
        `sessionToken` dalla RAM (idempotente). Le credenziali salvate non vengono toccate.

        Server-side (#168): se c'è un token attivo e l'App Key dell'ultimo login è nota, fa
        un POST al logout endpoint Betfair.it (`identitysso.betfair.it/api/logout`) con
        `X-Authentication`/`X-Application` PRIMA del clear locale, così la sessione non resta
        valida sul server fino alla scadenza (il chiamante mostrava "disconnesso" mentre il
        server restava loggato). È **best-effort**: un fallimento (rete/timeout/`status`!=SUCCESS)
        NON impedisce il clear locale — la GUI deve comunque risultare disconnessa — e si logga
        solo il TIPO dell'errore o lo `status`, MAI la response (che riecheggia il token).

        Copre il flusso auto login→sync→auto logout (`auto_sync` chiama `auth.logout()`). Il
        logout MANUALE della tab passa ancora da `controller.session.clear()` (il controller ha
        solo una `session`, non un auth client): instradarlo qui è un follow-up di wiring GUI."""
        token = self.session.token
        app_key = self._app_key
        if token and app_key:
            # Contratto read-only: il logout NON è una operazione di scommessa.
            safety.assert_read_only(LOGOUT_OPERATION)
            transport = self._logout_transport or _default_logout_transport
            try:
                data = transport(token, app_key)
            except Exception as ex:   # noqa: BLE001 — best-effort: mai response/segreti nel log
                # Solo il TIPO dell'errore (es. URLError/timeout), mai il contenuto.
                logger.warning("Logout Betfair lato server non riuscito (%s): la sessione "
                               "potrebbe restare valida fino alla scadenza. Token locale "
                               "cancellato comunque.", type(ex).__name__)
            else:
                # `status` è un codice safe (SUCCESS/FAIL); la response NON va loggata (il suo
                # campo `token` riecheggia il sessionToken). `isinstance(data, dict)` PRIMA di
                # `.get`: un endpoint/proxy che ritorna un JSON valido ma NON oggetto (lista/stringa)
                # farebbe sollevare `.get` QUI (fuori dal try) saltando il clear locale e rompendo il
                # contratto best-effort (CodeRabbit). Un payload non-dict è trattato come logout
                # server-side non confermato, ma il clear locale avviene comunque.
                status = data.get("status") if isinstance(data, dict) else None
                if status != "SUCCESS":
                    logger.warning("Logout Betfair lato server: stato %s. La sessione potrebbe "
                                   "restare valida fino alla scadenza. Token locale cancellato.",
                                   status or "risposta non valida")
        # Clear locale ATOMICO solo se la sessione tiene ANCORA il token appena sloggato (Codex/
        # CodeRabbit #262): durante la POST (rete, lenta) un altro path può fare un re-login sulla
        # sessione CONDIVISA (clear manuale + re-login, o un worker che completa un login).
        # `clear_if_token` fa il confronto e il `clear` SOTTO LOCK (niente race check-then-clear):
        # se il token è cambiato non cancella nulla e lascia intatta la sessione nuova. Il reset di
        # `_app_key` segue SOLO se il clear è avvenuto (token coincidente, anche `None`==`None` per il
        # logout idempotente), così non si spazza l'App Key del login più recente.
        if self.session.clear_if_token(token):
            self._app_key = None
