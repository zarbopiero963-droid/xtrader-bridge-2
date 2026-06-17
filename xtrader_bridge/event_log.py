"""PR-14: log persistente + contatori di stato (logica pura, testabile).

Cuore di #11 (l'utente capisce sempre cosa succede), fuori dalla GUI:

- log **persistente** in `<config_dir>/logs/bridge-YYYY-MM-DD.log` (append): lo
  storico sopravvive a chiusura/riavvio dell'app;
- **livelli** INFO / WARNING / ERROR / SIGNAL e filtro per livello;
- **contatori** di stato (messaggi/segnali/errori + ultimi valori) per la dashboard.

Nessuna dipendenza da GUI/Telegram/CSV. La scrittura è best-effort: un problema
di filesystem non deve mai far crashare il bridge (si perde solo lo storico su
disco, non il funzionamento). NB: questo modulo scrive ciò che riceve — la
redazione di eventuali segreti resta responsabilità del chiamante (cfr.
`settings_validation`, che non mette mai il valore grezzo nei messaggi).
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime

from . import config_store

LEVELS = ("INFO", "WARNING", "ERROR", "SIGNAL")
DEFAULT_LEVEL = "INFO"


def normalize_level(level) -> str:
    """Normalizza il livello a uno di LEVELS; ignoto/mancante → DEFAULT_LEVEL."""
    lvl = str(level or "").strip().upper()
    return lvl if lvl in LEVELS else DEFAULT_LEVEL


# Pattern di un bot token Telegram: <id numerico>:<~35 caratteri>. Va mascherato
# ovunque possa finire in un log (es. un'eccezione che incorpora il token), per
# rispettare l'invariante "mai token in chiaro nei log".
_TELEGRAM_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")
_REDACTED = "[REDACTED_TOKEN]"


def redact_secrets(text: str) -> str:
    """Maschera valori che assomigliano a un bot token Telegram. Difesa unica per
    i log (GUI e file): un token incorporato per sbaglio (es. nel testo di
    un'eccezione) non viene mai scritto in chiaro."""
    return _TELEGRAM_TOKEN_RE.sub(_REDACTED, str(text or ""))


# Marker emoji con cui la GUI prefissa i messaggi → livello di log. Serve a
# derivare automaticamente il livello quando il chiamante non lo passa, così lo
# storico persistente distingue errori/segnali e `filter_by_level` è utile (#11).
_MARKER_LEVEL = (
    ("❌", "ERROR"),
    ("⚠️", "WARNING"),
    ("📱", "SIGNAL"),
)


def classify(message: str) -> str:
    """Deriva il livello dal marker iniziale del messaggio (❌→ERROR, ⚠️→WARNING,
    📱→SIGNAL); altrimenti INFO. Permette di classificare lo storico senza dover
    annotare a mano ogni punto di log della GUI."""
    text = str(message or "").lstrip()
    for marker, level in _MARKER_LEVEL:
        if text.startswith(marker):
            return level
    return DEFAULT_LEVEL


def format_entry(message: str, level=DEFAULT_LEVEL, when: datetime = None) -> str:
    """Riga di log formattata: ``[HH:MM:SS] [LEVEL] messaggio``.

    Il messaggio è ridotto a **una sola riga fisica**: CR/LF vengono sostituiti da
    uno spazio. Senza questo, un messaggio multiriga (es. un EventName estratto su
    più righe da un parser custom) spezzerebbe la entry e `read_entries` vedrebbe
    le continuazioni come entry separate, o un messaggio potrebbe forgiare un
    header di livello falso."""
    when = when or datetime.now()
    safe = str(message).replace("\r", " ").replace("\n", " ")
    return f"[{when:%H:%M:%S}] [{normalize_level(level)}] {safe}"


def log_dir(base: str = None) -> str:
    """Cartella dei log: `<config_dir>/logs` (o `<base>/logs` nei test)."""
    base = base if base is not None else config_store.config_dir()
    return os.path.join(base, "logs")


def log_path(base: str = None, when: datetime = None) -> str:
    """Percorso del file di log del giorno (`bridge-YYYY-MM-DD.log`)."""
    when = when or datetime.now()
    return os.path.join(log_dir(base), f"bridge-{when:%Y-%m-%d}.log")


def append_entry(message: str, level=DEFAULT_LEVEL, *, base: str = None,
                 when: datetime = None) -> str:
    """Appende una riga formattata al log del giorno (best-effort, non solleva).
    Ritorna la riga (anche se la scrittura su disco fallisce)."""
    when = when or datetime.now()
    line = format_entry(message, level, when)
    try:
        os.makedirs(log_dir(base), exist_ok=True)
        with open(log_path(base, when), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    return line


def read_entries(base: str = None, when: datetime = None) -> list:
    """Righe storiche del log del giorno (lista, vuota se il file non esiste).
    Permette di rileggere lo storico dopo un riavvio dell'app."""
    try:
        with open(log_path(base, when), "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except OSError:
        return []


# Header di una entry: ``[HH:MM:SS] [LEVEL] ...``. Si estrae il livello SOLO da
# questo campo strutturale, non cercandolo in tutta la riga: un ``[ERROR]`` nel
# testo del messaggio non deve far classificare la entry come ERROR.
_ENTRY_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \[([A-Z]+)\] ")


def entry_level(line: str):
    """Livello di una riga formattata (dal campo header), o None se non combacia."""
    m = _ENTRY_RE.match(str(line or ""))
    return m.group(1) if m else None


def filter_by_level(lines, level) -> list:
    """Filtra righe formattate (`format_entry`) per livello, leggendo SOLO il
    campo livello dell'header (non il testo del messaggio)."""
    lvl = normalize_level(level)
    return [line for line in lines if entry_level(line) == lvl]


@dataclass
class Counters:
    """Contatori di stato del bridge per la dashboard (#11): quante cose sono
    successe e qual è l'ultima di ogni tipo. Pura, senza I/O."""

    messages: int = 0
    signals: int = 0
    errors: int = 0
    last_message: str = ""
    last_signal: str = ""
    last_error: str = ""

    def record_message(self, text: str = "") -> None:
        self.messages += 1
        if text:
            self.last_message = text

    def record_signal(self, text: str = "") -> None:
        self.signals += 1
        if text:
            self.last_signal = text

    def record_error(self, text: str = "") -> None:
        self.errors += 1
        if text:
            self.last_error = text
