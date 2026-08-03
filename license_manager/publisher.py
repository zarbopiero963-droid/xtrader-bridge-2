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

# Fonte UNICA del messaggio «manca il token» (rilievo Sourcery #215): `publish` e `check_access`
# lo dicevano con due frasi diverse per la stessa identica condizione, e due copie oggi sono due
# copie divergenti domani.
MSG_TOKEN_MANCANTE = "Token mancante: incollalo nelle impostazioni di pubblicazione e salva."
DEFAULT_TIMEOUT_S = 20

# Tetto di dimensione della risposta letta (una entry Contents API è piccola; evita di ingoiare un
# corpo enorme se l'endpoint viene dirottato).
_MAX_RESPONSE_BYTES = 2_000_000


def raw_url(repo: str, path: str, branch: str) -> str:
    """URL **raw** pubblico del file pubblicato — è quello da mettere in `REVOCATION_LIST_URL` nel
    bridge. Esempio: `https://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt`.

    `path`/`branch` sono **quotati come in `contents_url`** (rilievo Fugu #158): l'API pubblica il file
    all'indirizzo *codificato*, quindi un raw URL con caratteri grezzi (spazi/accenti) punterebbe a un
    file **inesistente** → il bridge non scaricherebbe più la lista → **lockout fail-closed di tutti i
    bridge**. I due URL devono codificare allo stesso modo. `quote` mantiene `/` (path annidati)."""
    path = urllib.parse.quote(str(path or "").strip().lstrip("/"))
    branch = urllib.parse.quote(str(branch or "").strip())
    return f"https://raw.githubusercontent.com/{_quote_repo(repo)}/{branch}/{path}"


def _quote_repo(repo: str) -> str:
    """`owner/nome` normalizzato e **quotato** (rilievo Fable #158).

    `publish_store.validate_config` già rifiuta tutto ciò che non è un repository GitHub legittimo:
    questa è la seconda rete, per chi arrivasse qui **senza** passare dalla validazione (config
    scritta a mano, chiamata diretta al modulo). Un `?` o un `#` grezzo trasformerebbe il resto
    dell'URL in query-string/fragment, cioè una richiesta a un path diverso da quello voluto.
    Quotare **negli stessi termini** in entrambi gli URL è essenziale: se lo facesse uno solo dei due
    tornerebbe la divergenza raw↔API che porta al lockout. `quote` mantiene lo `/` fra owner e nome."""
    return urllib.parse.quote(str(repo or "").strip().strip("/"))


def contents_url(repo: str, path: str) -> str:
    """Endpoint Contents API per il file (repo/path **quotati**: spazi e caratteri riservati non
    rompono l'URL — vedi `_quote_repo`)."""
    quoted = urllib.parse.quote(str(path or "").strip().lstrip("/"))
    return f"{GITHUB_API}/repos/{_quote_repo(repo)}/contents/{quoted}"


def branch_url(repo: str, branch: str) -> str:
    """Endpoint del **branch**. Serve a distinguere «file non ancora presente» da «branch
    inesistente»: `GET contents?ref=X` risponde 404 in entrambi i casi, e il primo è legittimo."""
    return f"{repo_url(repo)}/branches/{urllib.parse.quote(str(branch or '').strip())}"


def _contents_url_at_ref(repo: str, path: str, branch: str) -> str:
    """URL Contents API per (repo, path) al `ref` indicato — **fonte unica** (rilievo CodeRabbit
    #215): `check_access` e `get_file_sha` lo costruivano ognuno per conto suo, in modo identico.
    Due costruzioni indipendenti dello stesso URL divergono in silenzio il giorno in cui una sola
    viene aggiornata — ed è la classe di difetto che la regola della fonte unica esiste per
    impedire."""
    return contents_url(repo, path) + "?" + urllib.parse.urlencode({"ref": str(branch or "").strip()})


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


def _is_rate_limited(payload) -> bool:
    """`True` se il corpo della risposta dice che è un **rate-limit** (rilievo Fable #215).

    GitHub usa `403` sia per «permessi insufficienti» sia per il **rate-limit secondario**, e i due
    chiedono cose opposte: concedere un permesso contro *aspettare qualche minuto*. Distinguerli è
    lo stesso problema che questa PR risolve fra 401 e 403, un livello più in là.

    Si cerca **solo un marcatore** nel campo `message`; il corpo **non viene mai ri-emesso** —
    potrebbe riportare header o dettagli della richiesta. Il messaggio mostrato all'utente è
    scritto qui.

    **Limite dichiarato** (rilievo GPT-5.5 #215): GitHub segnala il rate-limit anche via header
    (`retry-after`, `x-ratelimit-remaining`), che il probe HTTP di questo modulo **non espone** —
    ritorna `(status, payload)`. Se un giorno arrivasse un 403 di rate-limit con un corpo privo del
    marcatore, l'utente leggerebbe il messaggio sui permessi. Si è preferito non allargare il
    contratto del probe — che è iniettabile e condiviso da tutte le chiamate — per un caso che
    GitHub oggi accompagna sempre con un `message` esplicito."""
    testo = str((payload or {}).get("message", "")).lower() if isinstance(payload, dict) else ""
    return "rate limit" in testo or "abuse detection" in testo


def _error_message(status: int, action: str, repo: str = "", payload=None) -> str:
    """Messaggio leggibile per un codice HTTP di errore. **Non** include mai token né corpo grezzo
    della risposta (che potrebbe riportare header/credenziali).

    401 e 403 hanno messaggi **distinti** (collaudo del proprietario, 2026-08-03). Prima
    condividevano una frase sola — «Token non valido o senza permessi» — e chi la leggeva non
    poteva sapere quale dei due fosse, mentre i rimedi sono opposti: rigenerare il token contro
    concedergli un permesso. Sul secondo PC del proprietario questo è costato una diagnosi a
    tentativi, con la pubblicazione delle revoche ferma nel frattempo."""
    if status == 401:
        return ("Token rifiutato da GitHub (401): non è un problema di permessi, è il token in sé "
                "— sbagliato, scaduto o revocato. Rigeneralo e reincollalo, senza spazi ai bordi.")
    if status == 403:
        if _is_rate_limited(payload):
            return ("GitHub ha applicato un limite di frequenza (403): non è un problema del token "
                    "né dei permessi — aspetta qualche minuto e riprova.")
        dove = f" su «{repo}»" if str(repo or "").strip() else ""
        return (f"Token accettato ma senza permesso di SCRITTURA{dove} (403). Se è un token "
                "fine-grained: in «Repository access» dev'esserci questo repository, e in "
                "«Permissions → Repository permissions» serve «Contents: Read and write».")
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


def repo_url(repo: str) -> str:
    """Endpoint del **repository** (non del file): serve a `check_access` per leggere i permessi
    dell'utente autenticato senza scrivere nulla."""
    return f"{GITHUB_API}/repos/{_quote_repo(repo)}"


def check_access(repo: str, path: str, branch: str, *, token: str, http=None,
                 timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Verifica **preventiva e in sola lettura** che la pubblicazione funzionerà.

    Ritorna ``{"ok", "message", "can_write", "file_exists"}``. **Non scrive mai** sul repository:
    due `GET`, nessun `PUT` — non si sporca il repo delle revoche per fare una prova.

    Perché non basta leggere il file (il caso reale del proprietario, 2026-08-03): il repository
    delle revoche è **pubblico**, quindi una `GET` riesce con qualunque token valido. Una verifica
    di sola lettura direbbe «tutto ok» e poi la pubblicazione fallirebbe con 403 — cioè
    esattamente il guasto che questa funzione dovrebbe prevenire. Per questo si legge
    ``permissions.push`` da `GET /repos/{owner}/{repo}`, che è la capacità di **scrivere**.

    Il 404 sul **file** non è un errore: alla prima pubblicazione il file non esiste ancora e
    verrà creato. Il 404 sul **repository** sì: repo inesistente, oppure — tipico dei token
    fine-grained — non concesso a questo token.

    Fail-safe come il resto del modulo: nessuna eccezione verso la GUI, e **il token non compare
    mai** nel risultato."""
    esito = {"ok": False, "message": "", "can_write": False, "file_exists": False}
    if not str(token or "").strip():
        esito["message"] = MSG_TOKEN_MANCANTE
        return esito
    caller = http or _default_http
    try:
        status, payload = caller("GET", repo_url(repo), token=token, timeout=timeout)
    except Exception:       # noqa: BLE001 — rete: esito strutturato, mai crash
        esito["message"] = "Rete non disponibile: impossibile contattare GitHub."
        return esito
    if status >= 300:
        if status == 404:
            esito["message"] = (f"Repository «{repo}» non trovato (404): controlla «owner/nome». "
                                "Con un token fine-grained un repo esistente ma NON concesso al "
                                "token risponde comunque 404.")
        else:
            esito["message"] = _error_message(status, "verifica", repo, payload)
        return esito
    permessi = (payload or {}).get("permissions") or {}
    esito["can_write"] = bool(permessi.get("push"))
    if not esito["can_write"]:
        esito["message"] = _error_message(403, "verifica", repo)
        return esito

    # Il branch va SONDATO, non dato per buono (rilievo Fugu #215): `GET contents?ref=X` risponde
    # 404 sia per «file non ancora presente» (legittimo, si creerà) sia per «branch inesistente»
    # (errore). Senza questa chiamata un refuso nel nome del branch passava la verifica con un
    # «✅ Accesso OK» che citava pure il branch sbagliato come se fosse stato controllato — un
    # falso-OK proprio nella funzione che esiste per evitarli.
    try:
        status, _payload = caller("GET", branch_url(repo, branch), token=token, timeout=timeout)
    except Exception:       # noqa: BLE001 — rete: esito strutturato, mai crash
        esito["message"] = "Rete non disponibile: impossibile contattare GitHub."
        return esito
    if status == 404:
        esito["message"] = (f"Il branch «{branch}» non esiste su «{repo}» (404): controlla il nome "
                            "(spesso è «main» o «master»). Il permesso di scrittura c'è.")
        return esito
    if status >= 300:
        esito["message"] = _error_message(status, "verifica", repo, _payload)
        return esito

    # Repo scrivibile e branch esistente: resta da vedere se il file c'è già (aggiornamento) o no
    # (creazione). Un errore QUI non invalida quanto già accertato, quindi non ribalta `ok`.
    url = _contents_url_at_ref(repo, path, branch)
    try:
        status, _payload = caller("GET", url, token=token, timeout=timeout)
    except Exception:       # noqa: BLE001 — rete instabile a metà verifica: si dichiara ciò che si sa
        status = None
    esito["ok"] = True
    esito["file_exists"] = status == 200
    if status == 200:
        dettaglio = f"Il file «{path}» esiste già e verrà aggiornato."
    elif status == 404:
        dettaglio = f"Il file «{path}» non c'è ancora: la prima pubblicazione lo creerà."
    else:
        dettaglio = ("Permesso di scrittura verificato; lo stato del file non è stato letto "
                     "(riprova se la pubblicazione dovesse fallire).")
    esito["message"] = (f"✅ Accesso OK: il token può scrivere su «{repo}» (branch {branch}). "
                        f"{dettaglio}")
    return esito


def get_file_sha(repo: str, path: str, branch: str, *, token: str, http=None,
                 timeout: int = DEFAULT_TIMEOUT_S):
    """`(sha, error)` del file già presente nel repo.

    - `(sha, None)` → il file esiste (serve per aggiornarlo);
    - `(None, None)` → **404**: non esiste ancora, si creerà;
    - `(None, messaggio)` → errore vero (credenziali, repo/branch errati, rete)."""
    caller = http or _default_http
    url = _contents_url_at_ref(repo, path, branch)
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
        return None, _error_message(status, "lettura", repo, payload)
    sha = (payload or {}).get("sha")
    return (str(sha) if sha else None), None


def publish(content: str, *, repo: str, path: str, branch: str, token: str, message: str,
            http=None, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Pubblica (crea o aggiorna) il file nel repository. Ritorna
    ``{"ok": bool, "message": str, "action": "created"|"updated"|""}``.

    **Fail-safe**: nessuna eccezione verso il chiamante; ogni errore diventa `ok=False` con un
    messaggio leggibile. **Il token non compare mai** nel risultato."""
    if not str(token or "").strip():
        return {"ok": False, "action": "", "message": MSG_TOKEN_MANCANTE}
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
        return {"ok": False, "action": "", "message": _error_message(status, "scrittura", repo, _payload)}
    verbo = "creata" if action == "created" else "aggiornata"
    return {"ok": True, "action": action,
            "message": f"Lista revoche {verbo} su {repo} ({path}, branch {branch})."}
