#!/usr/bin/env python3
"""
XTrader Signal Bridge
Telegram → CSV → XTrader
"""

import customtkinter as ctk
import threading
import json
import os
import csv
import re
import asyncio
import time
from datetime import datetime
from pathlib import Path

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
    TELEGRAM_OK = True
except ImportError:
    TELEGRAM_OK = False

# ─────────────────────────────────────────────
# CONFIGURAZIONE
# ─────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

CSV_HEADER = [
    "Provider", "SelectionId", "MarketId", "SelectionName",
    "MarketName", "EventName", "MarketType", "BetType", "Price",
    "MinPrice", "MaxPrice"
]

MARKET_MAPPING = {
    "GOL SECONDO TEMPO": "NEXT_GOAL",
    "OVER 0.5":          "OVER_UNDER_05",
    "OVER 1.5":          "OVER_UNDER_15",
    "OVER 2.5":          "OVER_UNDER_25",
    "OVER 3.5":          "OVER_UNDER_35",
    "OVER 4.5":          "OVER_UNDER_45",
    "MATCH ODDS":        "MATCH_ODDS",
    "1X2":               "MATCH_ODDS",
    "GG":                "BOTH_TEAMS_TO_SCORE",
    "GOAL GOAL":         "BOTH_TEAMS_TO_SCORE",
    "NEXT GOAL":         "NEXT_GOAL",
    "DOPPIA CHANCE":     "DOUBLE_CHANCE",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────
def parse_message(text: str) -> dict:
    """Estrae i campi da un messaggio P.Bet."""
    lines = text.strip().split('\n')
    result = {
        'signal_type': '',
        'competition': '',
        'teams': '',
        'score': '',
        'time_': '',
        'quota': '',
        'probability': '',
        'bet_type': 'BACK',
    }
    for line in lines:
        line = line.strip()
        if 'P.Bet.' in line:
            m = re.search(r'P\.Bet\.\s+(.+?)(?:\s+[🔊✅🔇]|$)', line)
            if m:
                result['signal_type'] = m.group(1).strip()
        elif '🏆' in line:
            result['competition'] = re.sub(r'[🏆\s]+', ' ', line).strip()
        elif '🆚' in line:
            result['teams'] = re.sub(r'[🆚\s]+', ' ', line).strip().lstrip()
        elif '⚽' in line:
            result['score'] = re.sub(r'[⚽\s]+', ' ', line).strip()
        elif '⌚' in line:
            result['time_'] = re.sub(r'[⌚\s]+', ' ', line).strip()
        elif 'Quota' in line or '📈' in line:
            m = re.search(r'Quota\s*([\d,\.]+)', line)
            if m:
                result['quota'] = m.group(1).replace(',', '.')
        elif '📊' in line:
            m = re.search(r'([\d\.]+)\s*%', line)
            if m:
                result['probability'] = m.group(1)
    return result


def build_csv_row(parsed: dict, provider: str) -> dict:
    """Converte i dati parsati in una riga XTrader."""
    market_type = "MATCH_ODDS"
    signal_upper = parsed['signal_type'].upper()
    for key, val in MARKET_MAPPING.items():
        if key in signal_upper:
            market_type = val
            break

    teams = parsed['teams']
    home = teams.split(' v ')[0] if ' v ' in teams else teams
    is_goals = any(k in signal_upper for k in ["GOL", "OVER", "GOAL"])
    selection = "Over 0.5 Goals" if is_goals else home

    return {
        'Provider':      provider,
        'SelectionId':   '',
        'MarketId':      '',
        'SelectionName': selection,
        'MarketName':    parsed['signal_type'],
        'EventName':     teams,
        'MarketType':    market_type,
        'BetType':       parsed['bet_type'],
        'Price':         parsed.get('quota', ''),
        'MinPrice':      '',
        'MaxPrice':      '',
    }


def init_csv(path: str):
    """Crea/svuota il CSV lasciando solo l'header."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()


def write_csv(row: dict, path: str):
    """Scrive un segnale nel CSV (sovrascrive)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────
# APP GUI
# ─────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("XTrader Signal Bridge")
        self.geometry("720x650")
        self.resizable(False, False)

        self._config = self._load_config()
        self._running = False
        self._bot_thread = None
        self._clear_timer = None
        self._tg_app = None
        self._loop = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── CONFIG ────────────────────────────────
    def _load_config(self) -> dict:
        defaults = {
            "bot_token":   "",
            "chat_id":     "",
            "csv_path":    r"C:\XTrader\segnali.csv",
            "clear_delay": 90,
            "provider":    "TelegramBot",
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    defaults.update(data)
            except Exception:
                pass
        return defaults

    def _save_config(self) -> dict:
        cfg = {
            "bot_token":   self._e_token.get().strip(),
            "chat_id":     self._e_chat.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": int(self._e_delay.get().strip() or 90),
            "provider":    self._e_provider.get().strip() or "TelegramBot",
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        return cfg

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
            delay, lambda: self._do_clear(cfg["csv_path"]))
        self._clear_timer.start()
        self.after(0, lambda: self._log(f"⏱️  CSV verrà svuotato tra {delay}s"))

    def _do_clear(self, path: str):
        init_csv(path)
        self.after(0, lambda: self._log("🗑️  CSV svuotato → pronto per il prossimo segnale"))

    def _manual_clear(self):
        path = self._e_csv.get().strip()
        if path:
            init_csv(path)
            self._log("🗑️  CSV svuotato manualmente")


# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
