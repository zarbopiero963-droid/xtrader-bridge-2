"""License Manager — **pubblicazione della lista di revoche su GitHub** (#157).

Carica il file firmato prodotto dal License Manager in un repository GitHub **pubblico**, da cui il
bridge lo scarica (`raw.githubusercontent.com/...`). Usa la **Contents API**:

- `GET  /repos/{owner}/{repo}/contents/{path}?ref={branch}` → se il file esiste ne legge lo `sha`
  (necessario per aggiornarlo); `404` = file non ancora presente → si crea;
- `PUT  /repos/{owner}/{repo}/contents/{path}` con `content` in base64, `message`, `branch` e — solo
  in aggiornamento — lo `sha` letto sopra.

Sicurezza:

- il **token** serve solo per l'upload, viaggia nell'header `Authorization` e **non compare MAI** nei
  messaggi di ritorno né nei log (i messaggi d'errore sono mappati per codice HTTP, non ri-emettono
  la richiesta);
- il repository è **pubblico** e il contenuto è **già firmato**: qui non si aggiunge fiducia, si fa
  solo trasporto. Nessuno può falsificare la lista senza il seed privato, che **non passa di qui**;
- **fail-safe**: qualunque errore (rete, credenziali, conflitto) ritorna un esito strutturato, mai
  un'eccezione verso la GUI.

L'I/O HTTP è dietro un **probe iniettabile** (`http=`), come `wizard.py`/`revocation_client.py`: i
test passano un finto e non aprono alcun socket.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT_S = 20

# Tetto di dimensione della risposta letta (una entry Contents API è piccola; evita di ingoiare un
# corpo enorme se l'endpoint viene dirottato).
_MAX_RESPONSE_BYTES = 2_000_000


def raw_url(repo: str, path: str, branch: str) -> str:
    """URL **raw** pubblico del file pubblicato — è quello da mettere in `REVOCATION_LIST_URL` nel
    bridge. Esempio: `https://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt`."""
    repo = str(repo or "").strip().strip("/")
    path = str(path or "").strip().lstrip("/")
    branch = str(branch or "").strip()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def contents_url(repo: str, path: str) -> str:
    """Endpoint Contents API per il file (path **quotato**: gli spazi/accenti non rompono l'URL)."""
    repo = str(repo or "").strip().strip("/")
    quoted = urllib.parse.quote(str(path or "").strip().lstrip("/"))
    return f"{GITHUB_API}/repos/{repo}/contents/{quoted}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler che **NON segue i redirect** (rilievo Fable #158, sicurezza).

    `urllib` di default segue i 3xx **ri-proponendo gli header della richiesta originale**: fra questi
    c'è `Authorization: Bearer <token>`, che finirebbe così all'host di destinazione — potenzialmente
    **diverso** da `api.github.com` (redirect ostile, proxy/DNS manomesso). Sarebbe un **leak del
    token**. L'API GitHub non ha bisogno di redirect per queste chiamate: restituendo `None` il 3xx
    viene trasformato in `HTTPError` e trattato come un errore qualsiasi, senza inviare nulla altrove."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):     # noqa: D102 — vedi classe
        return None


def _build_opener():
    """Opener con il blocco dei redirect (vedi `_NoRedirectHandler`)."""
    return urllib.request.build_opener(_NoRedirectHandler)


def _default_http(method: str, url: str, *, token: str, body=None,
                  timeout: int = DEFAULT_TIMEOUT_S):
    """Chiamata HTTP di default (urllib) all'API GitHub. Ritorna `(status, payload_dict_o_None)`
    **anche** per le risposte d'errore (4xx/5xx), così il chiamante può mappare il codice; solleva
    solo per problemi di **rete** (DNS, TLS, timeout), che il chiamante traduce in «rete»."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)      # noqa: S310 — host API fisso
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "XTrader-License-Manager")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        # Opener SENZA follow dei redirect: mai ri-inviare `Authorization` a un altro host.
        with _build_opener().open(req, timeout=timeout) as resp:      # noqa: S310 — idem
            raw = resp.read(_MAX_RESPONSE_BYTES)
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(_MAX_RESPONSE_BYTES) if hasattr(exc, "read") else b""
        status = exc.code
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        payload = None
    return status, (payload if isinstance(payload, dict) else None)


def _error_message(status: int, action: str) -> str:
    """Messaggio leggibile per un codice HTTP di errore. **Non** include mai token né corpo grezzo
    della risposta (che potrebbe riportare header/credenziali)."""
    if status in (401, 403):
        return ("Token non valido o senza permessi sul repository "
                "(serve «Contents: Read and write» sul repo scelto).")
    if status == 404:
        return "Repository, branch o percorso non trovati (controlla «owner/nome» e il branch)."
    if status in (409, 422):
        return "Conflitto sul file (è cambiato nel frattempo): riprova la pubblicazione."
    if status == 429:
        return "Troppe richieste all'API GitHub: riprova più tardi."
    if 300 <= status < 400:
        # Redirect NON seguito di proposito (vedi `_NoRedirectHandler`): seguirlo esporrebbe il token.
        return ("Risposta inattesa da GitHub (redirect non seguito per sicurezza): "
                "controlla l'URL/il repository.")
    if status >= 500:
        return "GitHub non disponibile al momento (errore del server): riprova più tardi."
    return f"Pubblicazione non riuscita ({action}): risposta HTTP {status}."


def get_file_sha(repo: str, path: str, branch: str, *, token: str, http=None,
                 timeout: int = DEFAULT_TIMEOUT_S):
    """`(sha, error)` del file già presente nel repo.

    - `(sha, None)` → il file esiste (serve per aggiornarlo);
    - `(None, None)` → **404**: non esiste ancora, si creerà;
    - `(None, messaggio)` → errore vero (credenziali, repo/branch errati, rete)."""
    caller = http or _default_http
    url = contents_url(repo, path) + "?" + urllib.parse.urlencode({"ref": str(branch or "").strip()})
    try:
        status, payload = caller("GET", url, token=token, timeout=timeout)
    except Exception:       # noqa: BLE001 — qualunque problema di rete: esito strutturato, mai crash
        return None, "Rete non disponibile: impossibile contattare GitHub."
    if status == 404:
        return None, None
    # >= 300 (non >= 400): un 3xx NON è un successo — è un redirect che abbiamo deliberatamente
    # rifiutato di seguire (vedi `_NoRedirectHandler`); trattarlo come «ok» leggerebbe uno `sha`
    # inesistente e poi «pubblicherebbe» nel nulla.
    if status >= 300:
        return None, _error_message(status, "lettura")
    sha = (payload or {}).get("sha")
    return (str(sha) if sha else None), None


def publish(content: str, *, repo: str, path: str, branch: str, token: str, message: str,
            http=None, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Pubblica (crea o aggiorna) il file nel repository. Ritorna
    ``{"ok": bool, "message": str, "action": "created"|"updated"|""}``.

    **Fail-safe**: nessuna eccezione verso il chiamante; ogni errore diventa `ok=False` con un
    messaggio leggibile. **Il token non compare mai** nel risultato."""
    if not str(token or "").strip():
        return {"ok": False, "action": "", "message": "Token mancante: salvalo prima di pubblicare."}
    sha, err = get_file_sha(repo, path, branch, token=token, http=http, timeout=timeout)
    if err is not None:
        return {"ok": False, "action": "", "message": err}
    action = "updated" if sha else "created"
    body = {
        "message": str(message or "Aggiorna lista revoche"),
        "content": base64.b64encode(str(content).encode("utf-8")).decode("ascii"),
        "branch": str(branch or "").strip(),
    }
    if sha:
        body["sha"] = sha
    caller = http or _default_http
    try:
        status, _payload = caller("PUT", contents_url(repo, path), token=token, body=body,
                                  timeout=timeout)
    except Exception:       # noqa: BLE001 — rete: esito strutturato, mai crash
        return {"ok": False, "action": "", "message": "Rete non disponibile: pubblicazione non riuscita."}
    if status >= 300:      # vedi sopra: un 3xx non è una pubblicazione riuscita
        return {"ok": False, "action": "", "message": _error_message(status, "scrittura")}
    verbo = "creata" if action == "created" else "aggiornata"
    return {"ok": True, "action": action,
            "message": f"Lista revoche {verbo} su {repo} ({path}, branch {branch})."}
