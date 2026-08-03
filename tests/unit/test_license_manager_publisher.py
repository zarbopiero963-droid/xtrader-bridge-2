"""Test hard della **pubblicazione su GitHub** della lista revoche (#157).

Esercitano la logica reale di `license_manager.publisher` con un **probe HTTP finto** (nessun socket,
nessun token reale): costruzione URL, create-vs-update via `sha`, mappatura degli errori HTTP e
l'invariante «**il token non compare MAI** nel risultato»."""

import base64
import json
import urllib.parse

import pytest

from license_manager import publisher

_REPO = "tizio/xtrader-revocation"
_PATH = "revocation_list.txt"
_BRANCH = "main"
_TOKEN = "ghp_TOKEN_FINTO_SEGRETO"
_SIGNED = "payload.firma"


class _FakeHttp:
    """Probe HTTP registrante: risponde con la coda di `(status, payload)` programmata."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, *, token, body=None, timeout=None):
        self.calls.append({"method": method, "url": url, "token": token, "body": body})
        return self.responses.pop(0) if self.responses else (200, {})


# ── URL ──────────────────────────────────────────────────────────────────────────────────────────
def test_raw_url_e_quello_da_mettere_nel_bridge():
    assert publisher.raw_url(_REPO, _PATH, _BRANCH) == \
        "https://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt"
    # tollera spazi e slash iniziali/finali di troppo
    assert publisher.raw_url(" tizio/x/ ", "/l.txt", " main ") == \
        "https://raw.githubusercontent.com/tizio/x/main/l.txt"


def test_contents_url_quota_il_path():
    assert publisher.contents_url(_REPO, _PATH) == \
        "https://api.github.com/repos/tizio/xtrader-revocation/contents/revocation_list.txt"
    assert "%20" in publisher.contents_url(_REPO, "cartella con spazi/l.txt")


# ── get_file_sha ─────────────────────────────────────────────────────────────────────────────────
def test_get_file_sha_trovato():
    http = _FakeHttp((200, {"sha": "abc123"}))
    sha, err = publisher.get_file_sha(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert sha == "abc123" and err is None
    assert http.calls[0]["method"] == "GET" and "ref=main" in http.calls[0]["url"]


def test_get_file_sha_404_e_creazione():
    """404 = file non ancora presente → `(None, None)`: non è un errore, si creerà."""
    sha, err = publisher.get_file_sha(_REPO, _PATH, _BRANCH, token=_TOKEN, http=_FakeHttp((404, None)))
    assert sha is None and err is None


def test_get_file_sha_errori_mappati():
    """401 e 403 attendevano entrambi la parola «permessi»: era il contratto di quando i due
    codici condividevano UN messaggio solo. Dal collaudo del 2026-08-03 sono distinti, perché
    chiedono rimedi opposti — rigenerare il token contro concedergli un permesso — e l'atteso
    qui diventa il codice HTTP, che è ciò che davvero identifica il guasto."""
    for status, atteso in ((401, "401"), (403, "403"), (500, "GitHub non disponibile")):
        sha, err = publisher.get_file_sha(_REPO, _PATH, _BRANCH, token=_TOKEN,
                                          http=_FakeHttp((status, None)))
        assert sha is None and err is not None and atteso.lower() in err.lower()


def test_get_file_sha_rete_ko_fail_safe():
    def boom(method, url, *, token, body=None, timeout=None):
        raise OSError("DNS down")
    sha, err = publisher.get_file_sha(_REPO, _PATH, _BRANCH, token=_TOKEN, http=boom)
    assert sha is None and "rete" in err.lower()


# ── publish ──────────────────────────────────────────────────────────────────────────────────────
def test_publish_crea_il_file_se_assente():
    http = _FakeHttp((404, None), (201, {"content": {}}))       # GET 404 → PUT create
    out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                            message="msg", http=http)
    assert out["ok"] is True and out["action"] == "created"
    put = http.calls[1]
    assert put["method"] == "PUT" and "sha" not in put["body"]   # creazione: nessuno sha
    assert put["body"]["branch"] == _BRANCH and put["body"]["message"] == "msg"
    # il contenuto viaggia in base64 ed è ESATTAMENTE la lista firmata
    assert base64.b64decode(put["body"]["content"]).decode("utf-8") == _SIGNED


def test_publish_aggiorna_con_sha_se_presente():
    http = _FakeHttp((200, {"sha": "vecchio"}), (200, {"content": {}}))
    out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                            message="msg", http=http)
    assert out["ok"] is True and out["action"] == "updated"
    assert http.calls[1]["body"]["sha"] == "vecchio"            # aggiornamento: sha obbligatorio


def test_publish_token_mancante_fail_closed():
    http = _FakeHttp()
    out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token="",
                            message="m", http=http)
    assert out["ok"] is False and "token" in out["message"].lower()
    assert http.calls == []                                     # non tenta nemmeno la chiamata


def test_publish_errori_http_mappati():
    for status in (401, 403, 404, 409, 422, 429, 500):
        http = _FakeHttp((404, None), (status, None))           # GET ok(create) → PUT fallisce
        out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                                message="m", http=http)
        assert out["ok"] is False and out["message"]


def test_publish_rete_ko_fail_safe():
    calls = {"n": 0}

    def flaky(method, url, *, token, body=None, timeout=None):
        calls["n"] += 1
        if method == "GET":
            return 404, None
        raise OSError("connessione persa")
    out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                            message="m", http=flaky)
    assert out["ok"] is False and "rete" in out["message"].lower()


def test_publish_non_espone_mai_il_token():
    """Invariante #157: il token è passato nell'header ma NON deve comparire in nessun messaggio."""
    for responses in (((404, None), (201, {})), ((401, None),), ((404, None), (500, None))):
        out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                                message="m", http=_FakeHttp(*responses))
        assert _TOKEN not in json.dumps(out)


# ── sicurezza: nessun follow dei redirect (leak del token) — rilievo Fable #158 ─────────────────
def test_redirect_non_seguito_per_non_esporre_il_token():
    """`urllib` di default segue i 3xx **ri-inviando `Authorization: Bearer <token>`** all'host di
    destinazione (anche diverso da api.github.com) → leak del token. L'handler deve rifiutare il
    redirect ritornando `None`, così il 3xx diventa un errore invece di una richiesta altrove."""
    handler = publisher._NoRedirectHandler()
    esito = handler.redirect_request(None, None, 302, "Found", {},
                                     "https://host-ostile.example/rubami-il-token")
    assert esito is None, "il redirect NON deve essere seguito (il token viaggerebbe altrove)"


def test_opener_monta_lhandler_no_redirect():
    """L'opener usato per le chiamate reali monta l'handler che blocca i redirect."""
    opener = publisher._build_opener()
    assert any(isinstance(h, publisher._NoRedirectHandler) for h in opener.handlers)


def test_messaggio_3xx_spiega_il_blocco_senza_esporre_il_token():
    for status in (301, 302, 307):
        out = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                                message="m", http=_FakeHttp((404, None), (status, None)))
        assert out["ok"] is False and "redirect" in out["message"].lower()
        assert _TOKEN not in out["message"]


def test_raw_url_e_contents_url_codificano_allo_stesso_modo():
    """I due URL devono codificare **identicamente** (rilievo Fugu #158): l'API pubblica al path
    codificato, quindi un raw URL grezzo punterebbe a un file inesistente → il bridge non scarica più
    la lista → lockout fail-closed di tutti i bridge."""
    path_con_spazi = "cartella con spazi/lista revoche.txt"
    raw = publisher.raw_url(_REPO, path_con_spazi, _BRANCH)
    api = publisher.contents_url(_REPO, path_con_spazi)
    assert " " not in raw, "il raw URL non può contenere spazi grezzi"
    # la parte «path» dei due URL è codificata allo stesso modo
    assert raw.split(f"/{_BRANCH}/", 1)[1] == api.split("/contents/", 1)[1]
    # gli slash dei path annidati restano slash (non %2F)
    assert "/" in raw.split(f"/{_BRANCH}/", 1)[1]


def test_raw_url_quota_anche_il_branch():
    raw = publisher.raw_url(_REPO, "l.txt", "feature/mia branch")
    assert " " not in raw and "feature/mia%20branch" in raw


def test_url_pubblicato_coincide_con_quello_che_il_bridge_scarica():
    """I **due capi della stessa catena** devono coincidere: l'URL che questo tool pubblica e la
    costante `REVOCATION_LIST_URL` da cui il bridge scarica (#157). Se divergono, il bridge cerca la
    lista dove nessuno la pubblica → nessuna lista fresca → **lockout fail-closed di tutti i bridge**.

    Il confronto sta QUI e non nella suite del bridge di proposito (rilievo Fable #159): l'import
    `license_manager → xtrader_bridge` è la direzione **consentita** dall'isolamento #140; l'opposto
    farebbe dipendere i test del bridge dal tool del proprietario."""
    from xtrader_bridge.licensing import revocation_client
    atteso = publisher.raw_url("zarbopiero963-droid/xtrader-revocation", "revocation_list.txt", "main")
    assert revocation_client.REVOCATION_LIST_URL == atteso


def test_raw_url_branch_con_slash_resta_un_percorso_valido():
    """`quote` lascia intatti gli `/`: un branch tipo `feature/x` resta due segmenti di path, che è
    esattamente la forma che raw.githubusercontent.com si aspetta (rilievo GPT-5.5 #158)."""
    assert publisher.raw_url(_REPO, _PATH, "feature/x") == \
        "https://raw.githubusercontent.com/tizio/xtrader-revocation/feature/x/revocation_list.txt"


def test_il_branch_viaggia_codificato_nella_query_ref_non_nel_path():
    """Dove finisce il branch nella chiamata all'API (rilievo GLM 5.2 #158): `contents_url` **non lo
    prende** — va in `?ref=`, codificato da `urlencode`. Quindi non può divergere da `raw_url`: qui è
    una query-string, là un segmento di path, e il valore che GitHub ri-decodifica è identico."""
    http = _FakeHttp((200, {"sha": "s"}))
    publisher.get_file_sha(_REPO, _PATH, "feature/mia branch", token=_TOKEN, http=http)
    url = http.calls[0]["url"]
    assert " " not in url, "il branch deve essere codificato, mai grezzo nell'URL"
    parsed = urllib.parse.urlparse(url)
    assert parsed.path.endswith("/contents/revocation_list.txt")          # branch NON nel path
    assert urllib.parse.parse_qs(parsed.query)["ref"] == ["feature/mia branch"]


def test_i_due_url_quotano_anche_il_repo_e_allo_stesso_modo():
    """Seconda rete dopo `validate_config` (rilievo Fable #158): se qualcuno arriva qui **senza**
    passare dalla validazione (config scritta a mano, chiamata diretta al modulo), un `?` grezzo nel
    `repo` trasformerebbe il resto dell'URL in query-string → richiesta a un path diverso. E i due URL
    devono quotare **negli stessi termini**: se lo facesse uno solo tornerebbe la divergenza raw↔API."""
    brutto = "owner/na?me"
    raw = publisher.raw_url(brutto, _PATH, _BRANCH)
    api = publisher.contents_url(brutto, _PATH)
    assert "?" not in raw and "?" not in api, "il carattere riservato deve essere codificato"
    assert raw.startswith("https://raw.githubusercontent.com/owner/na%3Fme/")
    assert api.startswith("https://api.github.com/repos/owner/na%3Fme/contents/")
    # lo `/` fra owner e nome resta uno slash (non %2F) in entrambi
    assert "/owner/na%3Fme/" in raw and "/owner/na%3Fme/" in api
    # un repository legittimo NON viene toccato dalla quotatura
    assert publisher.raw_url(_REPO, _PATH, _BRANCH) == \
        "https://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt"


def test_publish_manda_il_branch_letterale_nel_corpo_json():
    """Nel `PUT` il branch sta nel **corpo JSON**, non in un URL: lì va **letterale** (percent-encodarlo
    creerebbe un branch inesistente). È l'unico punto in cui NON si quota, e questo test lo fissa."""
    http = _FakeHttp((404, None), (201, {}))
    publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch="feature/x", token=_TOKEN,
                      message="m", http=http)
    assert http.calls[1]["body"]["branch"] == "feature/x"


# ── 401 ≠ 403: due guasti opposti, due messaggi (collaudo proprietario 2026-08-03) ───────────────
#
# Trovato installando il License Manager su un secondo PC: la pubblicazione falliva e il messaggio
# diceva «Token non valido o senza permessi sul repository». Il proprietario l'ha letta come DUE
# diagnosi, mentre era una frase sola che copre due cause che chiedono rimedi opposti:
#   401 → GitHub rifiuta il token in sé (sbagliato, scaduto, revocato, troncato nell'incollare);
#   403 → il token è buono ma non ha scrittura su quel repo (fine-grained senza «Contents: R/W»).
# Senza distinguerle non si può riparare se non per tentativi.

def test_401_dice_che_il_token_e_rifiutato_non_i_permessi():
    msg = publisher._error_message(401, "scrittura")
    assert "401" in msg
    basso = msg.lower()
    assert "scadut" in basso or "revocat" in basso or "rifiutat" in basso, msg
    assert "contents" not in basso, (
        "un 401 non è un problema di permessi: mandare l'utente a cambiare i permessi del token "
        f"lo fa girare a vuoto — {msg!r}")


def test_403_dice_che_mancano_i_permessi_di_scrittura():
    msg = publisher._error_message(403, "scrittura", repo=_REPO)
    assert "403" in msg
    basso = msg.lower()
    assert "contents" in basso and ("read and write" in basso or "scrittur" in basso), msg
    assert _REPO in msg, "il messaggio non dice SU QUALE repo mancano i permessi"


def test_i_messaggi_401_e_403_sono_diversi():
    assert publisher._error_message(401, "scrittura") != publisher._error_message(403, "scrittura")


def test_nessun_messaggio_di_errore_contiene_mai_il_token():
    for status in (401, 403, 404, 409, 422, 429, 301, 500):
        assert _TOKEN not in publisher._error_message(status, "scrittura", repo=_REPO)


# ── check_access: la verifica preventiva, in SOLA LETTURA ────────────────────────────────────────

def test_check_access_ok_quando_il_token_puo_scrivere():
    # GET /repos/... → permissions.push=True ; poi GET contents → 200 (il file esiste già)
    http = _FakeHttp((200, {"permissions": {"push": True, "pull": True}}), (200, {"sha": "abc"}))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is True and res["can_write"] is True
    assert http.calls[0]["method"] == "GET" and http.calls[1]["method"] == "GET", \
        "la verifica NON deve scrivere nulla sul repository"


def test_check_access_su_repo_pubblico_senza_scrittura_NON_dice_va_tutto_bene():
    """Il caso reale del proprietario. Su un repo PUBBLICO la lettura riesce con qualunque token
    valido: una verifica di sola lettura direbbe «tutto ok» e poi la pubblicazione fallirebbe con
    403. Per questo si legge `permissions.push`, che è la capacità di SCRIVERE."""
    http = _FakeHttp((200, {"permissions": {"push": False, "pull": True}}))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is False and res["can_write"] is False
    assert "contents" in res["message"].lower(), res["message"]


def test_check_access_401_token_rifiutato():
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=_FakeHttp((401, None)))
    assert res["ok"] is False and res["can_write"] is False
    assert "401" in res["message"]


def test_check_access_404_repo_inesistente_o_non_concesso():
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=_FakeHttp((404, None)))
    assert res["ok"] is False
    assert "404" in res["message"] or "non trovat" in res["message"].lower()


def test_check_access_file_non_ancora_presente_resta_OK():
    """404 sul FILE non è un errore: la prima pubblicazione lo crea. Deve restare `ok=True`,
    altrimenti la verifica spaventerebbe l'utente prima della prima pubblicazione.

    Le risposte sono TRE da quando il branch viene sondato (rilievo Fugu #215): repo → branch →
    file. Prima erano due, e il 404 del file era l'ultima — ora quella posizione è del branch, e
    lasciare due risposte farebbe cadere il 404 sul branch, provando tutt'altro."""
    http = _FakeHttp((200, {"permissions": {"push": True}}),   # repo scrivibile
                     (200, {"name": "main"}),                   # branch esiste
                     (404, None))                               # file no: si creerà
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is True and res["file_exists"] is False


def test_check_access_senza_token_non_chiama_la_rete():
    http = _FakeHttp()
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token="", http=http)
    assert res["ok"] is False and http.calls == [], "ha contattato GitHub senza token"


def test_check_access_rete_ko_fail_safe():
    def esplode(*_a, **_k):
        raise OSError("dns")
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=esplode)
    assert res["ok"] is False and "rete" in res["message"].lower()


def test_check_access_non_espone_mai_il_token():
    for risposte in ([(401, None)], [(403, None)], [(404, None)],
                     [(200, {"permissions": {"push": False}})]):
        res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=_FakeHttp(*risposte))
        assert _TOKEN not in json.dumps(res, ensure_ascii=False)


# ── 403 non è sempre «permessi»: GitHub lo usa anche per il rate-limit (rilievo Fable #215) ──────

def test_403_da_rate_limit_non_manda_a_cambiare_i_permessi():
    """GitHub risponde 403 **anche** per il rate-limit secondario. Mandare l'utente a modificare i
    permessi del token quando deve solo aspettare lo fa girare a vuoto — ed è il difetto che questa
    PR sta correggendo, riprodotto un livello più in là."""
    corpo = {"message": "You have exceeded a secondary rate limit. Please wait a few minutes."}
    msg = publisher._error_message(403, "scrittura", repo=_REPO, payload=corpo)
    basso = msg.lower()
    assert "limit" in basso or "attend" in basso or "riprova" in basso, msg
    assert "contents" not in basso, f"manda a cambiare i permessi per un rate-limit: {msg!r}"


def test_403_da_rate_limit_non_ripete_il_corpo_grezzo_di_github():
    """Il corpo della risposta non va mai ri-emesso: potrebbe riportare header o dettagli della
    richiesta. Si riconosce il marcatore e si scrive un messaggio NOSTRO."""
    corpo = {"message": "secondary rate limit", "documentation_url": "https://example.invalid/x"}
    msg = publisher._error_message(403, "scrittura", repo=_REPO, payload=corpo)
    assert "example.invalid" not in msg and "documentation_url" not in msg


def test_403_senza_marcatore_resta_il_messaggio_dei_permessi():
    """Non-regressione: il 403 «vero» (permessi) non deve essere scambiato per un rate-limit."""
    for corpo in (None, {}, {"message": "Resource not accessible by personal access token"}):
        msg = publisher._error_message(403, "scrittura", repo=_REPO, payload=corpo)
        assert "contents" in msg.lower(), f"{corpo!r} → {msg!r}"


def test_check_access_403_da_rate_limit_lo_dice(monkeypatch):
    http = _FakeHttp((403, {"message": "You have exceeded a secondary rate limit."}))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is False
    assert "contents" not in res["message"].lower(), res["message"]


def test_una_sola_frase_per_manca_il_token(monkeypatch):
    """Regola 3 (rilievo Sourcery #215): `publish` e `check_access` dicevano la stessa cosa con due
    frasi diverse. Ora la fonte è una — se qualcuno ne riscrivesse una a mano, questo test cade."""
    a = publisher.publish("x", repo=_REPO, path=_PATH, branch=_BRANCH, token="", message="m")
    b = publisher.check_access(_REPO, _PATH, _BRANCH, token="")
    assert a["message"] == b["message"] == publisher.MSG_TOKEN_MANCANTE


def test_una_sola_costruzione_dellurl_contents_con_ref():
    """Rilievo CodeRabbit #215 (regola 3): `check_access` e `get_file_sha` devono interrogare
    ESATTAMENTE lo stesso URL. Se un domani divergessero, la verifica direbbe «il file c'è» su un
    indirizzo diverso da quello che la pubblicazione poi aggiorna."""
    http_a = _FakeHttp((200, {"permissions": {"push": True}}), (200, {"sha": "x"}))
    publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http_a)
    http_b = _FakeHttp((200, {"sha": "x"}))
    publisher.get_file_sha(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http_b)
    assert http_a.calls[-1]["url"] == http_b.calls[-1]["url"]


def test_publish_403_da_rate_limit_lo_distingue_anche_in_SCRITTURA():
    """Rilievo GPT-5.5 #215: il ramo `publish` passa il corpo a `_error_message`, ma nulla lo
    pretendeva. È il ramo che conta di più — il 403 da rate-limit arriva quasi sempre sulla PUT,
    non sulla GET: mandare l'utente a cambiare i permessi mentre deve solo aspettare è proprio il
    difetto che questa PR chiude."""
    http = _FakeHttp((200, {"sha": "abc"}),                                   # GET: il file c'è
                     (403, {"message": "You have exceeded a secondary rate limit."}))   # PUT
    res = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                            message="m", http=http)
    assert res["ok"] is False
    assert "contents" not in res["message"].lower(), res["message"]
    assert _TOKEN not in res["message"]


def test_publish_403_senza_rate_limit_resta_il_messaggio_dei_permessi():
    """Non-regressione del gemello: il 403 «vero» in scrittura deve continuare a dire cosa
    concedere al token."""
    http = _FakeHttp((200, {"sha": "abc"}), (403, {"message": "Resource not accessible"}))
    res = publisher.publish(_SIGNED, repo=_REPO, path=_PATH, branch=_BRANCH, token=_TOKEN,
                            message="m", http=http)
    assert res["ok"] is False and "contents" in res["message"].lower()
    assert _REPO in res["message"]


# ── Il branch dev'essere sondato, non dato per buono (rilievo Fugu #215) ─────────────────────────

def test_check_access_branch_inesistente_NON_dice_accesso_ok():
    """Un branch sbagliato (un «master» al posto di «main», un refuso) faceva passare la verifica
    con «✅ Accesso OK … branch <quello sbagliato>», e la pubblicazione poi falliva. È un falso-OK
    proprio nella funzione che esiste per evitarli, e cita pure il branch inesistente come se fosse
    stato controllato.

    Causa: `GET contents?ref=X` risponde 404 sia per «file non ancora presente» sia per «branch
    inesistente», e il primo caso è legittimo. I due si distinguono solo sondando il branch."""
    http = _FakeHttp((200, {"permissions": {"push": True}}),   # repo scrivibile
                     (404, None))                              # branch NON esiste
    res = publisher.check_access(_REPO, _PATH, "branch-che-non-esiste", token=_TOKEN, http=http)
    assert res["ok"] is False, f"falso «Accesso OK» su un branch inesistente: {res['message']!r}"
    assert "branch" in res["message"].lower()
    assert "branch-che-non-esiste" in res["message"]


def test_check_access_branch_esistente_e_file_assente_resta_OK():
    """Contro-prova: branch valido + file non ancora presente resta `ok` — è la prima
    pubblicazione, e spaventare l'utente lì sarebbe un falso allarme."""
    http = _FakeHttp((200, {"permissions": {"push": True}}),   # repo
                     (200, {"name": "main"}),                   # branch c'è
                     (404, None))                               # file no: si creerà
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is True and res["file_exists"] is False


def test_check_access_sonda_il_branch_e_non_MODIFICA_nulla():
    """Contratto aggiornato il 2026-08-03. Prima pretendeva «nessun PUT»; ora la sonda ne fa UNA,
    deliberatamente, perché è l'unico modo di sapere con certezza se il token può scrivere. Ciò che
    va sorvegliato non è più «non fa PUT» ma «la PUT non può MODIFICARE nulla»: sha diverso per
    costruzione, e una sola."""
    sha = "abc123" + "0" * 34            # sha PLAUSIBILE: 40 esadecimali (il probe ne pretende uno)
    http = _FakeHttp((200, {"permissions": {"push": True}}), (200, {"name": "main"}),
                     (200, {"sha": sha}), (409, None))
    publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    metodi = [c["method"] for c in http.calls]
    assert metodi == ["GET", "GET", "GET", "PUT"], metodi
    assert "/branches/" in http.calls[1]["url"]
    assert http.calls[3]["body"]["sha"] != sha, "la PUT avrebbe MODIFICATO il file"


# ── Prova DEFINITIVA della scrittura, senza scrivere (richiesta del proprietario 2026-08-03) ─────
#
# `permissions.push` è un'inferenza: nessuna chiamata di sola lettura dice con certezza se un token
# fine-grained può SCRIVERE. L'unica prova certa è tentare — e GitHub verifica i permessi PRIMA
# dello `sha`, quindi un PUT con uno sha volutamente sbagliato distingue i due casi senza scrivere.

_SHA_REALE = "a" * 40


def _http_fino_al_probe(*coda):
    """repo scrivibile → branch esiste → file esiste (sha noto) → poi la coda del test."""
    return _FakeHttp((200, {"permissions": {"push": True}}),
                     (200, {"name": "main"}),
                     (200, {"sha": _SHA_REALE}),
                     *coda)


def test_probe_scrittura_403_smaschera_il_falso_ok_di_permissions_push():
    """Il caso che rende inutile la sonda: `push: true` ma niente «Contents: Read and write».
    Senza questo probe la verifica direbbe «✅ Accesso OK» proprio nel guasto da diagnosticare."""
    http = _http_fino_al_probe((403, {"message": "Resource not accessible by personal access token"}))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is False, f"falso «Accesso OK» nonostante il 403 in scrittura: {res!r}"
    assert res["can_write"] is False
    assert "contents" in res["message"].lower()


@pytest.mark.parametrize("status", [409, 422])
def test_probe_scrittura_conflitto_significa_PERMESSO_CONFERMATO(status):
    """409/422 = «avresti potuto scrivere, ma lo sha non combacia»: è la conferma del permesso.
    Nulla è stato modificato."""
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN,
                                 http=_http_fino_al_probe((status, {"message": "sha mismatch"})))
    assert res["ok"] is True and res["can_write"] is True


def test_probe_scrittura_manda_uno_sha_DIVERSO_da_quello_reale():
    """L'invariante di sicurezza. Se il probe mandasse lo sha REALE la scrittura andrebbe a buon
    fine e sovrascriverebbe la lista revoche con un contenuto segnaposto. Lo sha inviato dev'essere
    diverso PER COSTRUZIONE — non «improbabile»: diverso."""
    http = _http_fino_al_probe((409, None))
    publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    put = [c for c in http.calls if c["method"] == "PUT"]
    assert len(put) == 1, "il probe deve fare UNA sola PUT"
    inviato = (put[0]["body"] or {}).get("sha")
    assert inviato and inviato != _SHA_REALE, (
        f"il probe ha inviato lo sha REALE ({inviato!r}): la scrittura sarebbe RIUSCITA")
    assert len(inviato) == len(_SHA_REALE)


def test_probe_scrittura_NON_parte_se_il_file_non_esiste_ancora():
    """Senza sha reale non si può costruire uno sha «diverso per costruzione», e una PUT senza sha
    CREEREBBE il file. Quindi il probe si astiene, e la verifica lo dichiara invece di fingere."""
    http = _FakeHttp((200, {"permissions": {"push": True}}), (200, {"name": "main"}), (404, None))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert [c["method"] for c in http.calls] == ["GET", "GET", "GET"], "ha scritto senza sha reale"
    assert res["ok"] is True and res["file_exists"] is False
    testo = res["message"].lower()
    assert "non è stato verificato" in testo or "non è stato confermato" in testo, \
        f"promette una scrittura che non ha provato: {res['message']!r}"


# ── Il probe dev'essere FAIL-CLOSED sull'esito più pericoloso (bloccanti GPT-5.5 #215) ───────────

@pytest.mark.parametrize("status", [200, 201])
def test_probe_scrittura_ACCETTATA_e_un_allarme_non_un_ok(status):
    """Il caso peggiore possibile, e finora finiva nel ramo «ok». Se GitHub accettasse la PUT
    nonostante lo sha fittizio — o se rispondesse un proxy/API compatibile — il file **è stato
    modificato**, e dire «Accesso OK» sarebbe la bugia più dannosa che questa funzione possa
    raccontare: l'utente crederebbe di aver solo verificato, mentre la lista revoche pubblicata
    non è più quella firmata."""
    http = _http_fino_al_probe((status, {"content": {}}))
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is False, f"una PUT ACCETTATA riportata come «ok»: {res!r}"
    testo = res["message"].lower()
    assert "modificat" in testo or "accettata" in testo, res["message"]
    assert "ripubblica" in testo, "non dice all'utente come rimettere a posto il file"


@pytest.mark.parametrize("sha_anomalo", ["x", "", "   ", "abc", "z" * 40, "a" * 39, "a" * 41, None])
def test_probe_NON_parte_con_uno_sha_reale_non_plausibile(sha_anomalo):
    """`_sha_che_non_combacia` accettava qualunque stringa non vuota: con un payload anomalo («x»)
    avrebbe inviato «0», una richiesta semanticamente diversa da quella attesa. Se lo sha reale non
    è uno sha Git plausibile (40 esadecimali) non si può costruire un «diverso per costruzione»
    affidabile → ci si astiene, che è l'unica scelta sicura."""
    http = _http_fino_al_probe()   # nessuna risposta in coda: se partisse, si vedrebbe la PUT
    http.responses[2] = (200, {"sha": sha_anomalo})
    publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert [c["method"] for c in http.calls] == ["GET", "GET", "GET"], \
        f"probe partito con sha reale {sha_anomalo!r}: {[c['method'] for c in http.calls]}"


def test_sha_che_non_combacia_rifiuta_gli_sha_non_plausibili():
    assert publisher._sha_che_non_combacia("a" * 40) != "a" * 40
    assert len(publisher._sha_che_non_combacia("a" * 40)) == 40
    for cattivo in ("x", "", "abc", "z" * 40, "a" * 39, "a" * 41, None):
        assert publisher._sha_che_non_combacia(cattivo) == "", cattivo


def test_astensione_per_sha_anomalo_lo_DICHIARA_invece_di_promettere():
    """Buco trovato verificando la patch dei bloccanti: con uno sha reale non plausibile il probe
    si astiene (giusto), ma il messaggio diceva comunque «✅ Accesso OK … verrà aggiornato», senza
    alcun accenno al fatto che la scrittura NON era stata provata. È la stessa promessa non
    mantenuta che si era evitata nel caso «file non ancora esistente»: qui va detta uguale."""
    http = _http_fino_al_probe()
    http.responses[2] = (200, {"sha": "non-uno-sha"})
    res = publisher.check_access(_REPO, _PATH, _BRANCH, token=_TOKEN, http=http)
    assert res["ok"] is True
    testo = res["message"].lower()
    assert "non è stato verificato" in testo or "non è stato confermato" in testo, \
        f"promette una scrittura che non ha provato: {res['message']!r}"
