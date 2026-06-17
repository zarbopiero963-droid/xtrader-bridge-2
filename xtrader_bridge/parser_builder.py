"""CP-06: controller del costruttore di Parser Personalizzati (senza GUI).

Tutta la logica del costruttore vive qui, separata dai widget customtkinter
(vista sottile in `custom_parser_gui.py`), così è interamente testabile in CI:
gestione regole (aggiungi/aggiorna/rimuovi/sposta), opzioni dei menu a tendina,
validazione, salvataggio/caricamento e **test-live** di un messaggio.

Riusa i moduli già testati: `custom_parser` (modello/validazione/persistenza),
`value_maps`/`transforms` (opzioni a tendina), `custom_pipeline` (test-live),
`recognition` (modalità).
"""

from . import custom_parser, recognition, transforms, value_maps
from .custom_parser import CustomParserDef, FieldRule
from .custom_pipeline import build_validated_row


class ParserBuilder:
    """Stato e operazioni del costruttore. Nessun widget: solo dati e logica."""

    def __init__(self, defn: CustomParserDef = None):
        if defn is None:
            self.name = ""
            self.description = ""
            self.rules = []
        else:
            self.name = defn.name
            self.description = defn.description
            self.rules = [FieldRule.from_dict(r.to_dict()) for r in defn.rules]  # copia

    # ── opzioni per i menu a tendina della GUI ─────────────────────────────
    def target_options(self) -> list:
        return list(custom_parser.VALID_TARGETS)

    def transform_options(self) -> list:
        # "" = nessuna trasformazione.
        return [""] + transforms.available_transforms()

    def value_map_options(self, include_dizionario: bool = True, rows=None) -> list:
        # "" = nessuna value-map.
        return [""] + value_maps.available_value_maps(include_dizionario=include_dizionario, rows=rows)

    def mode_options(self) -> list:
        return list(recognition.VALID_MODES)

    # ── gestione regole ────────────────────────────────────────────────────
    def add_rule(self, target: str = "EventName", **kwargs) -> FieldRule:
        rule = FieldRule(target=target, **kwargs)
        self.rules.append(rule)
        return rule

    def update_rule(self, index: int, **kwargs) -> None:
        rule = self.rules[index]
        for key, value in kwargs.items():
            if not hasattr(rule, key):
                raise AttributeError(f"FieldRule non ha il campo {key!r}")
            setattr(rule, key, value)

    def remove_rule(self, index: int) -> None:
        del self.rules[index]

    def move_rule(self, index: int, delta: int) -> int:
        """Sposta la regola di `delta` posizioni (clamp ai bordi). Ritorna il
        nuovo indice."""
        new_index = max(0, min(len(self.rules) - 1, index + delta))
        if new_index != index:
            self.rules.insert(new_index, self.rules.pop(index))
        return new_index

    # ── modello / validazione ──────────────────────────────────────────────
    def to_def(self) -> CustomParserDef:
        return CustomParserDef(name=self.name, description=self.description,
                               rules=list(self.rules))

    def errors(self) -> list:
        return custom_parser.validate_parser_def(self.to_def())

    def is_valid(self) -> bool:
        return not self.errors()

    # ── persistenza ─────────────────────────────────────────────────────────
    def save(self, dir_path: str = None) -> str:
        """Salva il parser corrente (valida prima; solleva ValueError se invalido)."""
        return custom_parser.save_parser(self.to_def(), dir_path)

    @classmethod
    def load(cls, path: str) -> "ParserBuilder":
        return cls(custom_parser.load_parser(path))

    @staticmethod
    def list_saved(dir_path: str = None) -> list:
        return custom_parser.list_parser_files(dir_path)

    # ── test-live ────────────────────────────────────────────────────────────
    def test_message(self, message: str, *, provider: str = "",
                     mode: str = recognition.DEFAULT_MODE, require_price: bool = True):
        """Applica il parser corrente a un messaggio e ritorna il `PipelineResult`
        (status + riga + piazzabilità), per l'anteprima del costruttore."""
        return build_validated_row(self.to_def(), message, provider=provider,
                                   mode=mode, require_price=require_price)
