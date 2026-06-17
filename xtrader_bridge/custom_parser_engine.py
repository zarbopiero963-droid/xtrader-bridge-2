"""CP-02: motore di estrazione del Parser Personalizzato.

Applica le regole di un `CustomParserDef` (CP-01) al testo di un messaggio
Telegram e produce i valori per le colonne del contratto CSV XTrader.

Scope di CP-02 (volutamente stretto):
- NON risolve le value-map (è CP-03);
- NON applica trasformazioni configurabili, es. somma-gol → Over (somma).5 (CP-05);
- NON scrive il CSV (CP-04);
- NON tocca la GUI (CP-06).

Semantica di una regola (`FieldRule`):
- `fixed_value`: se valorizzato, la colonna vale esattamente quello e
  l'estrazione dal messaggio viene ignorata.
- `start_after` ("Inizia dopo"): se valorizzato, l'estrazione parte subito DOPO
  la prima occorrenza di questo testo (match case-sensitive, utile per
  emoji/simboli); se il testo non è presente nel messaggio → valore vuoto; se
  `start_after == ""` → si parte dall'inizio del messaggio.
- `end_before` ("Finisce prima di"): l'estrazione termina PRIMA della prima
  occorrenza di questo testo trovata dopo il punto di inizio; se il delimitatore
  è configurato ma NON è presente → estrazione **fallita** (valore vuoto): un
  messaggio non conforme non deve passare il gate. Se `end_before == ""` →
  fino a fine RIGA (primo a-capo dopo l'inizio), per non "ingoiare" il resto.
- una regola **senza estrazione configurata** (né `fixed_value`, né `start_after`,
  né `end_before`) restituisce vuoto: non sappiamo dove prendere il valore, quindi
  resta "mancante" finché non viene configurata (es. le regole di `skeleton()`).
- il valore estratto viene rifilato degli spazi ai bordi.
- `required`: se il valore finale è vuoto il parser è "Non pronto" (nessuna riga
  CSV); se opzionale e vuoto → colonna vuota (non blocca).
"""

from dataclasses import dataclass, field

from .csv_writer import CSV_HEADER
from .custom_parser import CustomParserDef, FieldRule


def extract_value(text: str, rule: FieldRule) -> str:
    """Estrae il valore di UNA regola dal testo (vedi semantica nel docstring
    del modulo). Non solleva eccezioni: un delimitatore mancante → valore vuoto.

    I campi della regola sono normalizzati con `or ""`: anche se costruita a mano
    con `None` (la persistenza JSON forza già `str`), `.find()` non esplode."""
    fixed = rule.fixed_value or ""
    if fixed != "":
        return fixed

    start_after = rule.start_after or ""
    end_before = rule.end_before or ""

    # Regola senza estrazione configurata: nessun modo di localizzare il valore
    # → vuoto (resta "mancante" se obbligatoria, es. le regole di skeleton()).
    if start_after == "" and end_before == "":
        return ""
    if not text:
        return ""

    start = 0
    if start_after != "":
        idx = text.find(start_after)
        if idx == -1:
            return ""
        start = idx + len(start_after)

    if end_before != "":
        # Delimitatore di fine configurato ma assente → messaggio non conforme:
        # estrazione fallita (vuoto), così un obbligatorio resta "Non pronto".
        end = text.find(end_before, start)
        if end == -1:
            return ""
    else:
        # Nessun end_before: fino a fine riga (non "ingoia" il resto del messaggio).
        nl = text.find("\n", start)
        end = nl if nl != -1 else len(text)

    return text[start:end].strip()


@dataclass
class ExtractionResult:
    """Esito dell'applicazione di un parser a un messaggio."""

    ready: bool                              # True se nessun obbligatorio è vuoto
    values: "dict[str, str]" = field(default_factory=dict)        # target → valore
    missing_required: "list[str]" = field(default_factory=list)   # obbligatori vuoti

    def as_csv_row(self) -> "dict[str, str]":
        """Riga completa a 14 colonne: le colonne senza regola restano vuote.

        Le colonne sono quelle del contratto (`csv_writer.CSV_HEADER`, fonte
        unica) per evitare drift. NB: i valori sono quelli grezzi estratti
        (nessuna value-map/trasformazione, quelle arrivano in CP-03/CP-05).
        Usare solo a parser `ready`."""
        row = {col: "" for col in CSV_HEADER}
        for target, value in self.values.items():
            if target in row:
                row[target] = value
        return row


def apply_parser(defn: CustomParserDef, text: str) -> ExtractionResult:
    """Applica tutte le regole del parser al messaggio.

    Ritorna i valori estratti per ogni regola e lo stato di "piazzabilità":
    `ready=False` con l'elenco `missing_required` se un campo obbligatorio è
    risultato vuoto (→ niente CSV, è il gate "Non pronto").

    `validate_parser_def` (CP-01) vieta già i target duplicati; qui il motore è
    comunque robusto: per ogni target vince l'ultima regola e `missing_required`
    è calcolato sul valore FINALE (dedup, niente doppioni o falsi mancanti)."""
    values = {}
    required_targets = []
    for rule in defn.rules:
        values[rule.target] = extract_value(text, rule)
        if rule.required and rule.target not in required_targets:
            required_targets.append(rule.target)
    missing = [t for t in required_targets if values.get(t, "") == ""]
    return ExtractionResult(ready=not missing, values=values, missing_required=missing)
