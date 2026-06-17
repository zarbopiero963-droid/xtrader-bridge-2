"""GUI CustomTkinter + listener Telegram.

Unica parte del progetto che dipende dalla GUI. La logica pura (parser, CSV,
config) vive in moduli separati ed è testabile headless.
"""

import asyncio
import threading
from datetime import datetime

import customtkinter as ctk

from .config_store import (
    CONFIG_FILE,
    load_config,
    migrate_legacy_config,
    save_config,
)
from .csv_writer import build_csv_row, init_csv, write_csv
from .parser import parse_message
from . import recognition
from . import validator
from .signal_gate import SignalGate

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
    TELEGRAM_OK = True
except ImportError:
    TELEGRAM_OK = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("XTrader Signal Bridge")
        self.geometry("720x700")
        self.resizable(False, False)

        self._config = self._load_config()
        self._running = False
        self._bot_thread = None
        self._clear_timer = None
        self._tg_app = None
        self._loop = None
        self._gate = SignalGate()   # evita che un clear obsoleto cancelli un nuovo segnale

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── CONFIG ────────────────────────────────
    def _load_config(self) -> dict:
        # Migra il vecchio config.json (accanto all'EXE) la prima volta, poi carica
        # dalla cartella utente persistente (%APPDATA%\XTraderBridge).
        migrate_legacy_config(CONFIG_FILE)
        return load_config(CONFIG_FILE)

    def _save_config(self) -> dict:
        cfg = {
            "bot_token":   self._e_token.get().strip(),
            "chat_id":     self._e_chat.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": int(self._e_delay.get().strip() or 90),
            "provider":    self._e_provider.get().strip() or "TelegramBot",
            # Preservati finché non c'è un campo GUI dedicato (PR-13): senza questo
            # un salvataggio (anche all'avvio) cancellerebbe l'opt-out require_price.
            "recognition_mode": self._config.get("recognition_mode", "NAME_ONLY"),
            "require_price":    self._config.get("require_price", True),
            # Preservati come sopra (nessun campo GUI dedicato qui): la scelta del
            # Parser Personalizzato attivo (CP-07) non va persa al salvataggio.
            "active_parser":    self._config.get("active_parser", ""),
            "parser_by_chat":   self._config.get("parser_by_chat", {}),
        }
        return save_config(cfg, CONFIG_FILE)

    # ── UI ────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=10)
        hdr.pack(fill="x", padx=15, pady=(12, 5))

        ctk.CTkLabel(hdr, text="🤖  XTrader Signal Bridge",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#4fc3f7").pack(side="left", padx=15, pady=10)

        self._status_lbl = ctk.CTkLabel(hdr, text="⬤  OFFLINE",
                                         font=ctk.CTkFont(size=13, weight="bold"),
                                         text_color="#ef5350")
        self._status_lbl.pack(side="right", padx=15)

        # Config
        cfg_frame = ctk.CTkFrame(self, corner_radius=10)
        cfg_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(cfg_frame, text="⚙️  CONFIGURAZIONE",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=15, pady=(10, 4))

        fields = [
            ("🔑 Bot Token",     "bot_token",   True,  0, 0),
            ("💬 Chat ID",       "chat_id",     False, 1, 0),
            ("📄 CSV Path",      "csv_path",    False, 2, 0),
            ("⏱️ Timeout (sec)", "clear_delay", False, 3, 0),
            ("🏷️ Provider",     "provider",    False, 4, 0),
        ]
        self._entries = {}
        for label, key, is_pwd, row, col in fields:
            ctk.CTkLabel(cfg_frame, text=label, width=140, anchor="w").grid(
                row=row+1, column=col, padx=(15, 5), pady=3, sticky="w")
            e = ctk.CTkEntry(cfg_frame, width=510, show="●" if is_pwd else "")
            e.insert(0, str(self._config.get(key, "")))
            e.grid(row=row+1, column=col+1, padx=(0, 15), pady=3, sticky="w")
            self._entries[key] = e

        self._e_token    = self._entries["bot_token"]
        self._e_chat     = self._entries["chat_id"]
        self._e_csv      = self._entries["csv_path"]
        self._e_delay    = self._entries["clear_delay"]
        self._e_provider = self._entries["provider"]

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=6)

        self._btn_start = ctk.CTkButton(
            btn_frame, text="▶  AVVIA", width=160, height=42,
            fg_color="#2e7d32", hover_color="#1b5e20",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start)
        self._btn_start.pack(side="left", padx=5)

        self._btn_stop = ctk.CTkButton(
            btn_frame, text="■  STOP", width=160, height=42,
            fg_color="#c62828", hover_color="#7f0000",
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            command=self._stop)
        self._btn_stop.pack(side="left", padx=5)

        self._btn_clear = ctk.CTkButton(
            btn_frame, text="🗑️  Svuota CSV ora", width=175, height=42,
            command=self._manual_clear)
        self._btn_clear.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="💾  Salva Config", width=140, height=42,
            fg_color="#37474f", hover_color="#263238",
            command=lambda: [self._save_config(), self._log("💾 Configurazione salvata")],
        ).pack(side="right", padx=5)

        # Riga propria: la finestra è a larghezza fissa, non far sforare i pulsanti.
        tools_frame = ctk.CTkFrame(self, fg_color="transparent")
        tools_frame.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkButton(
            tools_frame, text="🧩  Parser Personalizzato", width=220, height=38,
            fg_color="#4527a0", hover_color="#311b92",
            command=self._open_parser_builder).pack(side="left", padx=5)

        # Ultimo segnale
        sig_frame = ctk.CTkFrame(self, corner_radius=10)
        sig_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(sig_frame, text="📡  ULTIMO SEGNALE",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self._sig_lbl = ctk.CTkLabel(
            sig_frame, text="Nessun segnale ricevuto ancora",
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=680, anchor="w")
        self._sig_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # Log
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 12))
        ctk.CTkLabel(log_frame, text="📋  LOG",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self._log_box = ctk.CTkTextbox(
            log_frame, font=ctk.CTkFont(size=11, family="Courier"), height=160)
        self._log_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    # ── LOG ───────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.insert("end", f"[{ts}] {msg}\n")
        self._log_box.see("end")

    # ── START / STOP ──────────────────────────
    def _start(self):
        cfg = self._save_config()
        if not cfg["bot_token"]:
            self._log("❌ Inserisci il Bot Token prima di avviare!")
            return

        self._running = True
        self._status_lbl.configure(text="⬤  ATTIVO", text_color="#66bb6a")
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")

        init_csv(cfg["csv_path"])
        self._log("🚀 Bridge avviato!")
        self._log(f"📄 CSV: {cfg['csv_path']}")
        self._log(f"⏱️  Auto-clear dopo: {cfg['clear_delay']}s")
        self._log("👂 In ascolto su Telegram...")

        self._bot_thread = threading.Thread(
            target=self._run_bot, args=(cfg,), daemon=True)
        self._bot_thread.start()

    def _stop(self):
        self._running = False
        if self._loop and self._tg_app:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._tg_app.updater.stop(), self._loop)
                asyncio.run_coroutine_threadsafe(
                    self._tg_app.stop(), self._loop)
            except Exception:
                pass
        if self._clear_timer:
            self._clear_timer.cancel()
        self._status_lbl.configure(text="⬤  OFFLINE", text_color="#ef5350")
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._log("🛑 Bridge fermato.")

    def _on_close(self):
        self._stop()
        self.after(500, self.destroy)

    # ── BOT TELEGRAM ──────────────────────────
    def _run_bot(self, cfg: dict):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _async_run():
            self._tg_app = ApplicationBuilder().token(cfg["bot_token"]).build()

            async def _handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
                msg = update.message or update.channel_post
                if not msg:
                    return
                text = msg.text or msg.caption or ''
                cid = cfg.get("chat_id", "").strip()
                if cid and str(msg.chat_id) != cid:
                    return
                if 'P.Bet.' not in text and '📊' not in text:
                    return
                self._process(text, cfg)

            self._tg_app.add_handler(MessageHandler(filters.ALL, _handle))
            await self._tg_app.initialize()
            await self._tg_app.start()
            await self._tg_app.updater.start_polling(allowed_updates=["message", "channel_post"])
            while self._running:
                await asyncio.sleep(1)
            await self._tg_app.updater.stop()
            await self._tg_app.stop()
            await self._tg_app.shutdown()

        try:
            self._loop.run_until_complete(_async_run())
        except Exception as ex:
            self.after(0, lambda: self._log(f"❌ Errore bot: {ex}"))
            self.after(0, self._stop)

    # ── PROCESS SIGNAL ────────────────────────
    def _process(self, text: str, cfg: dict):
        parsed = parse_message(text)
        row    = build_csv_row(parsed, cfg["provider"])

        # Non scrivere righe non riconoscibili o non piazzabili da XTrader:
        # meglio scartare un segnale incompleto che generare una riga ambigua.
        # Il validatore controlla campi-nome (modalità), BetType e prezzo (> 1.0).
        mode = recognition.normalize_mode(cfg.get("recognition_mode", "NAME_ONLY"))
        require_price = validator.require_price_enabled(cfg)
        status, detail = validator.validate(row, mode, require_price=require_price)
        if status != validator.VALID:
            self.after(0, lambda: self._log(
                f"⚠️ Segnale scartato ({status}, modalità {mode}): {detail}"))
            return

        # Registra la generazione PRIMA di scrivere: invalida eventuali clear in
        # coda di segnali precedenti, così non cancellano questo nuovo segnale.
        gen = self._gate.begin()
        write_csv(row, cfg["csv_path"])

        info = (f"🏆 {parsed['teams']}  |  "
                f"{parsed['signal_type']}  |  "
                f"q.{parsed['quota']}  |  "
                f"{parsed['probability']}%")

        self.after(0, lambda: self._sig_lbl.configure(text=info, text_color="white"))
        self.after(0, lambda: self._log(f"📱 Segnale ricevuto: {parsed['teams']}"))
        self.after(0, lambda: self._log(f"   Mercato: {parsed['signal_type']}  Quota: {parsed['quota']}"))
        self.after(0, lambda: self._log("✅ CSV aggiornato → XTrader può piazzare la scommessa"))

        # Auto-clear
        delay = cfg.get("clear_delay", 90)
        if self._clear_timer:
            self._clear_timer.cancel()
        self._clear_timer = threading.Timer(
            delay, lambda g=gen: self._do_clear(cfg["csv_path"], g))
        self._clear_timer.start()
        self.after(0, lambda: self._log(f"⏱️  CSV verrà svuotato tra {delay}s"))

    def _do_clear(self, path: str, gen: int):
        # Svuota solo se nessun segnale più recente è arrivato nel frattempo.
        if self._gate.clear_if_current(gen, lambda: init_csv(path)):
            self.after(0, lambda: self._log("🗑️  CSV svuotato → pronto per il prossimo segnale"))
        else:
            self.after(0, lambda: self._log("⏭️  Clear obsoleto ignorato (segnale più recente presente)"))

    def _manual_clear(self):
        path = self._e_csv.get().strip()
        if path:
            # begin() invalida eventuali timer pendenti, poi svuota subito.
            self._gate.begin()
            init_csv(path)
            self._log("🗑️  CSV svuotato manualmente")

    def _open_parser_builder(self):
        """Apre la finestra del costruttore di Parser Personalizzati (CP-06).

        Import lazy: la GUI del costruttore non serve all'avvio del bridge."""
        from .custom_parser_gui import CustomParserWindow
        provider = str(self._load_config().get("provider", "")).strip()
        win = CustomParserWindow(self, provider=provider)
        win.focus()
