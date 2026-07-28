"""Test hard della **pubblicazione su GitHub** della lista revoche (#157).

Esercitano la logica reale di `license_manager.publisher` con un **probe HTTP finto** (nessun socket,
nessun token reale): costruzione URL, create-vs-update via `sha`, mappatura degli errori HTTP e
l'invariante «**il token non compare MAI** nel risultato»."""

import base64
import json

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
    for status, atteso in ((401, "permessi"), (403, "permessi"), (500, "GitHub non disponibile")):
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
