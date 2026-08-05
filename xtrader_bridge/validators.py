"""Helper condivisi di validazione/sanitizzazione input (fonte UNICA, anti-drift).

Raccoglie regole prima **duplicate** in più moduli safety-critical, così una
correzione non rischia di applicarsi a una copia e dimenticarne un'altra
(audit #105 / #133 item 6, parte "validatori"):

- `require_positive_int` / `require_finite_now`: validazione difensiva di
  parametri numerici e timestamp — un valore malformato (bool da JSON, NaN/inf,
  ``<= 0``, non intero) deve fallire con `ValueError`, non rendere un limite
  inefficace o sempre bloccante. Usati da `safety_guard.DailyLimiter` e
  `signal_dedupe.SignalTracker`.
- `WIN_RESERVED` + `safe_filename_core`: nucleo comune della sanitizzazione del
  nome file (Windows). I chiamanti (`custom_parser`, `profile_store`) applicano
  poi il PROPRIO fallback, volutamente diverso (vedi sotto), quindi qui resta solo
  la parte condivisa.

Modulo **puro**: nessuna dipendenza da GUI/CSV/Telegram, testabile headless.
"""

import math
import re

# Nomi device riservati di Windows: un file con questo nome-base (anche con
# estensione) non è creabile. Match ESATTO, case-insensitive (es. "con" sì,
# "console" no). Fonte unica condivisa.
WIN_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


# ── Classi di eccezione degli input ostili — FONTE UNICA (regola 3, #194 PR-E) ──────
#
# Perché esistono queste due costanti invece di ripetere le tuple nei singoli `except`.
# Prima della #194 PR-E il repository aveva OTTO siti che scrivevano a mano
# `except (TypeError, ValueError)` attorno a una `float()`, e TUTTI lasciavano passare
# `OverflowError`. Non per distrazione: la tupla stretta è quella che viene in mente, e
# `OverflowError` non è sottoclasse di `ValueError`, quindi il difetto è invisibile finché
# qualcuno non prova un intero enorme. Scritte una volta sola, un domani si estendono in un
# posto solo — che è esattamente ciò che le otto copie NON permettevano.

#: Classi che una CONVERSIONE numerica (`float()`/`int()`) può sollevare su input ostile.
#: `OverflowError` (#318 L1-1): un intero troppo grande per un float — es. ``10**400``,
#: che `json.loads` accetta senza protestare — quindi raggiungibile da un `config.json`
#: editato a mano o da uno stato persistito manomesso.
NUMERIC_ERRORS = (TypeError, ValueError, OverflowError)

#: Classi che il PARSING di un JSON ostile può sollevare **oltre** a `JSONDecodeError`.
#: `RecursionError`: `json` decodifica ricorsivamente, quindi un documento annidato
#: migliaia di livelli la solleva prima di finire. `OverflowError`: il letterale
#: `Infinity`, che `json.loads` accetta per default, esplode alla prima conversione a int.
#: Nessuna delle due è sottoclasse di `ValueError` (#240 B9).
CORRUPT_JSON_ERRORS = (RecursionError, OverflowError)


def numero_finito(value) -> bool:
    """`True` se `value` è un numero **finito**, senza convertirlo. Non solleva **mai**.

    Fonte UNICA (regola 3) del ramo numerico delle coercizioni booleane fail-closed:
    `autostart.coerce_enabled`, `config_store.as_bool_optin`,
    `source_manager.as_enabled_bool` e `source_manager._is_recognized_off`. Quei quattro
    siti hanno vocabolari di **stringhe** diversi di proposito (``"si"`` è un sì per le
    sorgenti e non per gli opt-in di privacy), ma sul **numero** devono dire tutti la
    stessa cosa — e finché sono state quattro copie non l'hanno detta (#278).

    Perché non basta `math.isfinite`, che sarebbe la scrittura ovvia: un `int` di Python
    non ha limite di grandezza, un `float` sì, quindi `math.isfinite(10**400)` non
    risponde «no», **solleva** ``OverflowError``. Un valore del genere entra da un
    `config.json` **valido** (``json.loads`` lo accetta senza protestare), e il crash
    arriva dentro `load_config`: l'app non si apre più e nessun recupero scatta, perché
    non c'è nulla di corrotto da recuperare. Il difetto era stato corretto in tre siti su
    quattro, ciascuno con il proprio commento — e il quarto, `autostart`, era proprio
    quello sul percorso di avvio.

    Un `int` è quindi **sempre** finito e va deciso senza conversione; solo il ramo
    `float` può (e deve) chiedere la finitezza, perché lì ``inf``/``nan`` esistono davvero.

    I `bool` sono esclusi di proposito, come negli altri validatori di questo modulo:
    ``float(True)`` è ``1.0``, e trattare un ``true`` come il numero 1 nasconderebbe una
    config malformata invece di segnalarla. I chiamanti gestiscono il caso `bool` **prima**
    di interrogare questo predicato.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def finite_or_none(value):
    """`value` come float **finito**, oppure ``None``. Non solleva **mai**.

    Il gemello non-sollevante di `require_finite_now`, per i siti che hanno un default o un
    fallback invece di un fail-fast: là dove il codice scriveva
    ``try: float(x) except (TypeError, ValueError): return default``, ora si scrive
    ``v = finite_or_none(x)`` e si decide su ``None``.

    Rifiuta `bool` per la stessa ragione degli altri validatori di questo modulo:
    ``float(True)`` è ``1.0``, quindi un ``true`` finito per errore in un campo numerico
    passerebbe per il valore 1 invece di essere trattato come config malformata — trappola
    già costata un bug su `saved_at` (#199) e uno su `clear_delay`.
    """
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except NUMERIC_ERRORS:
        return None
    return f if math.isfinite(f) else None


def require_positive_int(value, name: str) -> int:
    """`value` come int finito e > 0, altrimenti `ValueError`.

    Rifiuta esplicitamente `bool` (``True``/``False`` da JSON verrebbero coerciti a
    1/0: es. `max_per_day=True` capperebbe l'app a 1 segnale/giorno invece di essere
    trattato come config malformata) e `NaN`/`inf`/`<= 0`/non-interi (renderebbero il
    limite inefficace o sempre bloccante)."""
    if isinstance(value, bool):
        raise ValueError(f"{name} non valido: {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError (#318 L1-1): un int troppo grande per un float (es. 10**400) — da config
        # corrotta/manomessa — NON è sottoclasse di ValueError, quindi senza catturarlo esplicito
        # `float()` propagherebbe e farebbe crashare l'handler/START. Trattato come malformato
        # (ValueError controllato), coerente con message_freshness/csv_writer.
        raise ValueError(f"{name} non valido: {value!r}") from None
    if not math.isfinite(f) or f <= 0 or f != int(f):
        raise ValueError(f"{name} deve essere un intero > 0 (ricevuto {value!r})")
    return int(f)


def require_finite_now(now) -> float:
    """`now` (epoch) come float finito, altrimenti `ValueError`.

    Rifiuta `bool` (``True``/``False`` non sono timestamp) e `NaN`/`inf`, che
    falserebbero finestra di deduplica, conteggio al minuto e reset giornaliero."""
    if isinstance(now, bool):
        raise ValueError(f"now non valido: {now!r}")
    try:
        f = float(now)
    except (TypeError, ValueError, OverflowError):
        # OverflowError (#318 L1-1): un int troppo grande per un float (es. 10**400) non è
        # sottoclasse di ValueError → senza catturarlo `float()` crasherebbe il chiamante
        # (DailyLimiter/SignalTracker). Trattato come `now` malformato (ValueError controllato).
        raise ValueError(f"now non valido: {now!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"now deve essere finito (ricevuto {now!r})")
    return f


def has_unresolved_placeholder(value) -> bool:
    """`True` se il valore contiene un placeholder dinamico **non sostituito**.

    FONTE UNICA del predicato (#194 PR-I, regola 3). Prima ne esistevano **quattro**, e tre
    erano più permissivi del quarto — con effetti diversi ma la stessa causa:

    | sito | predicato | difetto |
    |---|---|---|
    | `value_maps._is_placeholder` | `"{" or "}"` | nessuno: indurito dalla #16 L2-2 |
    | `dizionario.has_placeholder` | `\\{[A-Z_]+\\}` | **B10**: cieco su `{HOME_TEAM`, `HOME_TEAM}`, `{home_team}` |
    | `mapping.resolve_selection` | `"{" in nome` | **B18**: vede `{`, mai `}` |
    | `custom_parser_engine.matches_message` | *nessuno* | **B16**: il placeholder contava come contenuto |

    **La regola: UNA sola graffa basta.** I valori betting reali — nomi squadra, mercati,
    selezioni, quote — non contengono **mai** graffe, quindi la presenza di una `{` o di una
    `}` è già segno di sostituzione non avvenuta. Un placeholder troncato (`{HOME_TEAM` senza
    chiusura, o `HOME_TEAM}` senza apertura) è un template rotto, non un nome: trattarlo come
    dato reale significa scrivere spazzatura nel CSV, o peggio far scattare un parser con ID
    fissi su un messaggio che non porta alcun dato. Fail-closed per costruzione.

    Un match per *forma esatta* (`\\{[A-Z_]+\\}`) sarebbe più elegante e sarebbe **sbagliato**:
    riconosce solo i placeholder scritti bene, cioè esattamente quelli che non fanno danno.

    Non solleva mai: il valore arriva da JSON e da CSV editabili a mano, e questo predicato
    decide se **scartare** una selezione — un'eccezione qui trasformerebbe una guardia in un
    crash.

    **Non-stringa: `str(value)`, non `str(value or "")`** (rilievo GPT-5.5 sulla #252). La
    seconda forma collassa ogni valore *falsy* a stringa vuota, e su un `dict` produceva una
    risposta che dipendeva dal contenuto: `{}` → `False` (falsy → `""`) ma `{"a": 1}` → `True`
    (`str` dà `"{'a': 1}"`). Due risposte diverse per lo stesso tipo, e quella permissiva sul
    caso vuoto. Con `str(value)` un non-stringa che *si scrive* con graffe è coerentemente un
    placeholder → scartato: se una struttura arriva fin qui è un errore di programmazione, e
    fail-closed è la direzione giusta. È anche l'idioma già usato in `csv_writer._sanitize_cell`
    (`"" if value is None else str(value)`), quindi il repository ne ha uno solo."""
    s = "" if value is None else str(value)
    return "{" in s or "}" in s


_PLACEHOLDER_TOKEN_RE = re.compile(r"\{([A-Z_]+)\}")


def substitute_placeholders(value, valori: dict) -> str:
    """Sostituisce i placeholder `{NOME}` in **una sola passata**, senza mai riesaminare
    il testo inserito. FONTE UNICA della sostituzione (#194 PR-I, B19).

    Un nome assente da `valori`, o mappato a stringa vuota, lascia il placeholder
    **invariato**: è il contratto su cui i chiamanti contano per accorgersi che il valore non
    è completabile e scartare la selezione, invece di scrivere un nome vuoto.

    **Perché una passata sola.** Prima c'erano due implementazioni, entrambe a `replace`
    concatenati (`mapping._subst` e `dizionario.fill_placeholders`), e i nomi squadra arrivano
    **verbatim dal messaggio Telegram**. Con le sostituzioni in sequenza un `home` che
    *contiene* `{AWAY_TEAM}` veniva inserito al posto di `{HOME_TEAM}` e poi riesaminato dal
    passaggio successivo, che lo trasformava nella squadra **avversaria**:

        _subst("{HOME_TEAM}", home="{AWAY_TEAM}", away="Milan")  ->  "Milan"   # PRIMA
        _subst("{HOME_TEAM}", home="{AWAY_TEAM}", away="Milan")  ->  "{AWAY_TEAM}"  # ORA

    La selezione «vittoria casa» diventava «vittoria trasferta» — il lato invertito, che è la
    prima invariante che `CLAUDE.md` protegge. Con `re.sub` e una callback ogni occorrenza è
    sostituita una volta e il risultato è finale."""
    def _sostituisci(m):
        return str(valori.get(m.group(1), "") or "") or m.group(0)

    return _PLACEHOLDER_TOKEN_RE.sub(_sostituisci, str(value))


def safe_filename_core(name: str) -> str:
    """Nucleo condiviso della sanitizzazione di un nome file (Windows).

    Tiene solo alfanumerici, ``-``, ``_`` e spazi (poi spazi → ``_``); evita path
    traversal e caratteri non validi; prefissa con ``_`` i NOMI DEVICE RISERVATI
    (``con``/``nul``/``com1``…). Ritorna la stringa pulita, **eventualmente vuota**:
    il fallback su vuoto è LASCIATO al chiamante, perché diverge per dominio —
    `custom_parser` usa un default (``"parser"``), `profile_store` rifiuta il nome
    vuoto. Per questo i due `_safe_filename` restano funzioni separate, ma il nucleo
    è unico (anti-drift).

    Annotato `name: str` per il contratto, ma `str(name)` resta come rete difensiva:
    un chiamante che passi un non-stringa per errore non deve far crashare l'I/O."""
    cleaned = "".join(c for c in str(name).strip() if c.isalnum() or c in " -_")
    cleaned = "_".join(cleaned.split())
    if cleaned.casefold() in WIN_RESERVED:
        cleaned = "_" + cleaned
    return cleaned
