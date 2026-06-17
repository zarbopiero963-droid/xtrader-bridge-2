"""Modello dati del Parser Personalizzato (CP-01).

Il Parser Personalizzato permette all'utente di definire — da GUI, in un passo
successivo — *come* estrarre i campi del contratto CSV XTrader da un messaggio
Telegram, senza dipendere dal parser hardcoded (PR-09). Questo modulo contiene
**solo** il modello dati e la sua persistenza/validazione strutturale:

- `FieldRule`        — una regola per UNA colonna CSV (target).
- `CustomParserDef`  — un parser con nome + elenco di regole.
- (de)serializzazione JSON, validazione strutturale, skeleton di default,
  salvataggio/caricamento in `<cartella utente persistente>/parsers/<nome>.json`
  (riusa `config_store.config_dir()`, non la cartella temporanea dell'EXE).

NON è incluso (scope dei CP successivi):
- il motore di estrazione a runtime (applicare le regole a un messaggio);
- la risoluzione delle value-map / dizionario;
- le trasformazioni configurabili (es. somma-gol → Over (somma).5, CP-05);
- la GUI.

Semantica delle regole (interpretata dal motore runtime, NON qui):
- `start_after` / `end_before`: testo libero (anche emoji/simboli) che delimita
  il valore dentro il messaggio ("Inizia dopo" / "Finisce prima di").
- `fixed_value`: valore costante (es. `Provider=TG_CUSTOM`, `Handicap=0`); se
  presente, la colonna NON viene estratta dal messaggio.
- `value_map`: nome di una value-map (il dizionario diventa selezionabile) per
  tradurre il valore estratto nel valore esatto atteso da XTrader.
- `required`: se True e il valore risulta vuoto → parser "Non pronto" (blocca,
  nessuna riga CSV). Se False e vuoto → colonna CSV vuota (NON blocca).
"""

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass, field

from . import config_store
from .csv_writer import CSV_HEADER

# Versione dello schema del file parser: serve a gestire migrazioni future
# senza rompere i file salvati dagli utenti.
SCHEMA_VERSION = 1

# Le colonne ammesse come `target` di una regola sono esattamente quelle del
# contratto CSV XTrader (fonte unica: csv_writer.CSV_HEADER), così il modello
# non può andare in drift rispetto al contratto.
VALID_TARGETS = tuple(CSV_HEADER)

# Token booleani riconosciuti nei file JSON scritti/modificati a mano.
_TRUE_TOKENS = {"true", "1", "yes", "si", "sì", "y", "on"}
_FALSE_TOKENS = {"false", "0", "no", "n", "off", ""}


def _as_bool(v) -> bool:
    """Normalizza un valore JSON in bool senza la trappola di `bool(v)` (che
    tratterebbe la stringa "false"/"0" come True). Accetta bool, numeri e le
    rappresentazioni testuali comuni; su un valore ambiguo solleva ValueError
    invece di indovinare (un parser è safety-critical)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE_TOKENS:
            return True
        if s in _FALSE_TOKENS:
            return False
    raise ValueError(f"valore booleano non riconosciuto per 'required': {v!r}")


@dataclass
class FieldRule:
    """Regola di estrazione per UNA colonna del CSV XTrader."""

    target: str                 # colonna CSV di destinazione (∈ CSV_HEADER)
    start_after: str = ""       # "Inizia dopo": delimitatore sinistro (testo/emoji)
    end_before: str = ""        # "Finisce prima di": delimitatore destro (testo/emoji)
    fixed_value: str = ""       # valore costante (alternativo all'estrazione)
    value_map: str = ""         # nome value-map per tradurre il valore (opz.)
    required: bool = False      # obbligatorio: se vuoto → parser "Non pronto"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FieldRule":
        """Crea una regola da dict tollerando chiavi mancanti (default) ed extra
        (ignorate: forward-compatibilità con schema più recenti)."""
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: data[k] for k in known if k in data}
        if "target" not in kwargs:
            raise ValueError("FieldRule senza 'target'")
        rule = cls(target=str(kwargs.pop("target")))
        for k, v in kwargs.items():
            if k == "required":
                setattr(rule, k, _as_bool(v))
            else:
                setattr(rule, k, "" if v is None else str(v))
        return rule

    def is_fixed(self) -> bool:
        return self.fixed_value != ""

    def has_extraction(self) -> bool:
        return self.start_after != "" or self.end_before != ""


@dataclass
class CustomParserDef:
    """Definizione di un Parser Personalizzato: nome + elenco di regole."""

    name: str
    description: str = ""
    version: int = SCHEMA_VERSION
    rules: "list[FieldRule]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomParserDef":
        rules = [FieldRule.from_dict(r) for r in data.get("rules", [])]
        version = data.get("version", SCHEMA_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError):
            version = SCHEMA_VERSION
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            version=version,
            rules=rules,
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "CustomParserDef":
        return cls.from_dict(json.loads(text))

    def required_targets(self) -> list:
        """Colonne marcate obbligatorie: se a runtime restano vuote il parser
        è "Non pronto" e non si scrive il CSV."""
        return [r.target for r in self.rules if r.required]


def validate_parser_def(defn: CustomParserDef) -> list:
    """Validazione *strutturale* del modello. Ritorna la lista degli errori
    (vuota = valido). NON applica le regole a un messaggio (è il runtime, CP
    successivi)."""
    errors = []

    if not defn.name or not str(defn.name).strip():
        errors.append("Il parser deve avere un nome non vuoto.")

    if not isinstance(defn.version, int) or defn.version < 1:
        errors.append(f"Versione schema non valida: {defn.version!r} (atteso intero >= 1).")

    if not defn.rules:
        errors.append("Il parser deve avere almeno una regola.")

    seen_targets = set()
    for i, rule in enumerate(defn.rules):
        where = f"regola #{i + 1} (target={rule.target!r})"
        if rule.target not in VALID_TARGETS:
            errors.append(
                f"{where}: colonna non valida; ammesse solo {', '.join(VALID_TARGETS)}."
            )
        elif rule.target in seen_targets:
            # Due regole sulla stessa colonna sarebbero ambigue (quale vince?).
            errors.append(f"{where}: colonna duplicata, ogni colonna una sola regola.")
        else:
            seen_targets.add(rule.target)

        # Costante ed estrazione insieme sono contraddittorie.
        if rule.is_fixed() and rule.has_extraction():
            errors.append(
                f"{where}: ha sia 'fixed_value' sia 'start_after'/'end_before' "
                "(scegline uno: valore costante OPPURE estrazione)."
            )

    return errors


def is_valid(defn: CustomParserDef) -> bool:
    return not validate_parser_def(defn)


def skeleton(name: str = "Nuovo parser") -> CustomParserDef:
    """Scheletro di partenza valido: Provider costante + le colonne-nome usate
    dal riconoscimento NAME_ONLY (EventName/MarketName/SelectionName/BetType) e
    il Price obbligatorio. L'utente poi imposta start_after/end_before/value_map.
    """
    return CustomParserDef(
        name=name,
        description="Scheletro di partenza: personalizza delimitatori e value-map.",
        version=SCHEMA_VERSION,
        rules=[
            FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            FieldRule(target="EventName", required=True),
            FieldRule(target="MarketName", required=True),
            FieldRule(target="SelectionName", required=True),
            FieldRule(target="Price", required=True),
            FieldRule(target="BetType", required=True, value_map="bettype"),
            FieldRule(target="Handicap", fixed_value="0"),
        ],
    )


# ── Persistenza: <cartella utente persistente>/parsers/<nome>.json ─────────

def default_parsers_dir() -> str:
    """Cartella persistente dei parser utente: `<config_dir>/parsers/`.

    Riusa `config_store.config_dir()` (`%APPDATA%\\XTraderBridge` su Windows,
    `~/.config/XTraderBridge` altrove): è una posizione **scrivibile e
    persistente**, che sopravvive a riavvii/aggiornamenti dell'EXE. NON usiamo
    `sys._MEIPASS` (la cartella di estrazione PyInstaller è temporanea e di sola
    lettura): lì stanno solo i dati bundled read-only come il dizionario."""
    return os.path.join(config_store.config_dir(), "parsers")


def _safe_filename(name: str) -> str:
    """Nome file sicuro dal nome del parser: solo alfanumerici, '-', '_' e spazi
    (poi spazi → '_'). Evita path traversal e caratteri non validi su Windows."""
    cleaned = "".join(c for c in str(name).strip() if c.isalnum() or c in " -_")
    cleaned = "_".join(cleaned.split())
    return cleaned or "parser"


def parser_path(name: str, dir_path: str = None) -> str:
    base = dir_path if dir_path is not None else default_parsers_dir()
    return os.path.join(base, _safe_filename(name) + ".json")


def save_parser(defn: CustomParserDef, dir_path: str = None) -> str:
    """Salva il parser in `<dir>/<nome>.json`. Rifiuta i parser non validi per
    non persistere una definizione che bloccherebbe/ corromperebbe il CSV."""
    errors = validate_parser_def(defn)
    if errors:
        raise ValueError("Parser non valido, non salvato:\n- " + "\n- ".join(errors))
    base = dir_path if dir_path is not None else default_parsers_dir()
    os.makedirs(base, exist_ok=True)
    path = parser_path(defn.name, base)
    # Due nomi diversi che si sanitizzano allo stesso file (es. "A/B" e "AB")
    # NON devono sovrascriversi in silenzio: si perderebbero le regole del primo
    # parser. Sovrascrivere è consentito solo se è lo *stesso* parser (update).
    if os.path.exists(path):
        try:
            existing_name = load_parser(path).name
        except (OSError, ValueError, json.JSONDecodeError):
            existing_name = None
        if existing_name is not None and existing_name != defn.name:
            raise ValueError(
                f"Il nome {defn.name!r} collide con il parser {existing_name!r} "
                f"(stesso file {os.path.basename(path)}): scegli un nome diverso."
            )
    # Scrittura atomica: file temporaneo nella stessa cartella + fsync + rename,
    # così un crash a metà scrittura non lascia un JSON parziale/corrotto (il
    # file esistente resta intatto finché il rename non riesce).
    payload = defn.to_json()
    fd, tmp = tempfile.mkstemp(prefix=".parser_", suffix=".json", dir=base)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def load_parser(path: str) -> CustomParserDef:
    """Carica un parser da file JSON."""
    with open(path, encoding="utf-8") as f:
        return CustomParserDef.from_json(f.read())


def list_parser_files(dir_path: str = None) -> list:
    """Elenca i path dei file parser (`*.json`) presenti nella cartella.

    Esclude i file che iniziano con `.` (es. il temporaneo `.parser_*.json`
    della scrittura atomica, eventualmente rimasto dopo un crash prima di
    `os.replace`): non sono parser reali e non devono apparire come "fantasmi".
    `_safe_filename()` non produce mai nomi che iniziano con `.`."""
    base = dir_path if dir_path is not None else default_parsers_dir()
    if not os.path.isdir(base):
        return []
    return sorted(
        os.path.join(base, f)
        for f in os.listdir(base)
        if f.endswith(".json") and not f.startswith(".")
    )
