"""Test hard della **pubblicazione su GitHub** della lista revoche (#157).

Esercitano la logica reale di `license_manager.publisher` con un **probe HTTP finto** (nessun socket,
nessun token reale): costruzione URL, create-vs-update via `sha`, mappatura degli errori HTTP e
l'invariante «**il token non compare MAI** nel risultato»."""

import base64
import json
import urllib.parse

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
