"""PR-13b/13c: controller dell'editor delle sorgenti multi-chat (logica pura, testabile).

Gestisce dalla GUI la lista `source_chats` (PR-13b) e l'override **parser per chat**
`parser_by_chat` (PR-13c), oggi modificabili solo a mano in `config.json`. Per ogni
sorgente si può scegliere un Parser Personalizzato dedicato (o "nessuno"). Niente
widget: la vista (`source_chats_gui`) crea le righe e chiama questi metodi. Riusa
`source_manager` (normalizzazione/validazione) e `parser_manager` (nomi parser
disponibili + mappa `parser_by_chat`).
"""

import copy

from . import parser_manager, source_manager


class SourceEditor:
    """Stato e operazioni dell'editor delle sorgenti. Solo dati e logica.

    Ogni riga porta i 5 campi di `source_chats` (name/chat_id/enabled/mode/provider)
    più `parser` (override per-chat, "" = nessuno) gestito a parte in `parser_by_chat`.
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or {}
        by_chat = parser_manager.parser_by_chat(cfg)   # {chat_id: nome_parser}
        # Sorgenti normalizzate (copie) + prefill del parser per chat dalla mappa.
        self.sources = []
        for s in source_manager.source_chats(cfg):
            s["parser"] = str(by_chat.get(s["chat_id"], "") or "").strip()
            self.sources.append(s)

    # ── opzioni per i menu della GUI ───────────────────────────────────────
    def mode_options(self) -> list:
        """Modalità ammesse per una sorgente (PRE/LIVE)."""
        return list(source_manager.MODES)

    def parser_options(self, parsers_dir: str = None) -> list:
        """Nomi dei Parser Personalizzati disponibili (per il menu override per-chat).
        La vista antepone una voce "nessuno" (= "" = parser hardcoded/attivo globale)."""
        return parser_manager.available_parser_names(parsers_dir)

    # ── gestione righe ─────────────────────────────────────────────────────
    @staticmethod
    def _row(name="", chat_id="", enabled=True, mode=None, provider="", parser="") -> dict:
        """Riga in forma canonica: i 5 campi di source_chats + `parser` (override)."""
        return {
            "name": str(name or "").strip(),
            "chat_id": str(chat_id or "").strip(),
            "enabled": bool(enabled),
            "mode": source_manager.normalize_mode(mode),
            "provider": str(provider or "").strip(),
            "parser": str(parser or "").strip(),
        }

    @staticmethod
    def _source_only(row: dict) -> dict:
        """Solo i 5 campi di `source_chats` (esclude `parser`, che va in parser_by_chat)."""
        return {k: row[k] for k in ("name", "chat_id", "enabled", "mode", "provider")}

    def add_source(self, name="", chat_id="", enabled=True, mode=None, provider="", parser="") -> dict:
        row = self._row(name, chat_id, enabled, mode, provider, parser)
        self.sources.append(row)
        return row

    def update_source(self, index: int, **kwargs) -> None:
        cur = self.sources[index]
        merged = {k: kwargs.get(k, cur[k]) for k in
                  ("name", "chat_id", "enabled", "mode", "provider", "parser")}
        self.sources[index] = self._row(**merged)

    def remove_source(self, index: int) -> None:
        del self.sources[index]

    # ── validazione + applicazione alla config ─────────────────────────────
    def validate(self) -> tuple:
        """`(errori, avvisi)` sulle sole sorgenti (i 5 campi). Errori bloccanti
        (chat_id mancante/duplicato, modalità invalida) da `source_manager`; avvisi
        (nomi duplicati) non bloccanti."""
        sources = [self._source_only(s) for s in self.sources]
        return source_manager.validate_sources(sources), source_manager.duplicate_name_warnings(sources)

    def apply(self, cfg: dict) -> tuple:
        """Fonde sorgenti **e** override parser-per-chat su una COPIA di `cfg` →
        `(nuova_cfg, errori, avvisi)`.

        - `source_chats`: i 5 campi delle righe.
        - `parser_by_chat`: parte dalla mappa esistente (così le voci di chat **non**
          mostrate qui — es. il `chat_id` globale — sono **preservate**), poi per ogni
          riga imposta/azzera l'override della sua chat dal campo `parser`.

        Se ci sono errori bloccanti, `nuova_cfg` è la config di partenza **invariata**."""
        base = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}
        errors, warnings = self.validate()
        if errors:
            return base, errors, warnings
        global_chat = str(base.get("chat_id", "") or "").strip()
        row_ids = {s["chat_id"] for s in self.sources}
        old_source_ids = {s["chat_id"] for s in source_manager.source_chats(base)}
        base["source_chats"] = [self._source_only(s) for s in self.sources]
        by_chat = parser_manager.parser_by_chat(base)
        # Sorgenti RIMOSSE/rinominate: togli l'override, così la chat non resta
        # autorizzata via parser_by_chat (`is_chat_allowed`) dopo la rimozione (Codex P1).
        # MA conserva l'override della chat `chat_id` GLOBALE: resta autorizzata di suo,
        # e il suo parser per-chat è ancora valido (Codex P2-a).
        for chat in (old_source_ids - row_ids):
            if chat and chat != global_chat:
                by_chat.pop(chat, None)
        # Righe correnti: azzera il vecchio override e ri-impostalo SOLO per le righe
        # ATTIVE. Una sorgente disattivata non deve lasciare una chiave parser_by_chat:
        # il runtime la deny-lista comunque, ma il check chat-notifiche di `_start`
        # conta ogni chiave come sorgente e bloccherebbe l'avvio (Codex P2-b).
        for s in self.sources:
            by_chat.pop(s["chat_id"], None)
            if s["parser"] and s["enabled"]:
                by_chat[s["chat_id"]] = s["parser"]
        base["parser_by_chat"] = by_chat
        return base, [], warnings
