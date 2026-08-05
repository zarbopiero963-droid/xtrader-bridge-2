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

# L'accoppiamento esiste già nello stesso senso in `publish_store.py`: qui serve per confrontare
# ciò che si sta per pubblicare con ciò che i bridge scaricano davvero (#234). Si importa il
# MODULO, non la costante: `REVOCATION_LIST_URL` va letta al momento della chiamata, altrimenti
# un `from … import` la congelerebbe all'import e il confronto guarderebbe un valore stantio.
from xtrader_bridge.licensing import revocation_client

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


def disallineamento_bridge(repo: str, path: str, branch: str) -> str:
    """Avviso se si sta per pubblicare a un indirizzo **diverso** da quello che i bridge leggono,
    altrimenti stringa vuota. Puro: nessuna rete, nessuna scrittura.

    **Da un incidente reale del proprietario (2026-08-03), #234.** Il campo Repository puntava a
    `xtrader-bridge-2` mentre il token aveva `Contents: Read and write` su `xtrader-revocation`:
    403, auto-pubblicazione ferma. Il messaggio del 403 suggeriva — correttamente ma
    **parzialmente** — di allargare il token. Seguirlo alla lettera avrebbe fatto **riuscire** la
    pubblicazione su un repository che **nessun bridge legge**, sostituendo un fallimento
    rumoroso con uno silenzioso su una funzione di sicurezza: le revoche avrebbero smesso di
    propagarsi senza un solo errore a video.

    Il confronto è possibile perché entrambi i valori vivono nello stesso processo: la
    configurazione di pubblicazione da una parte, la costante che i bridge compilano dall'altra.

    Due precisazioni che ne determinano la correttezza:

    - si confronta l'URL **quotato** prodotto da `raw_url`, non i campi grezzi. `raw_url`
      codifica `path`/`branch` apposta (rilievo Fugu #158), quindi un confronto sul testo grezzo
      darebbe un disallineamento **falso** su ogni path con spazi o accenti — e un avviso falso
      su una configurazione giusta insegna a ignorare l'avviso vero;
    - **gated su `is_placeholder_url`**: con l'URL placeholder di sviluppo la revoca online è
      inattiva per costruzione, quindi non esiste un termine di paragone e avvisare sarebbe
      rumore su uno stato che non è un errore.

    NON blocca: segnala. Ma il chiamante deve renderlo visibile **anche sul successo**, perché è
    esattamente il caso in cui il difetto si manifesta — «✅ Pubblicato» e nessuno che se ne
    accorga.
    """
    atteso = revocation_client.REVOCATION_LIST_URL
    if revocation_client.is_placeholder_url(atteso):
        return ""
    configurato = raw_url(repo, path, branch)
    # Confronto ESATTO, nessuna normalizzazione (secondo rilievo Fable 5, che ha corretto il
    # primo). Una stesura intermedia toglieva spazi e slash finali «perché servono lo stesso
    # file»: falso. Su `raw.githubusercontent.com` un file con slash finale
    # (`…/revocation_list.txt/`) risponde **404**, e uno spazio in coda pure — e
    # `REVOCATION_LIST_URL` non è una preferenza, è la stringa che i bridge **scaricano
    # davvero**. Normalizzarle silenziava un bridge realmente rotto, dentro la funzione che
    # esiste per non silenziare nulla: il difetto originale, riprodotto nella sua correzione.
    #
    # Quindi si avvisa SEMPRE su qualunque differenza. Ma il messaggio deve **nominarla**: due
    # URL che differiscono per uno spazio finale o per una maiuscola si leggono come identici, e
    # un avviso che sembra sbagliato è un avviso che la volta dopo nessuno legge.
    a, b = str(configurato), str(atteso or "")
    if a == b:
        return ""
    # `strip()` toglie il bianco da ENTRAMBI i lati, quindi ci finisce anche uno spazio iniziale:
    # il messaggio deve dire «in eccesso», non «finali» (rilievo Fable 5 + GPT-5.5 sul commit
    # precedente). Chiamarlo «finale» mandava a cercare in coda una differenza che sta in testa —
    # cioè di nuovo un testo che dichiara una cosa diversa da quella che il codice fa, che è
    # esattamente il difetto che questa PR esiste per togliere.
    if a.strip().rstrip("/") == b.strip().rstrip("/"):
        return (
            "⚠️ L'indirizzo di pubblicazione e quello che i bridge scaricano differiscono solo "
            f"per SPAZI o SLASH in eccesso (a inizio o fine).\nConfigurato:      {a!r}\n"
            f"Atteso dai bridge: {b!r}\n"
            "Sembrano identici ma non lo sono, e i bridge NON scaricherebbero la lista: su "
            "raw.githubusercontent.com un file con slash o spazio in coda risponde 404, e uno "
            "spazio iniziale rende la richiesta non valida. Correggi REVOCATION_LIST_URL o la "
            "configurazione. NON allargare il token.")
    if a.lower() == b.lower():
        # Differenza di SOLE maiuscole/minuscole. Si avvisa comunque — perché su
        # `raw.githubusercontent.com` branch e percorso SONO case-sensitive, e un `Main` al posto
        # di `main` darebbe 404 a tutti i bridge — ma dicendo esattamente cos'è, altrimenti chi
        # legge confronta due URL che «sembrano identici» e conclude che l'avviso è rotto.
        return (
            "⚠️ L'indirizzo di pubblicazione e quello che i bridge scaricano differiscono SOLO "
            f"per maiuscole/minuscole.\nConfigurato:      {configurato}\nAtteso dai bridge: "
            f"{atteso}\nBranch e percorso su raw.githubusercontent.com sono case-sensitive: "
            "allinea la grafia esatta. NON allargare il token — non è un problema di permessi.")
    return (
        "⚠️ Stai pubblicando a un indirizzo DIVERSO da quello da cui i bridge scaricano la "
        f"lista.\nConfigurato:      {configurato}\nAtteso dai bridge: {atteso}\n"
        "Pubblicare qui NON propagherà alcuna revoca. Correggi Repository/Branch/Percorso — "
        "NON allargare il token: allargarlo farebbe riuscire la pubblicazione nel posto "
        "sbagliato, e il problema diventerebbe invisibile.")


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


def probe_path(path: str) -> str:
    """Percorso **usa-e-getta** su cui si fa la prova di scrittura — mai il file delle revoche.

    Bloccante Fugu #215. La prova puntava al file reale, difesa solo dall'ordine
    «permessi-prima-di-sha» di GitHub: se un proxy o un'API compatibile applicasse comunque la
    `PUT`, la lista **firmata** verrebbe sovrascritta e i bridge resterebbero senza. Rilevare il
    danno (ramo ANOMALIA) non è impedirlo, e su un artefatto di sicurezza vivo la differenza conta.

    Il potere diagnostico non cambia: il permesso «Contents» vale per l'intero **repository**, non
    per singolo file. Cambia il danno peggiore: da «lista revoche sovrascritta» a «un file inerte
    che nessun bridge legge, cancellabile a mano»."""
    return f"{str(path or '').strip().lstrip('/')}.xtrader-verifica-accesso"


# Sha di prova: forma valida (40 esadecimali) ma riferito a un file che **non esiste**, quindi
# GitHub risponde «conflitto» invece di scrivere. Costante e innocua: il bersaglio è il percorso
# usa-e-getta, non le revoche.
_SHA_PROBE = "0" * 40


def _rimuovi_file_di_prova(repo: str, path: str, branch: str, sha: str, *, caller, token,
                          timeout: int) -> bool:
    """Cancella il file di prova creato da una `PUT` accettata (ramo ANOMALIA). `True` se rimosso.

    Bloccante Fugu #215: dire «cancellalo a mano» scarica sull'utente la pulizia di un artefatto
    creato dallo strumento, per giunta in un repository **pubblico** accanto alla lista firmata.

    Guardia di sicurezza esplicita: si cancella **solo** il percorso di prova. Un errore qui
    cancellerebbe la lista delle revoche, cioè il danno peggiore possibile — quindi la condizione
    è verificata prima della chiamata, non affidata al fatto che il chiamante passi la cosa
    giusta. Best-effort: un fallimento non solleva, viene detto nel messaggio."""
    bersaglio = probe_path(path)
    if bersaglio == str(path or "").strip().lstrip("/") or not str(sha or "").strip():
        return False
    try:
        status, _ = caller("DELETE", contents_url(repo, bersaglio), token=token,
                           body={"message": "rimuove il file di verifica accesso",
                                 "sha": str(sha), "branch": str(branch or "").strip()},
                           timeout=timeout)
    except Exception:       # noqa: BLE001 — pulizia best-effort: mai un crash, si dice e basta
        return False
    return status is not None and 200 <= status < 300


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
        # DUE ipotesi, non una (#234, incidente del proprietario 2026-08-03). Questo messaggio
        # ne nominava una sola — «il token è troppo stretto» — e chi lo seguiva alla lettera
        # quando la causa vera era l'altra allargava il token, faceva RIUSCIRE la pubblicazione
        # nel repository sbagliato, e le revoche smettevano di propagarsi in silenzio. Il 403
        # era più sicuro del successo che il messaggio suggeriva di ottenere: qui si mette
        # per PRIMA l'ipotesi che, se ignorata, produce il danno peggiore.
        return (f"Token accettato ma senza permesso di SCRITTURA{dove} (403). Due cause "
                "possibili, e vanno controllate IN QUEST'ORDINE:\n"
                "1) il REPOSITORY configurato non è quello giusto — dev'essere lo stesso da cui "
                "i bridge scaricano la lista. Se è questo il caso, NON allargare il token: la "
                "pubblicazione riuscirebbe nel posto sbagliato e nessuna revoca si "
                "propagherebbe, senza più alcun errore visibile;\n"
                "2) il token è troppo stretto — se è fine-grained: in «Repository access» "
                "dev'esserci questo repository, e in «Permissions → Repository permissions» "
                "serve «Contents: Read and write».")
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
    """Verifica **preventiva** che la pubblicazione funzionerà, **senza modificare nulla**.

    Ritorna ``{"ok", "message", "can_write", "file_exists"}``. **Non modifica mai** il repository:
    tre `GET` più **una `PUT` su un percorso usa-e-getta** (`probe_path`), **mai** sul file delle
    revoche, con uno `sha` riferito a un file inesistente. Non è una scrittura: è l'unica domanda a
    cui GitHub risponde con certezza su «questo token può scrivere?», perché i permessi sono
    validati **prima** dello sha. E se anche quella `PUT` venisse applicata da un proxy o un'API
    compatibile, nascerebbe un file inerte che nessun bridge legge — non una lista revoche
    corrotta (bloccante Fugu #215: rilevare il danno non è impedirlo).

    Perché non basta leggere il file (il caso reale del proprietario, 2026-08-03): il repository
    delle revoche è **pubblico**, quindi una `GET` riesce con qualunque token valido. Una verifica
    di sola lettura direbbe «tutto ok» e poi la pubblicazione fallirebbe con 403 — cioè
    esattamente il guasto che questa funzione dovrebbe prevenire. Per questo si legge
    ``permissions.push`` da `GET /repos/{owner}/{repo}` — ma è solo il **primo filtro**: è
    un'inferenza, e la prova vera è la `PUT` che non può riuscire (vedi sopra).

    ⚠️ Chi consuma l'esito deve guardare **`ok`**, non `can_write`. Nel ramo ANOMALIA — la `PUT`
    accettata nonostante lo sha costruito per fallire — `can_write` è `True` (il token ha
    dimostrato di poter scrivere: l'ha appena fatto) ma `ok` è `False`, perché il file potrebbe
    essere stato modificato. Chi si regolasse su `can_write` ignorerebbe il fail-closed
    (rilievo GPT-5.5 #215).

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
    esito["file_exists"] = status == 200

    # PROVA DEFINITIVA della scrittura (richiesta del proprietario, 2026-08-03). `permissions.push`
    # è un'INFERENZA: nessuna chiamata di sola lettura dice con certezza se un token *fine-grained*
    # può scrivere — se riportasse `push: true` con «Contents» in sola lettura, la sonda direbbe
    # «Accesso OK» proprio nel guasto che deve diagnosticare (rilievo Fugu #215).
    #
    # Si tenta una `PUT` sul percorso USA-E-GETTA (`probe_path`), MAI sul file delle revoche
    # (bloccante Fugu #215), con uno sha riferito a un file inesistente. GitHub valida i permessi
    # PRIMA dello sha: 403 = non può scrivere (prova definitiva), 409/422 = poteva, e nulla è
    # stato creato. Nel caso peggiore — una `PUT` comunque applicata da un proxy o un'API
    # compatibile — nasce un file inerte che nessun bridge legge, non una lista revoche corrotta.
    corpo = {"message": "verifica accesso (file temporaneo, ignorare)",
             "content": base64.b64encode(b"verifica accesso").decode("ascii"),
             "branch": str(branch or "").strip(), "sha": _SHA_PROBE}
    try:
        status_w, payload_w = caller("PUT", contents_url(repo, probe_path(path)), token=token,
                                     body=corpo, timeout=timeout)
    except Exception:       # noqa: BLE001 — rete a metà verifica: si dichiara ciò che si sa
        status_w, payload_w = None, None

    if status_w in (401, 403):
        esito["can_write"] = False
        esito["message"] = _error_message(status_w, "verifica", repo, payload_w)
        return esito
    if status_w is not None and 200 <= status_w < 300:
        rimosso = _rimuovi_file_di_prova(
            repo, path, branch, ((payload_w or {}).get("content") or {}).get("sha"),
            caller=caller, token=token, timeout=timeout)
        # Non avrebbe dovuto passare. Il danno è però circoscritto per costruzione: il file creato
        # NON è la lista revoche. Fail-closed lo stesso, dicendo la cosa che conta davvero.
        esito["can_write"] = True
        esito["ok"] = False
        coda = ("Il file temporaneo è stato rimosso automaticamente."
                if rimosso else
                f"Il file temporaneo «{probe_path(path)}» NON è stato rimosso: cancellalo a mano "
                "dal repository.")
        esito["message"] = (
            f"⚠️ ANOMALIA: la prova di scrittura è stata ACCETTATA da GitHub (HTTP {status_w}) "
            f"nonostante fosse costruita per fallire. La lista revoche «{path}» è **intatta** — la "
            f"prova scrive solo su «{probe_path(path)}». {coda} Segnala l'accaduto.")
        return esito

    if status_w not in (409, 422):
        # ESITO INCERTO — rete KO (`None`), 429, 5xx, o qualunque codice inatteso. Prima si finiva
        # nel ramo positivo con «✅ Accesso OK … non confermato»: fail-OPEN nel punto che deve
        # essere il più prudente di tutti (bloccante Fugu #215). Incerto non è OK: il permesso di
        # scrittura è l'unica cosa che questa sonda esiste per accertare, e se non l'ha accertata
        # deve dirlo senza spunta verde.
        esito["message"] = (
            f"⚠️ Verifica NON completata: il token risulta abilitato su «{repo}» e il branch "
            f"«{branch}» esiste, ma la prova del permesso di SCRITTURA non è andata a buon fine "
            + (f"(HTTP {status_w}). " if status_w is not None else "(rete non disponibile). ")
            + "Non è detto che ci sia un problema di permessi: riprova fra poco.")
        return esito

    esito["ok"] = True
    conferma = "Permesso di scrittura CONFERMATO da GitHub (prova senza modifiche)."
    if status == 200:
        dettaglio = f"Il file «{path}» esiste già e verrà aggiornato. {conferma}"
    elif status == 404:
        dettaglio = f"Il file «{path}» non c'è ancora: la prima pubblicazione lo creerà. {conferma}"
    else:
        dettaglio = f"Lo stato del file «{path}» non è stato letto. {conferma}"
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
