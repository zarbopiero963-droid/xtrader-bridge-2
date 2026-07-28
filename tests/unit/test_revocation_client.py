"""Test hard del **client bridge** della revoca online (`xtrader_bridge.licensing.revocation_client`,
#140 R3c). Logica pura fail-closed: fetch (probe iniettabile, nessun socket reale), verifica +
anti-replay (`accept_signed`), revoca della licenza corrente (`license_revoked`), gate no-grace
(`gate_allows`), cache. Nessun segreto reale: keypair generata al volo."""

import json
import time

from xtrader_bridge.licensing import license as lic
from xtrader_bridge.licensing import revocation, revocation_client

_HW = "HW1-1234-5678-9ABC-DEF0"
_HW2 = "HW1-AAAA-BBBB-CCCC-DDDD"
_NOW = 1_700_000_000


def _keypair():
    from license_manager import core
    return core.generate_keypair()   # (seed_hex, public_hex)


def _token(seed_hex, *, name="Mario Rossi", hw=_HW, iss=_NOW, exp=_NOW + 30 * 86_400):
    return lic.build_license(bytes.fromhex(seed_hex), name, hw, iss, exp)


def _signed_list(seed_hex, entries, *, now=_NOW):
    return revocation.build_revocation_list(bytes.fromhex(seed_hex), entries, now=now)


# ── fetch_signed (probe iniettabile, fail-closed) ─────────────────────────────────────────────────
def test_fetch_signed_probe_ok():
    called = {}

    def probe(url, *, timeout):
        called["url"] = url
        called["timeout"] = timeout
        return "  payload.firma  "
    out = revocation_client.fetch_signed("http://x/list", fetch=probe, timeout=7)
    assert out == "payload.firma"           # strip applicato
    assert called == {"url": "http://x/list", "timeout": 7}


def test_fetch_signed_probe_solleva_fail_closed():
    def boom(url, *, timeout):
        raise OSError("network down")       # simula URLError/timeout/TLS
    assert revocation_client.fetch_signed("http://x", fetch=boom) is None


def test_fetch_signed_vuoto_o_solo_spazi_none():
    assert revocation_client.fetch_signed("http://x", fetch=lambda u, *, timeout: "") is None
    assert revocation_client.fetch_signed("http://x", fetch=lambda u, *, timeout: "   \n") is None


def test_fetch_signed_default_url_costante():
    """`fetch_signed()` senza URL usa la costante di modulo (1a); il probe la riceve verbatim."""
    seen = {}
    revocation_client.fetch_signed(fetch=lambda u, *, timeout: seen.setdefault("u", u) or "x.y")
    assert seen["u"] == revocation_client.REVOCATION_LIST_URL


# ── is_placeholder_url (attivazione DERIVATA dall'URL) ────────────────────────────────────────────
def test_is_placeholder_url_deriva_attivazione_dall_url():
    """Vuoto / non parsabile / senza host / host in TLD `.invalid` → placeholder (revoca inattiva); un
    URL reale → attivo. Nessun secondo flag: impostare l'URL reale attiva da solo la revoca (Fugu/GLM
    #156)."""
    assert revocation_client.is_placeholder_url("") is True
    assert revocation_client.is_placeholder_url(None) is True
    assert revocation_client.is_placeholder_url(revocation_client._PLACEHOLDER_URL) is True
    assert revocation_client.is_placeholder_url("https://x.invalid/list.txt") is True
    assert revocation_client.is_placeholder_url("https://invalid/list.txt") is True   # host esatto "invalid"
    assert revocation_client.is_placeholder_url("https://revoke.mysite.com/list.txt") is False
    assert revocation_client.is_placeholder_url("http://revoke.mysite.com/l.txt") is False   # http reale
    # senza schema → `urlsplit` non trova host → placeholder (fail-closed: il proprietario deve usare
    # un URL con schema, es. https://…; il gate release blocca un default così malformato).
    assert revocation_client.is_placeholder_url("revoke.mysite.com/list.txt") is True
    assert revocation_client.is_placeholder_url("https:///solo-path") is True
    # match sull'HOST, non substring (rilievo Fable/Fugu #156): «invalid» nel PATH o in un host che solo
    # la contiene NON è placeholder → un URL reale non viene disattivato per sbaglio.
    assert revocation_client.is_placeholder_url("https://revoke.mysite.com/x.invalid.txt") is False
    assert revocation_client.is_placeholder_url("https://revoke.invalid-x.com/list.txt") is False
    # il marcatore derivato riflette l'URL configurato — garantito, non presupposto
    assert revocation_client.REVOCATION_URL_IS_PLACEHOLDER is \
        revocation_client.is_placeholder_url(revocation_client.REVOCATION_LIST_URL)


def test_url_reale_configurato_e_revoca_attiva():
    """L'URL di produzione è impostato e la revoca è **attiva** (#157).

    Blinda il valore esatto: un refuso in repository, branch o nome file non darebbe un errore
    evidente, darebbe un **404 silenzioso** → nessuna lista scaricabile → tutti i bridge bloccati
    fail-closed. Devono corrispondere schema, host, proprietario, repo, branch e nome del file —
    gli stessi che il License Manager usa per pubblicare (`publisher.raw_url`)."""
    url = revocation_client.REVOCATION_LIST_URL
    assert url == ("https://raw.githubusercontent.com/"
                   "zarbopiero963-droid/xtrader-revocation/main/revocation_list.txt")
    assert url.startswith("https://"), "solo HTTPS: su HTTP la lista sarebbe alterabile in transito"
    # l'attivazione è DERIVATA dall'URL: niente flag separato da ricordarsi
    assert revocation_client.is_placeholder_url(url) is False
    assert revocation_client.REVOCATION_URL_IS_PLACEHOLDER is False


def test_url_reale_e_quello_che_il_license_manager_pubblica():
    """L'URL nel bridge e quello prodotto dal License Manager devono essere lo **stesso**: sono i due
    capi della stessa catena (chi pubblica ↔ chi scarica). Se divergono, il bridge scarica da un
    indirizzo dove nessuno pubblica → lockout. Qui li confrontiamo generando il raw URL con la stessa
    funzione usata dalla GUI del tool."""
    from license_manager import publisher
    atteso = publisher.raw_url("zarbopiero963-droid/xtrader-revocation", "revocation_list.txt", "main")
    assert revocation_client.REVOCATION_LIST_URL == atteso


# ── accept_signed (verifica + anti-replay) ────────────────────────────────────────────────────────
def test_accept_signed_round_trip():
    seed_hex, public_hex = _keypair()
    signed = _signed_list(seed_hex, [{"serial": "LIC-DEAD"}], now=_NOW)
    rev = revocation_client.accept_signed(signed, public_key_hex=public_hex, min_iss=0)
    assert rev is not None and rev.issued == _NOW and "LIC-DEAD" in rev.serials


def test_accept_signed_anti_replay_rifiuta_iss_vecchio():
    """Monotònia: una lista con `iss` < `min_iss` (già vista una più recente) è rifiutata → nessun
    replay che «de-revoca» un utente ripubblicando una vecchia lista firmata."""
    seed_hex, public_hex = _keypair()
    signed_old = _signed_list(seed_hex, [{"serial": "LIC-DEAD"}], now=_NOW - 100)
    # min_iss più recente della lista → rifiutata
    assert revocation_client.accept_signed(signed_old, public_key_hex=public_hex, min_iss=_NOW) is None
    # stessa lista con min_iss <= iss → accettata
    assert revocation_client.accept_signed(signed_old, public_key_hex=public_hex,
                                           min_iss=_NOW - 100) is not None


def test_accept_signed_firma_sbagliata_o_vuota_none():
    seed_hex, _pub = _keypair()
    _s2, public_hex2 = _keypair()
    signed = _signed_list(seed_hex, [{"serial": "LIC-X"}], now=_NOW)
    assert revocation_client.accept_signed(signed, public_key_hex=public_hex2) is None   # chiave diversa
    assert revocation_client.accept_signed(None, public_key_hex=public_hex2) is None
    assert revocation_client.accept_signed("", public_key_hex=public_hex2) is None


# ── license_revoked (serial dal token + hw) ───────────────────────────────────────────────────────
def test_license_revoked_per_serial_del_token():
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    signed = _signed_list(seed_hex, [{"serial": serial}], now=_NOW)
    rev = revocation_client.accept_signed(signed, public_key_hex=public_hex)
    assert revocation_client.license_revoked(rev, token=token, hardware_id=_HW) is True
    # un token diverso (serial diverso) NON è revocato da quella lista
    other = _token(seed_hex, name="Altro Utente")
    assert revocation_client.license_revoked(rev, token=other, hardware_id=_HW) is False


def test_license_revoked_per_hardware_id():
    """Se la lista contiene un Hardware ID (blacklist macchina, entry manuale del proprietario), il
    bridge la onora anche se il serial non combacia."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    signed = _signed_list(seed_hex, [{"hw": _HW}], now=_NOW)
    rev = revocation_client.accept_signed(signed, public_key_hex=public_hex)
    assert revocation_client.license_revoked(rev, token=token, hardware_id=_HW) is True
    assert revocation_client.license_revoked(rev, token=token, hardware_id=_HW2) is False


def test_license_revoked_token_vuoto_o_lista_none_false():
    assert revocation_client.license_revoked(None, token="qualcosa", hardware_id=_HW) is False
    seed_hex, public_hex = _keypair()
    rev = revocation_client.accept_signed(_signed_list(seed_hex, [{"serial": "LIC-X"}]),
                                          public_key_hex=public_hex)
    assert revocation_client.license_revoked(rev, token="", hardware_id=_HW) is False
    assert revocation_client.license_revoked(rev, token=None, hardware_id=_HW) is False


# ── gate_allows (decisione sincrona fail-closed no-grace) ─────────────────────────────────────────
def test_gate_allows_lista_assente_o_verified_at_none_fail_closed():
    assert revocation_client.gate_allows(None, verified_at=_NOW, now=_NOW,
                                         token="t", hardware_id=_HW) is False
    seed_hex, public_hex = _keypair()
    rev = revocation_client.accept_signed(_signed_list(seed_hex, []), public_key_hex=public_hex)
    assert revocation_client.gate_allows(rev, verified_at=None, now=_NOW,
                                         token="t", hardware_id=_HW) is False


def test_gate_allows_stantia_fail_closed():
    """Lista verificata ma **troppo vecchia** (oltre `max_age`) → bloccato (no grazia su
    irraggiungibilità persistente)."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    rev = revocation_client.accept_signed(_signed_list(seed_hex, []), public_key_hex=public_hex)
    verified_at = _NOW
    fresh_now = _NOW + revocation_client.FRESHNESS_MAX_AGE_S           # esattamente al limite → ok
    stale_now = _NOW + revocation_client.FRESHNESS_MAX_AGE_S + 1       # oltre → stantia
    assert revocation_client.gate_allows(rev, verified_at=verified_at, now=fresh_now,
                                         token=token, hardware_id=_HW) is True
    assert revocation_client.gate_allows(rev, verified_at=verified_at, now=stale_now,
                                         token=token, hardware_id=_HW) is False


def test_gate_allows_contenuto_troppo_vecchio_fail_closed():
    """**Anti-replay per età del CONTENUTO firmato** (decisione proprietario: 3 giorni): una lista appena
    scaricata (fetch fresco) ma **firmata** oltre `MAX_LIST_AGE_S` fa → `False`. Chiude il replay di una
    lista vecchia da parte dell'utente revocato. I limiti si derivano dalla costante, non ricopiati."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    old_iss = _NOW - revocation_client.MAX_LIST_AGE_S - 1        # firmata 24h+ fa
    rev_old = revocation_client.accept_signed(_signed_list(seed_hex, [], now=old_iss),
                                              public_key_hex=public_hex, min_iss=0)
    # fetch fresco (verified_at ora), ma iss troppo vecchio → bloccato
    assert revocation_client.gate_allows(rev_old, verified_at=_NOW, now=_NOW,
                                         token=token, hardware_id=_HW) is False
    # esattamente al limite (24h) → ancora consentito
    edge_iss = _NOW - revocation_client.MAX_LIST_AGE_S
    rev_edge = revocation_client.accept_signed(_signed_list(seed_hex, [], now=edge_iss),
                                               public_key_hex=public_hex, min_iss=0)
    assert revocation_client.gate_allows(rev_edge, verified_at=_NOW, now=_NOW,
                                         token=token, hardware_id=_HW) is True


def test_gate_allows_fresca_e_non_revocata_true_revocata_false():
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    # lista vuota fresca → consentito
    rev_ok = revocation_client.accept_signed(_signed_list(seed_hex, []), public_key_hex=public_hex)
    assert revocation_client.gate_allows(rev_ok, verified_at=_NOW, now=_NOW,
                                         token=token, hardware_id=_HW) is True
    # lista che revoca IL serial corrente, fresca → bloccato
    rev_bad = revocation_client.accept_signed(_signed_list(seed_hex, [{"serial": serial}]),
                                              public_key_hex=public_hex)
    assert revocation_client.gate_allows(rev_bad, verified_at=_NOW, now=_NOW,
                                         token=token, hardware_id=_HW) is False


# ── cache (fail-safe) ─────────────────────────────────────────────────────────────────────────────
def test_cache_round_trip(tmp_path):
    path = revocation_client.revocation_cache_path(str(tmp_path))
    revocation_client.save_cached_signed(path, "payload.firma")
    assert revocation_client.load_cached_signed(path) == "payload.firma"


def test_cache_assente_o_corrotta_none(tmp_path):
    path = revocation_client.revocation_cache_path(str(tmp_path))
    assert revocation_client.load_cached_signed(path) is None        # assente
    with open(path, "w", encoding="utf-8") as f:
        f.write("{non-json")                                         # corrotta
    assert revocation_client.load_cached_signed(path) is None
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"altro": 1}, f)                                   # senza 'signed'
    assert revocation_client.load_cached_signed(path) is None


# ── data nel FUTURO: skew tollerato, avvelenamento del floor impedito ─────────────────────────────
def test_accept_signed_rifiuta_lista_datata_oltre_lo_skew_nel_futuro():
    """`gate_allows` confronta un solo verso (`now - issued > max_iss_age`): una lista datata **avanti**
    darebbe differenza negativa e passerebbe indisturbata. La guardia sul futuro chiude quel verso.
    Il limite esatto è **incluso** (`<= skew` accettato), come per l'età massima."""
    seed_hex, public_hex = _keypair()
    skew = revocation_client.MAX_FUTURE_SKEW_S
    al_limite = _signed_list(seed_hex, [], now=_NOW + skew)
    oltre = _signed_list(seed_hex, [], now=_NOW + skew + 1)
    assert revocation_client.accept_signed(
        al_limite, public_key_hex=public_hex, now=_NOW) is not None
    assert revocation_client.accept_signed(
        oltre, public_key_hex=public_hex, now=_NOW) is None


def test_accept_signed_tollera_orologio_del_bridge_indietro():
    """Il confronto è fra l'orologio del BRIDGE e la data messa dal PROPRIETARIO: un bridge con
    l'orologio **indietro** vede la lista legittima come «futura». Con uno skew stretto quel banale
    drift diventerebbe un **lockout**; qui un bridge indietro di mezz'ora accetta ancora."""
    seed_hex, public_hex = _keypair()
    legittima = _signed_list(seed_hex, [], now=_NOW)
    bridge_indietro = _NOW - 1800        # orologio del bridge 30 min indietro
    assert revocation_client.accept_signed(
        legittima, public_key_hex=public_hex, now=bridge_indietro) is not None


def test_accept_signed_futuro_NON_avvelena_il_floor_min_iss():
    """La regressione che conta. L'anti-replay è **monotòno**: se una lista datata nel futuro entra, il
    floor `min_iss` sale a quella data e ogni lista **legittima successiva** — con `iss` reale, più
    basso — viene rifiutata. Il proprietario perde la capacità di revocare su quella copia, e il danno
    sopravvive al riavvio perché il floor si ri-deriva dalla cache su disco.

    Qui si esercitano ENTRAMBI i rami sullo stesso scenario: con la guardia attiva il floor non si
    muove e la lista legittima passa; disattivandola (skew enorme) si riproduce l'avvelenamento. Senza
    il secondo ramo il test non dimostrerebbe che è la guardia a fare la differenza."""
    seed_hex, public_hex = _keypair()
    futura = _signed_list(seed_hex, [], now=_NOW + 7 * 86_400)          # datata fra una settimana
    legittima = _signed_list(seed_hex, [{"serial": "LIC-REVOCATO"}], now=_NOW)

    # --- con la guardia (comportamento voluto) ---
    floor = 0
    accolta = revocation_client.accept_signed(futura, public_key_hex=public_hex,
                                              min_iss=floor, now=_NOW)
    assert accolta is None, "una lista datata a +7 giorni non deve essere accettata"
    floor = max(floor, accolta.issued) if accolta is not None else floor
    assert floor == 0, "il floor non deve muoversi per una lista respinta"
    dopo = revocation_client.accept_signed(legittima, public_key_hex=public_hex,
                                           min_iss=floor, now=_NOW)
    assert dopo is not None and "LIC-REVOCATO" in dopo.serials, \
        "la revoca legittima successiva deve continuare a essere accettata"

    # --- senza la guardia: l'avvelenamento che il fix impedisce ---
    floor_rotto = 0
    avvelenata = revocation_client.accept_signed(futura, public_key_hex=public_hex,
                                                 min_iss=floor_rotto, now=_NOW,
                                                 max_future_skew=10 * 365 * 86_400)
    assert avvelenata is not None                      # entra solo perché la guardia è disattivata
    floor_rotto = max(floor_rotto, avvelenata.issued)
    assert revocation_client.accept_signed(legittima, public_key_hex=public_hex,
                                           min_iss=floor_rotto, now=_NOW) is None, \
        "senza guardia la revoca legittima viene rifiutata: è esattamente il guasto da impedire"


def test_accept_signed_senza_now_controlla_comunque_il_futuro():
    """`now=None` (chiamante che non passa un riferimento temporale) **non** salta il controllo: legge
    l'orologio di sistema. Un percorso che salta la verifica sarebbe fail-open."""
    seed_hex, public_hex = _keypair()
    fra_un_anno = int(time.time()) + 365 * 86_400
    assert revocation_client.accept_signed(
        _signed_list(seed_hex, [], now=fra_un_anno), public_key_hex=public_hex) is None
    adesso = int(time.time())
    assert revocation_client.accept_signed(
        _signed_list(seed_hex, [], now=adesso), public_key_hex=public_hex) is not None


def test_gate_allows_rifiuta_contenuto_datato_nel_futuro():
    """Ridondanza voluta col controllo in `accept_signed`: quella impedisce alla lista di **entrare**
    (floor/cache), questa impedisce che conceda **immunità** se fosse già entrata per altra via."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    skew = revocation_client.MAX_FUTURE_SKEW_S
    # costruita bypassando la guardia d'ingresso, per esercitare il gate da solo
    futura = revocation_client.accept_signed(
        _signed_list(seed_hex, [], now=_NOW + skew + 1), public_key_hex=public_hex,
        now=_NOW, max_future_skew=10 * 365 * 86_400)
    assert futura is not None                       # precondizione del test, non l'asserzione
    assert revocation_client.gate_allows(futura, verified_at=_NOW, now=_NOW,
                                         token=token, hardware_id=_HW) is False


def test_finestra_freschezza_contenuto_e_di_tre_giorni():
    """Contratto della finestra (decisione proprietario 2026-07-29). Non è un numero qualsiasi: regge
    il compromesso fra quanto un revocato resiste replayando e quanto il proprietario può stare senza
    ri-firmare prima di bloccare gli utenti **legittimi** (la ri-firma richiede il seed, che vive solo
    sul suo PC). Cambiarlo è una decisione del proprietario: questo test lo rende esplicito."""
    assert revocation_client.MAX_LIST_AGE_S == 3 * 24 * 3600
    assert revocation_client.MAX_FUTURE_SKEW_S < revocation_client.MAX_LIST_AGE_S
