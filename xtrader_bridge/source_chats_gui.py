"""PR-13b/13c: vista customtkinter (sottile) dell'editor delle sorgenti multi-chat.

Tutta la logica sta nel controller `source_editor.SourceEditor` (testato in CI) e in
`source_manager` (validazione); qui ci sono SOLO i widget. La finestra si apre da un
pulsante nella GUI principale (`app.App`). Permette di aggiungere/rimuovere sorgenti
`source_chats` (nome, chat_id, attiva, modalità PRE/LIVE, provider) e di assegnare a
ciascuna un **Parser Personalizzato** dedicato (override `parser_by_chat`, PR-13c),
salvando in `config.json` senza editare il file a mano.

NB: questo modulo non è testato in CI (richiede un display). La logica che usa è
coperta da `tests/unit/test_source_editor.py`. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import config_store
from .source_editor import SourceEditor

# Etichetta base della voce "nessun override" (= "" = parser hardcoded/attivo).
_NO_PARSER_BASE = "(nessuno)"


def _none_sentinel(names) -> str:
    """Sentinella "nessuno" GARANTITA diversa da ogni nome di parser reale: se per
    assurdo un parser si chiama "(nessuno)", aggiunge spazi finché è unica. Evita la
    collisione che renderebbe ambiguo "nessun override" vs il parser omonimo (Codex)."""
    existing = set(names or [])
    label = _NO_PARSER_BASE
    while label in existing:
        label += " "
    return label


class SourceChatsWindow(ctk.CTkToplevel):
    """Finestra editor delle sorgenti multi-chat.

    `on_saved(new_cfg)`: callback opzionale chiamata dopo un salvataggio riuscito,
    così la GUI principale può aggiornare la propria config in memoria."""

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self.title("Chat sorgenti (multi-chat)")
        self.geometry("1080x560")
        self._on_saved = on_saved
        self._editor = SourceEditor(config_store.load_config(config_store.CONFIG_FILE))
        self._modes = self._editor.mode_options()
        # Nomi reali dei parser + sentinella "nessuno" unica (non collide mai con un
        # nome reale). Opzioni menu: sentinella davanti, poi i nomi reali.
        self._parser_names = self._editor.parser_options()
        self._no_parser = _none_sentinel(self._parser_names)
        self._parser_options = [self._no_parser] + self._parser_names
        self._rows = []   # widget refs per sorgente
        self._build_ui()
        for src in self._editor.sources:
            self._add_row(src)

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="📡  Chat sorgenti (multi-chat)",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text="Ogni sorgente è una chat/canale da cui accettare segnali. "
                       "chat_id obbligatorio e univoco; una sorgente disattivata viene ignorata.",
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=860,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        # Intestazione colonne
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12)
        for text, w in (("Attiva", 60), ("Nome", 180), ("Chat ID", 160),
                        ("Modalità", 100), ("Provider", 150), ("Parser", 160), ("", 40)):
            ctk.CTkLabel(head, text=text, width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)

        self._rows_frame = ctk.CTkScrollableFrame(self, height=320)
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(btns, text="➕  Aggiungi sorgente", width=180,
                      command=lambda: self._add_row()).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="💾  Salva", width=140, fg_color="#2e7d32",
                      hover_color="#1b5e20", command=self._save).pack(side="right", padx=4)

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                    text_color="gray", wraplength=860, anchor="w", justify="left")
        self._status.pack(fill="x", padx=12, pady=(0, 10))

    def _add_row(self, source: dict = None):
        source = source or {}
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        enabled = ctk.BooleanVar(value=bool(source.get("enabled", True)))
        ctk.CTkCheckBox(row, text="", width=60, variable=enabled).pack(side="left", padx=3)
        name = ctk.CTkEntry(row, width=180)
        name.insert(0, str(source.get("name", "")))
        name.pack(side="left", padx=3)
        chat_id = ctk.CTkEntry(row, width=160)
        chat_id.insert(0, str(source.get("chat_id", "")))
        chat_id.pack(side="left", padx=3)
        mode = ctk.StringVar(value=source.get("mode", self._modes[0] if self._modes else "PRE"))
        ctk.CTkOptionMenu(row, width=100, values=self._modes, variable=mode).pack(side="left", padx=3)
        provider = ctk.CTkEntry(row, width=150)
        provider.insert(0, str(source.get("provider", "")))
        provider.pack(side="left", padx=3)
        # Parser override per questa chat: "" → voce "nessuno"; un nome reale resta tale.
        parser = ctk.StringVar(value=str(source.get("parser", "")) or self._no_parser)
        ctk.CTkOptionMenu(row, width=160, values=self._parser_options,
                          variable=parser).pack(side="left", padx=3)
        refs = {"frame": row, "enabled": enabled, "name": name,
                "chat_id": chat_id, "mode": mode, "provider": provider, "parser": parser}
        ctk.CTkButton(row, text="✕", width=40, fg_color="#c62828", hover_color="#7f0000",
                      command=lambda r=refs: self._remove_row(r)).pack(side="left", padx=3)
        self._rows.append(refs)

    def _remove_row(self, refs):
        refs["frame"].destroy()
        self._rows.remove(refs)

    # ── salvataggio ────────────────────────────────────────────────────────
    def _save(self):
        # Ricostruisce l'editor dallo stato corrente dei widget (niente sync per-campo).
        editor = SourceEditor()
        for r in self._rows:
            # Solo la sentinella unica significa "nessun override" → ""; qualsiasi
            # altra voce è un nome di parser reale (anche un parser chiamato "(nessuno)",
            # perché la sentinella in quel caso è diversa: "(nessuno) ").
            parser = r["parser"].get()
            editor.add_source(name=r["name"].get(), chat_id=r["chat_id"].get(),
                              enabled=r["enabled"].get(), mode=r["mode"].get(),
                              provider=r["provider"].get(),
                              parser="" if parser == self._no_parser else parser)
        cfg = config_store.load_config(config_store.CONFIG_FILE)
        new_cfg, errors, warnings = editor.apply(cfg)
        if errors:
            self._status.configure(
                text="❌ " + "  ·  ".join(errors) + "\nNiente salvato: correggi gli errori.",
                text_color="#ef5350")
            return
        config_store.save_config(new_cfg, config_store.CONFIG_FILE)
        if self._on_saved:
            self._on_saved(new_cfg)
        msg = f"✅ Salvate {len(self._rows)} sorgenti in config.json."
        if warnings:
            msg += "\n⚠️ " + "  ·  ".join(warnings)
        self._status.configure(text=msg, text_color="#66bb6a")
