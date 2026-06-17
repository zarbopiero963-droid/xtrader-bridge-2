"""CP-08: import/export dei Parser Personalizzati + parser d'esempio.

- `export_parser(defn, dest)`: salva un parser (validato) in un percorso scelto
  dall'utente, per condividerlo.
- `import_parser(src, dir)`: legge un file parser da un percorso qualsiasi, lo
  valida e lo salva nella cartella dei parser (riusando `save_parser`, con
  controllo collisione e scrittura atomica di CP-01).
- `example_parser()`: un parser realistico e VALIDO, punto di partenza
  documentato; con `fixture_message()` dimostra l'intera catena
  estrazione→value-map→validazione su un messaggio tipico.

Import/export non scrivono il CSV e non toccano il runtime: solo file dei parser.
Un file corrotto o invalido → `ValueError` (niente salvataggi parziali).
"""

import json
import os
import tempfile

from . import custom_parser
from .custom_parser import CustomParserDef, FieldRule


def export_parser(defn: CustomParserDef, dest_path: str) -> str:
    """Scrive il parser (validato) come JSON in `dest_path`. Solleva ValueError
    se la definizione non è valida (non si esporta un parser rotto).

    Scrittura atomica (tempfile + fsync + os.replace, come `save_parser`): un
    export interrotto non lascia un file parziale al posto di uno esistente."""
    errors = custom_parser.validate_parser_def(defn)
    if errors:
        raise ValueError("Parser non valido, non esportato:\n- " + "\n- ".join(errors))
    payload = defn.to_json()
    dest_dir = os.path.dirname(os.path.abspath(dest_path))
    fd, tmp = tempfile.mkstemp(prefix=".export_", suffix=".json", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest_path


def import_parser(src_path: str, dir_path: str = None) -> CustomParserDef:
    """Importa un parser da `src_path`: legge, valida e lo salva nella cartella
    dei parser (con collisione/atomicità gestite da `save_parser`). Ritorna la
    definizione importata. Solleva ValueError se il file è corrotto o invalido."""
    defn = custom_parser.load_parser(src_path)   # OSError/ValueError su file rotto
    errors = custom_parser.validate_parser_def(defn)
    if errors:
        raise ValueError("Parser non valido, non importato:\n- " + "\n- ".join(errors))
    custom_parser.save_parser(defn, dir_path)
    return defn


def example_parser() -> CustomParserDef:
    """Parser d'esempio realistico (valido) per un messaggio tipo:

        Match: Inter v Milan
        Esito: GG
        Quota: 1,85
        Lato: BACK

    Usa value-map `selectionname`/`bettype`; pronto da personalizzare."""
    return CustomParserDef(
        name="Esempio P.Bet.",
        description="Esempio: Match/Esito/Quota/Lato con value-map dizionario.",
        rules=[
            FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            FieldRule(target="SelectionName", start_after="Esito:", end_before="\n",
                      value_map="selectionname", required=True),
            FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ],
    )


def fixture_message() -> str:
    """Messaggio d'esempio che `example_parser()` rende piazzabile."""
    return "Match: Inter v Milan\nEsito: GG\nQuota: 1,85\nLato: BACK"
