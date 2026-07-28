"""PR-14c: report diagnostico testuale per il supporto (logica pura, testabile).

Costruisce il testo che il pulsante "Copia diagnostica" mette negli appunti: stato
del bridge, contatori, ultimi eventi e percorsi utili. È **puro** (nessun widget) e
applica sempre la redazione dei segreti (`event_log.redact_secrets`), così un token
incollato per sbaglio in un campo non finisce mai nel report condiviso col supporto.

**Privacy del report condiviso (C1, audit #114).** Questo testo nasce per essere
INCOLLATO in una segnalazione: oltre ai token deve uscire senza i due dati personali
che il report portava con sé in chiaro —

- il **chat_id** Telegram, sostituito dall'impronta stabile `chat:sha256:<12 hex>` di
  `log_privacy.redact_chat_id` (la stessa del diario eventi: correlabile, non rivelata);
- lo **username del PC** dentro i path (``C:\\Users\\<nome>\\…``, ``/home/<nome>/…``),
  sostituito da `MASKED_USER`.

La redazione dei chat_id è **esatta**, non euristica: sostituisce solo i valori
realmente presenti in config (`collect_chat_ids`), mai "i numeri che sembrano un id" —
un report coi contatori storpiati sarebbe inutile al supporto.
"""

import re

from . import __version__, event_log, log_privacy

_TITLE = "XTrader Signal Bridge — diagnostica"

#: Segnaposto che prende il posto dello username nei path del report.
MASKED_USER = "<utente>"

#: Sotto questa lunghezza un valore NON è trattato come chat_id (vedi `redact_chat_ids`).
MIN_CHAT_ID_LEN = 5

# Prefisso dei chat_id di supergruppo/canale: `-100` + id interno. È l'id INTERNO (senza
# prefisso) a comparire nei link `t.me/c/<id>/<msg>` generati da Telegram.
_SUPERGROUP_PREFIX = "-100"

# Home utente stile Windows/macOS: un segmento di path chiamato `Users` seguito da un nome,
# **ovunque si trovi**. Copre `C:\Users\<nome>`, `C:/Users/<nome>`, `/Users/<nome>` (macOS) e
# tutte le forme di rete: `\\Server\Users\<nome>` (CodeRabbit #164) ma anche `\\Server\C$\Users\
# <nome>` (admin share) e `\\Server\Condivisa\Users\<nome>` (home annidate, Fable #164). Un primo
# tentativo ancorava `Users` subito dopo l'unità o il server: copriva il caso semplice e lasciava
# in chiaro proprio quelli aziendali.
#
# Scelta deliberatamente FAIL-SAFE VERSO LA PRIVACY: se una cartella si chiama davvero `Users`
# senza essere una home, si perde un nome di file nel report; nella direzione opposta si
# perderebbe il nome di una persona. Il CSV su share di rete non è un caso di laboratorio — è lo
# scenario da cui nasce l'intero Tema A dell'audit #114.
#
# Il lookbehind accetta separatore, spazio o inizio campo: copre anche un path RELATIVO
# `Users\<nome>` digitato a mano in «CSV Path» (Fugu #164), e continua a rifiutare `Users`
# come suffisso di un altro nome (`ProjectUsers\<x>`, `SuperUsers\<x>`) — lì non c'è nessuna
# home e mascherare storpierebbe soltanto.
#
# Due alternative per il nome, non una (Fable #164): un nome utente PUÒ contenere spazi
# (`C:\Users\Mario Rossi\`), ma consentirli senza vincoli faceva divorare l'INTERA riga a una
# frase come «Active Users/list non raggiungibile» — over-masking distruttivo per la
# diagnosi, non solo un dettaglio. Quindi:
#   1. nome seguito da un separatore → spazi ammessi, è inequivocabilmente un path;
#   2. nome a fine riga o prima di uno spazio → niente spazi, si maschera una sola parola.
_WIN_HOME_RE = re.compile(
    r"(?<![^\s\\/])(Users[\\/]{1,2})"
    r"(?:[^\\/\r\n]+?(?=[\\/])|[^\s\\/\r\n]+(?=\s|$))", re.IGNORECASE)
# Home utente Linux: `/home/<nome>/`. Qui il lookbehind serve: "home" è una parola comune e una
# cartella che si CHIAMA così in mezzo a un path (`C:/Progetti/home/segnali.csv`) non contiene
# nessuno username da proteggere, quindi storpiarla confonderebbe soltanto la diagnosi.
_POSIX_HOME_RE = re.compile(r"(?<![\w.\-])(/home/)([^/\s\r\n]+)")

# Chiavi di config che contengono un chat_id singolo.
_CHAT_ID_KEYS = ("chat_id", "xtrader_notification_chat_id")
# Mappe la cui CHIAVE è un chat_id.
_CHAT_KEYED_MAPS = ("parser_by_chat", "parser_list_by_chat")


def mask_user_paths(text) -> str:
    """Sostituisce lo username dentro le home directory con `MASKED_USER`.

    Il resto del path resta leggibile (al supporto serve sapere *dove* sta il CSV, non
    *chi* è l'utente): sparisce solo il segmento subito dopo `Users`/`home`. Un path senza
    home utente — ``D:\\XTrader\\dati``, una share ``\\\\NAS\\condivisa`` — passa **invariato**."""
    s = str(text or "")
    s = _WIN_HOME_RE.sub(lambda m: m.group(1) + MASKED_USER, s)
    return _POSIX_HOME_RE.sub(lambda m: m.group(1) + MASKED_USER, s)


def collect_chat_ids(cfg) -> tuple:
    """Tutti i chat_id presenti nella config, da ogni fonte, deduplicati e ordinati dal
    più lungo (vedi `redact_chat_ids`: i più lunghi vanno sostituiti per primi).

    Fonti: `chat_id`, `xtrader_notification_chat_id`, ogni voce di `source_chats` e le
    **chiavi** di `parser_by_chat` / `parser_list_by_chat`. Una config malformata (vecchia,
    editata a mano) non solleva: si raccoglie ciò che c'è."""
    if not isinstance(cfg, dict):
        return ()
    trovati = set()

    def _aggiungi(value):
        s = str(value).strip() if value is not None else ""
        if s:
            trovati.add(s)

    for key in _CHAT_ID_KEYS:
        _aggiungi(cfg.get(key))
    chats = cfg.get("source_chats")
    if isinstance(chats, (list, tuple)):
        for voce in chats:
            if isinstance(voce, dict):
                _aggiungi(voce.get("chat_id"))
    for key in _CHAT_KEYED_MAPS:
        mappa = cfg.get(key)
        if isinstance(mappa, dict):
            for chiave in mappa:
                _aggiungi(chiave)
    return tuple(sorted(trovati, key=lambda s: (-len(s), s)))


def redact_chat_ids(text, chat_ids) -> str:
    """Sostituisce ogni `chat_ids` presente in `text` con la sua impronta stabile.

    Tre cautele, tutte dettate dal fatto che un report storpiato non serve a nessuno:

    - **confini numerici**: `12345` non viene sostituito dentro `9912345678` (contatori,
      timestamp, id evento restano leggibili);
    - **tutte le grafie dello stesso id**: un supergruppo è `-1001234567890` in config, ma
      l'API Telegram lo cita spesso senza il meno (`1001234567890`) e i link generati da
      Telegram usano l'id **interno** senza il prefisso `-100`
      (`t.me/c/1234567890/45`) — un campo libero come «Ultimo messaggio» basterebbe a farlo
      trapelare. Si redigono tutte e tre, con la **stessa** impronta: è la stessa chat, e un
      report che sembrasse parlare di due chat diverse sarebbe fuorviante;
    - **soglia `MIN_CHAT_ID_LEN`**: un valore di 1-2 cifre non è un chat_id Telegram reale
      (campo di prova, config mezza compilata) e sostituirlo cancellerebbe ogni cifra
      uguale del report.

    I più lunghi sono sostituiti per primi, così `-1001234567890` non viene mangiato a
    metà dalla forma corta (stessa logica di `event_log.redact_secrets`)."""
    s = str(text or "")
    canonici = {str(raw).strip() for raw in chat_ids or () if raw is not None}
    voci = []
    for raw in chat_ids or ():
        canonico = str(raw).strip() if raw is not None else ""
        if len(canonico) < MIN_CHAT_ID_LEN:
            continue
        impronta = log_privacy.redact_chat_id(canonico)
        if not impronta:
            continue
        # Stesso id, tre grafie possibili: come in config, senza il segno (API Telegram) e
        # senza il prefisso `-100` dei supergruppi (id interno dei link `t.me/c/<id>/<msg>`).
        forme = {canonico, canonico.lstrip("-")}
        if canonico.startswith(_SUPERGROUP_PREFIX):
            forme.add(canonico[len(_SUPERGROUP_PREFIX):])
        for forma in forme:
            if len(forma) < MIN_CHAT_ID_LEN:
                continue
            # Collisione (GPT-5.5 #164): la forma DERIVATA di una chat può coincidere con
            # l'id CONFIGURATO di un'altra (supergruppo `-1001234567890` + chat `1234567890`).
            # In quel caso vince l'id configurato esplicitamente: entrambe le chat restano
            # comunque redatte, ma l'impronta mostrata è quella della chat che l'utente ha
            # davvero scritto in config — l'alternativa sarebbe un'attribuzione a sorte.
            if forma != canonico and forma in canonici:
                continue
            voci.append((forma, impronta))
    for forma, impronta in sorted(voci, key=lambda v: (-len(v[0]), v[0])):
        s = re.sub(r"(?<![0-9])" + re.escape(forma) + r"(?![0-9])", impronta, s)
    return s


def build_report(info, *, chat_ids=()) -> str:
    """Report multilinea da una sequenza ordinata di `(etichetta, valore)` (o un
    dict). Un valore vuoto/None è mostrato come ``—``.

    Il testo finale passa per tre livelli, in quest'ordine: `redact_secrets` (token),
    `redact_chat_ids` (identità della chat) e `mask_user_paths` (username del PC). I
    segreti per primi perché la loro forma canonica (``<id>:<20+ char>``) non deve essere
    spezzata da una sostituzione precedente; i path per ultimi perché non interagiscono
    con le altre due.

    `chat_ids` sono i chat_id **noti da config** (vedi `collect_chat_ids`): la redazione è
    esatta, non indovina quali numeri siano un id."""
    items = info.items() if isinstance(info, dict) else list(info or [])
    lines = [_TITLE, f"versione: {__version__}", "-" * len(_TITLE)]
    for label, value in items:
        # Normalizza PRIMA di decidere: un valore di soli spazi (es. "   ", "\t") va
        # mostrato come "—", non come stringa vuota. Strippare e poi fare il fallback
        # copre None/""/whitespace-only con un unico controllo (#184 LOW).
        text = str(value).strip() if value is not None else ""
        text = text or "—"
        lines.append(f"{label}: {text}")
    report = event_log.redact_secrets("\n".join(lines))
    report = redact_chat_ids(report, chat_ids)
    return mask_user_paths(report)
