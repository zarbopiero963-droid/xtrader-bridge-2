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
  occorrenza di questo testo trovata dopo il punto di inizio; se non è presente
  → fino a fine messaggio; se `end_before == ""` → fino a fine RIGA (primo
  a-capo dopo l'inizio), per non "ingoiare" il resto del messaggio.
- il valore estratto viene rifilato degli spazi ai bordi.
- `required`: se il valore finale è vuoto il parser è "Non pronto" (nessuna riga
  CSV); se opzionale e vuoto → colonna vuota (non blocca).
"""

from dataclasses import dataclass, field

from .custom_parser import VALID_TARGETS, CustomParserDef, FieldRule


def extract_value(text: str, rule: FieldRule) -> str:
    """Estrae il valore di UNA regola dal testo (vedi semantica nel docstring
    del modulo). Non solleva eccezioni: un delimitatore mancante → valore vuoto."""
    if rule.fixed_value != "":
        return rule.fixed_value
    if not text:
        return ""

    start = 0
    if rule.start_after != "":
        idx = text.find(rule.start_after)
        if idx == -1:
            return ""
        start = idx + len(rule.start_after)

    if rule.end_before != "":
        end = text.find(rule.end_before, start)
        if end == -1:
            end = len(text)
    else:
        nl = text.find("\n", start)
        end = nl if nl != -1 else len(text)

    return text[start:end].strip()


@dataclass
class ExtractionResult:
    """Esito dell'applicazione di un parser a un messaggio."""

    ready: bool                              # True se nessun obbligatorio è vuoto
    values: dict = field(default_factory=dict)        # target → valore estratto
    missing_required: list = field(default_factory=list)  # obbligatori vuoti

    def as_csv_row(self) -> dict:
        """Riga completa a 14 colonne: le colonne senza regola restano vuote.

        NB: i valori sono quelli grezzi estratti (nessuna value-map/trasformazione,
        quelle arrivano in CP-03/CP-05). Usare solo a parser `ready`."""
        row = {col: "" for col in VALID_TARGETS}
        for target, value in self.values.items():
            if target in row:
                row[target] = value
        return row


def apply_parser(defn: CustomParserDef, text: str) -> ExtractionResult:
    """Applica tutte le regole del parser al messaggio.

    Ritorna i valori estratti per ogni regola e lo stato di "piazzabilità":
    `ready=False` con l'elenco `missing_required` se un campo obbligatorio è
    risultato vuoto (→ niente CSV, è il gate "Non pronto")."""
    values = {}
    missing = []
    for rule in defn.rules:
        value = extract_value(text, rule)
        values[rule.target] = value
        if rule.required and value == "":
            missing.append(rule.target)
    return ExtractionResult(ready=not missing, values=values, missing_required=missing)
