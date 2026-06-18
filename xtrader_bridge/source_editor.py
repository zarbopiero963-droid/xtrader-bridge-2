"""PR-13b: controller dell'editor delle sorgenti multi-chat (logica pura, testabile).

Permette di gestire dalla GUI la lista `source_chats` (oggi modificabile solo a mano
in `config.json`): aggiungere/aggiornare/rimuovere sorgenti, con validazione. Niente
widget: la vista (`source_chats_gui`) crea le righe e chiama questi metodi. Riusa
`source_manager` (normalizzazione, modalità, validazione duplicati) come fonte unica.
"""

import copy

from . import source_manager


class SourceEditor:
    """Stato e operazioni dell'editor delle sorgenti. Solo dati e logica."""

    def __init__(self, cfg: dict = None):
        # Parte dalle sorgenti normalizzate in config (copie: mutarle non tocca cfg).
        self.sources = source_manager.source_chats(cfg or {})

    # ── opzioni per i menu della GUI ───────────────────────────────────────
    def mode_options(self) -> list:
        """Modalità ammesse per una sorgente (PRE/LIVE)."""
        return list(source_manager.MODES)

    # ── gestione righe ─────────────────────────────────────────────────────
    @staticmethod
    def _row(name="", chat_id="", enabled=True, mode=None, provider="") -> dict:
        """Riga sorgente in forma canonica (stessi campi/normalizzazioni di source_manager)."""
        return {
            "name": str(name or "").strip(),
            "chat_id": str(chat_id or "").strip(),
            "enabled": bool(enabled),
            "mode": source_manager.normalize_mode(mode),
            "provider": str(provider or "").strip(),
        }

    def add_source(self, name="", chat_id="", enabled=True, mode=None, provider="") -> dict:
        row = self._row(name, chat_id, enabled, mode, provider)
        self.sources.append(row)
        return row

    def update_source(self, index: int, **kwargs) -> None:
        """Aggiorna i campi dati di una sorgente (ri-normalizzando)."""
        cur = self.sources[index]
        merged = {
            "name": kwargs.get("name", cur["name"]),
            "chat_id": kwargs.get("chat_id", cur["chat_id"]),
            "enabled": kwargs.get("enabled", cur["enabled"]),
            "mode": kwargs.get("mode", cur["mode"]),
            "provider": kwargs.get("provider", cur["provider"]),
        }
        self.sources[index] = self._row(**merged)

    def remove_source(self, index: int) -> None:
        del self.sources[index]

    # ── validazione + applicazione alla config ─────────────────────────────
    def validate(self) -> tuple:
        """`(errori, avvisi)`. Errori **bloccanti** (chat_id mancante/duplicato,
        modalità non valida) da `source_manager.validate_sources`; avvisi non
        bloccanti (nomi duplicati) da `duplicate_name_warnings`."""
        errors = source_manager.validate_sources(self.sources)
        warnings = source_manager.duplicate_name_warnings(self.sources)
        return errors, warnings

    def apply(self, cfg: dict) -> tuple:
        """Fonde le sorgenti su una COPIA di `cfg` → `(nuova_cfg, errori, avvisi)`.

        Se ci sono errori bloccanti, `nuova_cfg` è la config di partenza **invariata**
        (nessun salvataggio parziale). Gli avvisi non bloccano l'applicazione."""
        base = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}
        errors, warnings = self.validate()
        if errors:
            return base, errors, warnings
        base["source_chats"] = [dict(s) for s in self.sources]
        return base, [], warnings
