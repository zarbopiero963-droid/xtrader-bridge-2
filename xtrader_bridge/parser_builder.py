"""CP-06: controller del costruttore di Parser Personalizzati (senza GUI).

Tutta la logica del costruttore vive qui, separata dai widget customtkinter
(vista sottile in `custom_parser_gui.py`), così è interamente testabile in CI:
gestione regole (aggiungi/aggiorna/rimuovi/sposta), opzioni dei menu a tendina,
validazione, salvataggio/caricamento e **test-live** di un messaggio.

Riusa i moduli già testati: `custom_parser` (modello/validazione/persistenza),
`value_maps`/`transforms` (opzioni a tendina), `custom_pipeline` (test-live),
`recognition` (modalità).
"""

import json
import os

from . import custom_parser, dizionario, recognition, transforms, value_maps
from .custom_parser import CustomParserDef, FieldRule
from .custom_pipeline import build_validated_row


class ParserBuilder:
    """Stato e operazioni del costruttore. Nessun widget: solo dati e logica."""

    def __init__(self, defn: CustomParserDef = None):
        if defn is None:
            self.name = ""
            self.description = ""
            self.mode = recognition.DEFAULT_MODE
            self.rules = []
            # Mappatura nomi squadra (name_mapping_store): vanno preservati nel
            # round-trip del builder, altrimenti load+save/duplica azzererebbe la
            # mappatura in silenzio (live scriverebbe l'EventName provider grezzo).
            self.name_mapping_profiles = []
            self.team_separator = ""
        else:
            self.name = defn.name
            self.description = defn.description
            # Preserva la modalità COM'È, incl. "" (legacy = eredita il globale): NON
            # normalizzare "" → NAME_ONLY, altrimenti aprire/salvare/duplicare un parser
            # legacy ne scriverebbe NAME_ONLY perdendo l'ereditarietà (Codex).
            self.mode = getattr(defn, "mode", recognition.DEFAULT_MODE)
            self.rules = [FieldRule.from_dict(r.to_dict()) for r in defn.rules]  # copia
            # Campi mappatura nomi: copiati (lista nuova) così il builder non perde i
            # profili/separatore di un parser caricato (Codex). `getattr` per tollerare
            # def costruite prima dei campi.
            self.name_mapping_profiles = list(getattr(defn, "name_mapping_profiles", []) or [])
            self.team_separator = getattr(defn, "team_separator", "") or ""

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

    # ── catalogo XTrader: Mercato → Selezione FISSI (B2) ───────────────────
    def market_options(self, rows=None) -> list:
        """MarketName selezionabili come valore **fisso** per la tendina Mercato del
        catalogo: esclude i mercati **dinamici** (MarketName con placeholder squadra,
        es. handicap `"{HOME_TEAM} +1"`), che non sono valori fissi sicuri."""
        return dizionario.market_names(rows=rows, fixed_only=True)

    def selection_options(self, market: str, rows=None) -> list:
        """SelectionName **non dinamici** del mercato dato, per la tendina Selezione.
        Esclude le selezioni con placeholder squadra (vanno risolte a runtime da
        Home/Away, quindi non usabili come valore fisso)."""
        return [s["SelectionName"]
                for s in dizionario.selections_for_market(market, rows)
                if not s["dynamic"] and s["SelectionName"]]

    def set_fixed_market(self, market: str, selection: str, rows=None) -> None:
        """Imposta Mercato+Selezione **fissi** dal catalogo XTrader (B2): crea/aggiorna
        le regole `MarketType`, `MarketName`, `SelectionName` coi valori canonici scelti
        (`fixed_value`), azzerando estrazione/transform/value-map così il valore resta
        ESATTAMENTE quello del catalogo. Non tocca le altre regole.

        CSV-safe: l'input è confrontato in modo case/spazio-insensitive col catalogo ma
        nel CSV si persistono **sempre i nomi CANONICI** del dizionario (non l'input
        grezzo), così un `"esito finale"` non diventa una riga non-canonica che romperebbe
        il match XTrader. `ValueError` se il mercato non è nel catalogo (fixed-only) o la
        selezione non è tra quelle **non dinamiche** del mercato."""
        market_key = str(market or "").strip().casefold()
        selection_key = str(selection or "").strip().casefold()
        # Risolve il nome CANONICO del mercato (solo fixed-only: niente dinamici).
        canonical_market = next(
            (m for m in self.market_options(rows=rows)
             if m.strip().casefold() == market_key), None)
        if not canonical_market:
            raise ValueError(f"Mercato non nel catalogo XTrader: {market!r}")
        canonical_selection = next(
            (s for s in self.selection_options(canonical_market, rows)
             if s.strip().casefold() == selection_key), None)
        if not canonical_selection:
            raise ValueError(
                f"Selezione non valida o dinamica per {market!r}: {selection!r}")
        market_type = dizionario.market_type_for_name(canonical_market, rows)
        for target, value in (("MarketType", market_type),
                              ("MarketName", canonical_market),
                              ("SelectionName", canonical_selection)):
            self._upsert_fixed_rule(target, value)

    def _upsert_fixed_rule(self, target: str, value: str) -> None:
        """Imposta una regola a valore FISSO per `target`: aggiorna quella esistente (o
        ne aggiunge una nuova), azzerando i campi di estrazione/traduzione così resta un
        valore costante. Evita target duplicati (vietati dalla validazione)."""
        for rule in self.rules:
            if rule.target == target:
                rule.fixed_value = value
                rule.start_after = rule.end_before = rule.transform = rule.value_map = ""
                return
        self.rules.append(FieldRule(target=target, fixed_value=value))

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
        return CustomParserDef(
            name=self.name, description=self.description, mode=self.mode,
            name_mapping_profiles=list(self.name_mapping_profiles),
            team_separator=self.team_separator, rules=list(self.rules))

    # ── Modalità di riconoscimento (per-parser) ────────────────────────────
    def set_mode(self, mode: str) -> None:
        """Imposta la Modalità del parser e **allinea** l'obbligatorietà dei SOLI campi di
        riconoscimento al suo set (auto-Obblig.): i campi del set diventano `required=True`,
        gli ALTRI campi di riconoscimento `required=False`. Così selezionando una modalità
        i required risultano sempre coerenti con essa (cambiando NAME↔ID non restano
        required "stantii", Codex). `BOTH` → nessun campo di riconoscimento forzato (basta
        un set). Price/BetType/Provider NON sono toccati (non dipendono dalla modalità).

        Va invocata SOLO su azione esplicita dell'utente (scelta modalità) o su parser
        NUOVO — MAI al semplice reload/apertura, altrimenti rilasserebbe i required salvati
        a mano di un parser esistente (per quello la GUI non la chiama in `_reload`)."""
        self.mode = recognition.normalize_mode(mode)
        required = set(recognition.required_targets(self.mode))
        for rule in self.rules:
            if rule.target in recognition.RECOGNITION_FIELDS:
                rule.required = rule.target in required

    def ensure_all_columns(self) -> None:
        """Garantisce una riga per OGNI colonna del contratto (14), nell'ordine di
        `VALID_TARGETS`: le colonne non ancora presenti sono aggiunte come regole
        vuote (nessun valore → colonna CSV vuota se non configurata). Serve alla GUI a
        righe fisse: l'utente compila/lascia vuota ciascuna colonna senza aggiungerle
        a mano. Mantiene le regole esistenti (valori/Obblig.), solo riordinate."""
        by_target = {r.target: r for r in self.rules}
        ordered = []
        for target in custom_parser.VALID_TARGETS:
            ordered.append(by_target.get(target) or FieldRule(target=target))
        # Eventuali target non-standard (non dovrebbero esistere) restano in coda.
        ordered.extend(r for r in self.rules if r.target not in custom_parser.VALID_TARGETS)
        self.rules = ordered

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

    # ── gestione dei parser salvati (per la GUI: lista/carica/duplica/elimina) ─
    @staticmethod
    def saved_parsers(dir_path: str = None) -> list:
        """Elenco dei parser salvati come `[{"name", "path"}]`, ordinato per nome
        (case-insensitive). `name` è il nome **dentro** il file; se un file è
        illeggibile/corrotto si usa il nome del file (stem) come fallback, senza
        far fallire l'intera lista (un parser rotto non deve nascondere gli altri)."""
        items = []
        for path in custom_parser.list_parser_files(dir_path):
            try:
                name = custom_parser.load_parser(path).name
            except (OSError, ValueError, json.JSONDecodeError):
                name = os.path.splitext(os.path.basename(path))[0]
            items.append({"name": name, "path": path})
        items.sort(key=lambda it: it["name"].lower())
        return items

    @staticmethod
    def delete_saved(name: str, dir_path: str = None) -> bool:
        """Elimina un parser salvato per nome. Ritorna `True` se rimosso."""
        return custom_parser.delete_parser(name, dir_path)

    @staticmethod
    def duplicate_saved(src_path: str, new_name: str, dir_path: str = None) -> str:
        """Duplica un parser salvato sotto `new_name` e salva la copia.

        Una duplica crea un parser **nuovo**: se esiste già un file per `new_name`
        viene rifiutata con `ValueError`, così non si sovrascrive in silenzio un
        parser esistente (`save_parser` con lo stesso nome sarebbe invece un
        *update*). Ritorna il path della copia; l'originale non è modificato."""
        new_name = str(new_name).strip()
        if os.path.exists(custom_parser.parser_path(new_name, dir_path)):
            raise ValueError(
                f"Esiste già un parser con nome {new_name!r}: scegli un altro nome.")
        builder = ParserBuilder.load(src_path)
        builder.name = new_name
        return builder.save(dir_path)

    # ── test-live ────────────────────────────────────────────────────────────
    def test_message(self, message: str, *, provider: str = "",
                     mode: str = None, require_price: bool = None):
        """Applica il parser corrente a un messaggio e ritorna il `PipelineResult`
        (status + riga + piazzabilità), per l'anteprima del costruttore. La modalità
        usata è quella DEL PARSER (`self.mode`) salvo override esplicito.

        `require_price` di default (None) deriva dalla riga Price del parser
        (`price_required()`): l'anteprima riflette così l'unico comando della quota,
        coerente col runtime."""
        defn = self.to_def()
        if require_price is None:
            require_price = defn.price_required()
        return build_validated_row(defn, message, provider=provider,
                                   mode=self.mode if mode is None else mode,
                                   require_price=require_price)
