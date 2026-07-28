"""Client **bridge** della revoca online (issue #140 R3c): scarica la lista di revoche firmata da un
**URL statico**, la verifica, applica **anti-replay** e la usa nel **gate licenza fail-closed**.

Divisione delle responsabilità (coerente con `license.py`/`revocation.py`):

- **logica pura e testabile, qui**: fetch (dietro un *probe* iniettabile, come `wizard.py`), verifica +
  anti-replay (`accept_signed`), calcolo revoca per la licenza corrente (`license_revoked`) e la
  **decisione di gate** sincrona (`gate_allows`) — nessun thread, nessuna GUI;
- **orchestrazione (thread di refresh + cablaggio nel lock), in `app.py`**: un supervisore periodico
  aggiorna in memoria `(lista_verificata, verificata_a)`; il gate le legge **sincrono** (niente rete
  nel gate) e blocca **senza grazia** (decisione proprietario: il bridge deve **raggiungere e
  verificare** l'URL per operare).

Modello di sicurezza:

- la lista è **firmata Ed25519** con la chiave privata del proprietario (mai nel repo/EXE); il bridge
  verifica con la **pubblica** incorporata (`revocation.verify_revocation_list`, già fail-closed);
- **anti-replay/monotònia** (`min_iss`): una lista con `iss` **più vecchio** dell'ultima accettata è
  rifiutata → nessuno può «de-revocare» un utente ripubblicando una vecchia lista firmata;
- **fail-closed no-grace**: senza una lista **verificata e fresca**, `gate_allows` → `False`
  (bloccato). Il *cap* di freschezza assorbe i blip di rete transitori (il supervisore ritenta con
  backoff), ma un'irraggiungibilità **persistente** oltre la soglia blocca (decisione proprietario 2a).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse

from . import license as _license
from . import revocation

# ── URL statico della lista di revoche (decisione proprietario 1a: COSTANTE nel codice) ───────────
# URL **REALE** del proprietario: il repository GitHub pubblico su cui il License Manager pubblica la
# lista firmata (sezione «📤 Pubblicazione automatica», #157/#158). Pubblico e senza credenziali di
# proposito: il contenuto è **firmato Ed25519**, quindi l'hosting non è fidato — nessuno può falsificare
# «non revocato» senza il seed privato, che resta sul PC del proprietario e non entra mai nel repo/EXE.
#
# ⚠️ Impostare questo URL **ATTIVA** la revoca online (l'attivazione è derivata dall'URL, vedi
# `is_placeholder_url`): da qui in poi il gate è **fail-closed senza grazia** (decisione proprietario).
# Prerequisito operativo: il file deve **esistere** a questo indirizzo ed essere **ri-pubblicato almeno
# ogni `MAX_LIST_AGE_S`** (3 giorni). Se l'URL risponde 404 o la lista invecchia oltre il tetto, i bridge
# legittimi si **bloccano** — è il comportamento voluto, non un guasto.
_PLACEHOLDER_URL = "https://revoche.example.invalid/xtrader/revocation_list.txt"
REVOCATION_LIST_URL = (
    "https://raw.githubusercontent.com/zarbopiero963-droid/xtrader-revocation/main/revocation_list.txt"
)


def is_placeholder_url(url: "str | None") -> bool:
    """`True` se `url` è ancora un **placeholder di sviluppo** → revoca online **inattiva**. L'attivazione
    è **derivata dall'URL stesso**, non da un secondo flag dimenticabile (rilievo Fugu/GLM #156):
    impostare un URL reale **attiva** la revoca — impossibile lasciare «URL reale ma flag a True» e
    disattivarla in silenzio.

    Placeholder = URL vuoto, **esattamente** l'URL di TEST `_PLACEHOLDER_URL`, non parsabile, **senza
    host** (es. senza schema `revoke.x/list` o `https:///p`), o con **host** riservato `.invalid`
    (RFC 2606: host esatto `invalid` **o** che termina con `.invalid`). Il controllo è sull'**host**, non
    una substring sull'intero URL (rilievo Fable/Fugu #156): un URL reale con «invalid» nel path
    (`…/x.invalid.txt`) o in un host che solo la contiene (`revoke.invalid-x.com`) **non** è placeholder.
    Non parsabile / senza host → placeholder (fail-closed).

    NB (rilievo Fable/Fugu #156): `REVOCATION_LIST_URL` è una **costante di compilazione** (decisione 1a),
    NON configurabile a runtime — non esiste una «misconfigurazione runtime». Un URL placeholder/malformato
    → `True` → il **gate di release** (che legge questo stesso valore) **BLOCCA il tag**: non può finire in
    un EXE distribuito con revoca silenziosamente inattiva (fail-closed alla release, non fail-open)."""
    u = (url or "").strip()
    if not u or u.lower() == _PLACEHOLDER_URL.lower():
        return True     # vuoto o esattamente il placeholder di TEST (belt-and-suspenders)
    try:
        host = (urllib.parse.urlsplit(u).hostname or "").lower()
    except ValueError:
        return True     # URL non parsabile → placeholder (fail-closed: revoca inattiva, gate release blocca)
    return not host or host == "invalid" or host.endswith(".invalid")


# Marcatore booleano **DERIVATO** dall'URL (per il gate di release e i log) — NON una seconda fonte di
# verità: cambia automaticamente quando si imposta un URL reale.
REVOCATION_URL_IS_PLACEHOLDER = is_placeholder_url(REVOCATION_LIST_URL)

# File di cache della lista accettata (accanto a `license_state.json` in `config_dir()`).
REVOCATION_CACHE_FILE = "revocation_cache.json"

# Tempi (costanti di modulo; non config utente, coerente con 1a).
DEFAULT_FETCH_TIMEOUT_S = 10          # timeout della singola fetch HTTP
REFRESH_INTERVAL_S = 5 * 60           # cadenza normale di ri-scarico del supervisore
FRESHNESS_MAX_AGE_S = 15 * 60         # freschezza del FETCH: oltre → non si raggiunge l'URL → gate chiuso
# Freschezza del CONTENUTO firmato (`iss`): una lista firmata da più di questo tetto è considerata
# **stantia** anche se appena scaricata → gate chiuso (decisione proprietario: **3 giorni**, allargata
# dalle 24h iniziali). Chiude il **replay di una lista vecchia** (un utente revocato che serve alla
# propria copia una lista firmata precedente alla revoca): il proprietario **deve ri-pubblicare la
# lista firmata almeno ogni finestra** (anche invariata, automatizzato dalla pubblicazione #158),
# altrimenti i bridge legittimi si bloccano fail-closed.
#
# Perché 3 giorni e non 24h (decisione proprietario 2026-07-29). La finestra è **una sola costante per
# due effetti opposti**: quanto a lungo un revocato può resistere replayando una lista pre-revoca, e
# quanto a lungo il proprietario può stare senza ri-firmare prima che si blocchino gli utenti
# **legittimi**. La ri-firma richiede il seed privato, che vive solo sul PC del proprietario: con 24h
# bastava un weekend col PC spento per bloccare tutti. Tre giorni di resistenza di un revocato costano
# meno di un lockout generale, per un operatore singolo. Allargarla ancora è possibile ma allarga
# **esattamente** nella stessa misura la finestra di replay: è una scelta del proprietario, non un
# parametro da ritoccare di iniziativa.
MAX_LIST_AGE_S = 3 * 24 * 3600

# Tolleranza di **sfasamento d'orologio** per il verso opposto: una lista firmata nel **FUTURO** oltre
# questo margine è rifiutata. Serve contro un guasto che non richiede alcun attaccante — basta
# l'orologio sbagliato sul PC che firma, o una data futura impostata a mano:
#
# 1. `gate_allows` controlla solo il limite **superiore** (`now - issued > MAX_LIST_AGE_S`): una lista
#    datata avanti nel tempo dà una differenza **negativa** e passerebbe indisturbata, restando valida
#    ben oltre la finestra;
# 2. peggio, l'anti-replay è **monotòno** (`min_iss`): una volta accettata quella lista, ogni lista
#    **legittima successiva** — con `iss` reale, quindi più basso — viene **rifiutata**. Il proprietario
#    perde la capacità di revocare proprio su quella copia, e il danno **sopravvive al riavvio** perché
#    il floor viene ri-derivato dalla cache su disco (`app.py`, avvio del supervisore). Non è
#    rimediabile da remoto: servirebbe cancellare un file sul PC dell'utente.
#
# Il margine è **generoso di proposito**. Il confronto è fra l'orologio del BRIDGE e la data messa dal
# PROPRIETARIO: un margine stretto trasformerebbe un banale drift sul PC dell'utente in un lockout.
# Un'ora è enormemente più di qualunque deriva realistica (le macchine sincronizzate stanno nei
# secondi) e enormemente meno dei giorni che servono allo scenario di avvelenamento qui sopra.
MAX_FUTURE_SKEW_S = 3600

# Tetto di dimensione della lista scaricata (una lista di revoche resta piccola; evita di ingoiare un
# corpo enorme se l'URL è dirottato su altro).
_MAX_LIST_BYTES = 1_000_000


def revocation_cache_path(config_dir: "str | None" = None) -> str:
    """Percorso del file di cache. `config_dir=None` usa `config_store.config_dir()` (la stessa
    cartella di `license_state.json`)."""
    if config_dir is None:
        from xtrader_bridge import config_store
        config_dir = config_store.config_dir()
    return os.path.join(config_dir, REVOCATION_CACHE_FILE)


def load_cached_signed(path: str) -> "str | None":
    """Legge la lista firmata dall'ultima cache, o `None` se assente/corrotta (**fail-safe**: una cache
    illeggibile non fa crashare l'avvio, degrada a «nessuna cache» → il gate resterà chiuso finché non
    arriva una fetch fresca)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        signed = obj.get("signed") if isinstance(obj, dict) else None
        return signed if isinstance(signed, str) and signed else None
    except (OSError, ValueError):       # assente, JSON rotto, permessi: nessuna cache utilizzabile
        return None


def save_cached_signed(path: str, signed: str) -> None:
    """Scrive la lista firmata in cache in modo **atomico** (tmp + `os.replace`), con `fsync`. Gli
    errori di I/O propagano al chiamante (il supervisore li tratta best-effort)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"signed": str(signed)}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _default_fetch(url: str, *, timeout: int) -> str:
    """Fetch HTTP di default (urllib). Solleva su qualunque errore di rete/HTTP/decodifica; la
    gestione fail-closed è in `fetch_signed`. Cap di dimensione a `_MAX_LIST_BYTES`."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as resp:      # noqa: S310 — URL costante fidato
        raw = resp.read(_MAX_LIST_BYTES + 1)
    if len(raw) > _MAX_LIST_BYTES:
        raise ValueError("lista di revoche troppo grande")
    return raw.decode("utf-8").strip()


def fetch_signed(url: str = REVOCATION_LIST_URL, *, fetch=None,
                 timeout: int = DEFAULT_FETCH_TIMEOUT_S) -> "str | None":
    """Scarica la lista firmata dall'URL. **Fail-closed**: qualunque errore (rete, DNS, HTTP, timeout,
    TLS, decodifica, lista troppo grande) → `None` (nessuna lista → il gate resta chiuso). `fetch` è un
    *probe* iniettabile `(url, *, timeout) -> str` (default `_default_fetch`); i test ne passano uno
    finto che restituisce byte canonici o solleva, **senza socket reali**."""
    fetcher = fetch or _default_fetch
    try:
        text = fetcher(url, timeout=timeout)
    except Exception:       # noqa: BLE001 — qualunque problema di fetch: fail-closed → None
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


def accept_signed(signed: "str | None", *, public_key_hex: "str | None" = None,
                  min_iss: int = 0, now: "int | None" = None,
                  max_future_skew: int = MAX_FUTURE_SKEW_S) -> "revocation.RevocationList | None":
    """Verifica una lista firmata e applica **anti-replay**. Ritorna la `RevocationList` **solo se** la
    firma è valida (`verify_revocation_list`, già fail-closed), `iss >= min_iss` (monotònia: non si
    accetta una lista più vecchia dell'ultima già vista → nessun replay che «de-revoca») **e** `iss` non
    è nel **futuro** oltre `max_future_skew` (vedi `MAX_FUTURE_SKEW_S`). Altrimenti `None`.

    Il controllo sul futuro sta **qui**, non solo in `gate_allows`, perché è qui che nasce il danno
    **durevole**: è il valore accettato che alza il floor `min_iss` e che finisce in cache su disco. Una
    lista futura respinta a questo livello non lascia traccia — il floor resta dov'era e le liste
    legittime successive continuano a essere accettate.

    `now=None` legge l'orologio di sistema: la verifica c'è **sempre**, anche dai chiamanti che non
    passano un riferimento temporale (fail-closed, nessun percorso che salta il controllo)."""
    if not signed:
        return None
    revlist = revocation.verify_revocation_list(signed, public_key_hex=public_key_hex)
    if revlist is None:
        return None
    if int(revlist.issued) < int(min_iss):
        return None
    adesso = int(time.time()) if now is None else int(now)
    if int(revlist.issued) - adesso > int(max_future_skew):
        return None
    return revlist


def license_revoked(revlist: "revocation.RevocationList | None", *, token: "str | None",
                    hardware_id: "str | None") -> bool:
    """`True` se la licenza corrente è revocata dalla lista: il suo **serial** (deterministico dal
    token, `license.license_serial`) **o** il suo Hardware ID è nella lista. Token vuoto → `False`
    (nessuna licenza da revocare; la validità di base la stabilisce `verify_license`). `revlist=None`
    → `False` (la policy su lista assente è di `gate_allows`, non di qui)."""
    if not token:
        return False
    serial = _license.license_serial(token)
    return revocation.is_revoked(revlist, serial=serial, hardware_id=hardware_id)


def gate_allows(revlist: "revocation.RevocationList | None", *, verified_at: "int | None",
                now: int, token: "str | None", hardware_id: "str | None",
                max_age: int = FRESHNESS_MAX_AGE_S, max_iss_age: int = MAX_LIST_AGE_S,
                max_future_skew: int = MAX_FUTURE_SKEW_S) -> bool:
    """**Decisione di gate sincrona, fail-closed no-grace.** `True` **solo se**:

    1. esiste una lista **verificata** (`revlist is not None` e `verified_at is not None`);
    2. il **FETCH** è fresco (`now - verified_at <= max_age`): non si raggiunge più l'URL da troppo tempo
       (irraggiungibilità persistente) → `False` (no grazia; il supervisore ha ritentato con backoff);
    3. il **CONTENUTO firmato** è fresco (`now - issued <= max_iss_age`): una lista firmata troppo tempo
       fa — anche se appena scaricata — è **stantia/replay** → `False` (chiude il replay di una lista
       vecchia da parte dell'utente revocato; richiede ri-pubblicazione periodica lato proprietario);
    4. il contenuto **non è datato nel futuro** oltre `max_future_skew`: il punto 3 confronta un solo
       verso, e una data futura darebbe differenza **negativa** passando indisturbata (vedi
       `MAX_FUTURE_SKEW_S`). Ridondante con `accept_signed` di proposito: quella impedisce al valore di
       **entrare** (floor/cache), questa impedisce che conceda **immunità** se fosse già entrato;
    5. la licenza corrente **non è revocata** in quella lista.

    Nessuna rete qui: legge solo lo stato mantenuto dal supervisore → il gate resta istantaneo."""
    if revlist is None or verified_at is None:
        return False
    if int(now) - int(verified_at) > int(max_age):
        return False
    if int(now) - int(revlist.issued) > int(max_iss_age):
        return False
    if int(revlist.issued) - int(now) > int(max_future_skew):
        return False
    return not license_revoked(revlist, token=token, hardware_id=hardware_id)
