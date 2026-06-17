"""GUI CustomTkinter + listener Telegram.

Unica parte del progetto che dipende dalla GUI. La logica pura (parser, CSV,
config) vive in moduli separati ed è testabile headless.
"""

import asyncio
import threading
import time
from datetime import datetime

import customtkinter as ctk

from . import __version__
from .config_store import (
    CONFIG_FILE,
    config_dir,
    load_config,
    migrate_legacy_config,
    save_config,
)
from .csv_writer import init_csv, write_rows
from . import (
    confirmation_reader,
    event_log,
    live_guard,
    safety_guard,
    settings_validation,
    signal_dedupe,
    signal_queue,
    signal_router,
)

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
    TELEGRAM_OK = True
except ImportError:
    TELEGRAM_OK = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Ritardo (s) di retry quando una riscrittura del CSV fallisce (es. file bloccato da
# XTrader oltre i retry atomici): breve, per non lasciare una riga stantia per un
# intero intervallo di timeout (PR-23, finding Codex).
_WRITE_RETRY_DELAY = 5


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"XTrader Signal Bridge v{__version__}")
        self.geometry("720x700")
        self.resizable(False, False)

        self._config = self._load_config()
        self._running = False
        self._bot_thread = None
        self._tg_app = None
        self._loop = None
        # Guardrail del percorso di scrittura (PR-21), creati allo START dalla config:
        # tracker = dedup + limite/minuto (PR-15); daily = limite/giorno (PR-19).
        self._tracker = None
        self._daily = None
        # Coda dei segnali attivi (PR-22): determina quali righe sono nel CSV e
        # gestisce i timeout per-segnale. Mutata sia dal thread del bot (add) sia dal
        # timer di scadenza → protetta da un lock. Sostituisce il vecchio SignalGate.
        self._queue = None
        self._queue_lock = threading.Lock()
        self._expire_timer = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── CONFIG ────────────────────────────────
    def _load_config(self) -> dict:
        # Migra il vecchio config.json (accanto all'EXE) la prima volta, poi carica
        # dalla cartella utente persistente (%APPDATA%\XTraderBridge).
        migrate_legacy_config(CONFIG_FILE)
        return load_config(CONFIG_FILE)

    def _save_config(self) -> dict:
        # Timeout robusto: un valore non numerico non deve crashare il salvataggio
        # (PR-13/#10). Se invalido, si tiene il default e si avvisa nel log.
        delay, delay_err = settings_validation.parse_timeout(self._e_delay.get())
        if delay_err:
            delay = settings_validation.DEFAULT_TIMEOUT
            self._log(f"⚠️ {delay_err} Uso {delay}s.")
        # Si parte dalla config CARICATA e si sovrascrivono solo i campi del form:
        # così ogni impostazione senza campo GUI (recognition_mode, require_price,
        # active_parser, parser_by_chat, source_chats, le chiavi delle conferme
        # XTrader, ecc.) viene PRESERVATA e non si perde al salvataggio — niente
        # drift quando si aggiungono nuove chiavi.
        cfg = dict(self._config) if isinstance(self._config, dict) else {}
        cfg.update({
            "bot_token":   self._e_token.get().strip(),
            "chat_id":     self._e_chat.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": delay,
            "provider":    self._e_provider.get().strip() or "TelegramBot",
        })
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
    def _log(self, msg: str, level: str = None):
        # Redazione unica nel sink condiviso: un token incorporato per sbaglio
        # (es. nel testo di un'eccezione del bot) non finisce mai nel log, né a
        # schermo né su file (invariante: mai token nei log).
        safe = event_log.redact_secrets(msg)
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.insert("end", f"[{ts}] {safe}\n")
        self._log_box.see("end")
        # Storico persistente in AppData (#11): sopravvive al riavvio. Il livello,
        # se non passato, è derivato dal marker del messaggio (❌/⚠️/📱) così lo
        # storico distingue errori/segnali. Best-effort: un errore di filesystem
        # non deve interrompere la GUI.
        event_log.append_entry(safe, level or event_log.classify(safe))

    # ── GUARDRAIL (PR-21) ─────────────────────
    def _dedupe_state_path(self) -> str:
        # History anti-duplicato accanto al config (AppData): i duplicati recenti
        # restano riconosciuti dopo un riavvio.
        import os
        return os.path.join(config_dir(), "dedupe_state.json")

    def _daily_state_path(self) -> str:
        # Conteggio giornaliero persistito: stop/start nello stesso giorno (UTC)
        # NON deve azzerare il tetto (altrimenti il limite/giorno è aggirabile).
        import os
        return os.path.join(config_dir(), "daily_state.json")

    def _init_guards(self, cfg: dict) -> None:
        """Crea i guardrail del percorso di scrittura dalla config (chiamato allo
        START). `max_per_day` invalido in config → default sicuro con avviso."""
        import os
        self._dedupe_save_warned = False
        self._tracker = signal_dedupe.SignalTracker()
        # Avvisa solo se lo stato ESISTE ma non è caricabile (corrotto/illeggibile):
        # l'assenza al primo avvio è normale, non un degrado.
        dpath = self._dedupe_state_path()
        if os.path.exists(dpath) and not signal_dedupe.load_state(self._tracker, dpath):
            self._log("⚠️ Stato anti-duplicato presente ma illeggibile: "
                      "protezione dopo riavvio non garantita.")
        try:
            self._daily = safety_guard.DailyLimiter(
                max_per_day=cfg.get("max_per_day", safety_guard.DEFAULT_MAX_PER_DAY))
        except ValueError:
            self._daily = safety_guard.DailyLimiter()
            self._log(f"⚠️ max_per_day non valido in config: uso "
                      f"{safety_guard.DEFAULT_MAX_PER_DAY}.")
        self._load_daily_state()
        # Coda dei segnali attivi (PR-22): il timeout per-segnale è `clear_delay`
        # (stesso valore dell'auto-clear), così OVERWRITE_LAST replica il
        # comportamento storico (un segnale, svuotato dopo il timeout).
        mode = signal_queue.normalize_mode(cfg.get("queue_mode"))
        delay = cfg.get("clear_delay", settings_validation.DEFAULT_TIMEOUT)
        try:
            self._queue = signal_queue.SignalQueue(mode=mode, default_timeout=delay)
        except ValueError:
            self._queue = signal_queue.SignalQueue(mode=mode)
            self._log(f"⚠️ clear_delay non valido per la coda: uso il default.")
        # Fonte UNICA del timeout (validata dalla coda): usata anche dai timer di
        # scadenza, così coda e timer condividono lo stesso valore valido.
        self._queue_timeout = self._queue.default_timeout
        self._log(f"🧮 Modalità coda: {mode}")

    def _load_daily_state(self) -> None:
        """Ripristina il conteggio giornaliero (persistenza same-day tra START/STOP).
        Best-effort: file assente/illeggibile → si riparte da 0 per oggi."""
        import json
        if self._daily is None:
            return
        try:
            with open(self._daily_state_path(), encoding="utf-8") as f:
                self._daily.restore_state(json.load(f))
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    def _save_guard_state(self) -> None:
        """Persiste lo stato dei guardrail su disco DOPO una decisione/scrittura.
        Dedupe: atomico, con avviso (una sola volta) se fallisce. Daily: best-effort."""
        import json
        import os
        if (not signal_dedupe.save_state(self._tracker, self._dedupe_state_path())
                and not self._dedupe_save_warned):
            self._dedupe_save_warned = True
            self.after(0, lambda: self._log(
                "⚠️ Impossibile salvare lo stato anti-duplicato su disco: "
                "protezione dopo riavvio degradata."))
        if self._daily is not None:
            try:
                path = self._daily_state_path()
                d = os.path.dirname(os.path.abspath(path))
                if d:
                    os.makedirs(d, exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._daily.state(), f)
                os.replace(tmp, path)
            except OSError:
                pass

    # ── START / STOP ──────────────────────────
    def _start(self):
        if not TELEGRAM_OK:
            # Libreria python-telegram-bot assente: errore chiaro, niente crash
            # silenzioso nel thread del bot (PR-11, #11).
            self._log("❌ python-telegram-bot non disponibile: impossibile avviare il listener.")
            return
        # Validazione sui valori GREZZI dei campi PRIMA del salvataggio
        # (PR-13/#10): _save_config normalizza il timeout invalido al default,
        # quindi validare la cfg dopo il save non vedrebbe più l'errore e il
        # bridge partirebbe a 90s ignorando l'input dell'utente.
        raw = {
            "bot_token":   self._e_token.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": self._e_delay.get().strip(),
        }
        if not raw["bot_token"]:
            self._log("❌ Inserisci il Bot Token prima di avviare!")
            return
        errors = settings_validation.validate_settings(raw)
        if errors:
            for err in errors:
                self._log(f"❌ {err}")
            return

        cfg = self._save_config()
        # Fail-fast (PR-23): la chat notifiche XTrader NON deve coincidere con una chat
        # sorgente (chat_id o un override parser_by_chat); altrimenti i segnali di quella
        # chat finirebbero nel percorso di conferma e verrebbero ignorati silenziosamente.
        notif = str(cfg.get("xtrader_notification_chat_id", "") or "").strip()
        if notif:
            sources = {str(cfg.get("chat_id", "") or "").strip()}
            sources.update(str(k).strip() for k in (cfg.get("parser_by_chat") or {}))
            sources.discard("")
            if notif in sources:
                self._log("❌ La Chat notifiche XTrader coincide con una chat sorgente: "
                          "cambiala (i segnali verrebbero scambiati per conferme). Avvio annullato.")
                return

        self._running = True
        self._status_lbl.configure(text="⬤  ATTIVO", text_color="#66bb6a")
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")

        init_csv(cfg["csv_path"])
        self._init_guards(cfg)
        self._log("🚀 Bridge avviato!")
        self._log(f"📄 CSV: {cfg['csv_path']}")
        self._log(f"⏱️  Auto-clear dopo: {cfg['clear_delay']}s")
        if safety_guard.is_dry_run(cfg):
            self._log("🧪 DRY_RUN attivo (simulazione): il CSV operativo NON verrà scritto.")
        else:
            self._log("⚠️ Modalità REALE: i segnali validi verranno scritti nel CSV.")
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
        if self._expire_timer:
            self._expire_timer.cancel()
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
                runtime_chat = str(msg.chat_id)
                # PR-23: la chat notifiche XTrader (SEPARATA dalle sorgenti) porta
                # ESITI, non segnali → percorso di conferma, non di scrittura.
                notif = str(cfg.get("xtrader_notification_chat_id", "") or "").strip()
                if notif and runtime_chat == notif:
                    self._process_confirmation(text, cfg)
                    return
                # PR-11: decisione di instradamento estratta e testabile.
                # Gatea il filtro chat (CP-09, chat configurata ∪ parser_by_chat)
                # e il prefiltro legacy P.Bet./📊 (solo per il parser hardcoded):
                # una chat non ammessa o un messaggio non pertinente non scrive.
                if not signal_router.should_process(cfg, runtime_chat, text):
                    return
                self._process(text, cfg, chat_id=runtime_chat)

            self._tg_app.add_handler(MessageHandler(filters.ALL, _handle))
            await self._tg_app.initialize()
            await self._tg_app.start()
            # drop_pending_updates: scarta i messaggi accodati mentre il bridge era
            # offline, così all'avvio non si processano segnali vecchi (PR-11, #9).
            await self._tg_app.updater.start_polling(
                allowed_updates=["message", "channel_post"], drop_pending_updates=True)
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
    def _process(self, text: str, cfg: dict, chat_id: str = None):
        # CP-09: instrada al Parser Personalizzato attivo (autoritativo) o, in
        # assenza, al parser hardcoded. Non scrive righe non piazzabili: meglio
        # scartare un segnale incompleto che generare una riga ambigua.
        result = signal_router.resolve_row(text, cfg, chat_id=chat_id)
        if not result.placeable:
            detail = (", ".join(result.missing_required)
                      if result.missing_required else result.detail)
            self.after(0, lambda: self._log(
                f"⚠️ Segnale scartato ({result.source}/{result.status}): {detail}"))
            return

        row = result.row

        # Guardrail del percorso di scrittura (PR-21): dedup + limite/minuto +
        # limite/giorno + DRY_RUN. Solo WRITE autorizza la scrittura; ogni altro
        # esito la sopprime (anti-doppia-scommessa / simulazione). `evaluate`
        # consuma lo stato (registra il messaggio, scala il tetto): si fa uno
        # snapshot per poterlo annullare se la scrittura del CSV poi fallisce.
        tracker_snap = daily_snap = None
        if self._tracker is not None:
            tracker_snap = self._tracker.state()
            daily_snap = self._daily.state() if self._daily is not None else None
            decision = live_guard.evaluate(cfg, self._tracker, self._daily, text)
            if decision != live_guard.WRITE:
                self._save_guard_state()
                self._after_non_write(decision, row)
                return

        # Coda dei segnali attivi (PR-22): aggiunge il segnale (OVERWRITE_LAST
        # sostituisce l'attivo; APPEND_ACTIVE/QUEUE_UNTIL_CONFIRMED accodano) e
        # riscrive TUTTE le righe attive in modo atomico. `expire` prima dell'add
        # rimuove i segnali già scaduti.
        path = cfg["csv_path"]
        now = time.time()
        # Lock tenuto ATTRAVERSO la scrittura: stato della coda e contenuto del CSV
        # evolvono in modo monotòno (nessuna corsa con il tick di scadenza).
        write_error = None
        with self._queue_lock:
            queue_snap = self._queue.state()      # snapshot per rollback su write fallita
            self._queue.expire(now=now)
            self._queue.add(row, now=now)
            rows = self._queue.active_rows()
            try:
                write_rows(rows, path)
            except Exception as ex:   # noqa: BLE001 — esito riportato a log, no crash
                # Scrittura fallita: RIPRISTINA la coda allo stato precedente (allineato
                # al CSV ancora su disco). In OVERWRITE_LAST il segnale precedente NON
                # va perso e il nuovo è riprovabile.
                self._queue.restore_state(queue_snap)
                write_error = ex
        if write_error is not None:
            # Annulla anche il consumo dei guardrail → il segnale non resta soppresso.
            if self._tracker is not None:
                self._tracker.restore_state(tracker_snap)
                if self._daily is not None and daily_snap is not None:
                    self._daily.restore_state(daily_snap)
            self.after(0, lambda e=write_error: self._log(
                f"❌ Scrittura CSV fallita: {e}. Segnale non registrato (riprovabile)."))
            self._schedule_expiry(path)           # i segnali ripristinati devono comunque scadere
            return
        # Scrittura riuscita: ora è sicuro persistere lo stato dei guardrail.
        if self._tracker is not None:
            self._save_guard_state()

        info = (f"🏆 {row.get('EventName', '')}  |  "
                f"{row.get('SelectionName', '')}  |  "
                f"q.{row.get('Price', '')}")

        self.after(0, lambda: self._sig_lbl.configure(text=info, text_color="white"))
        self.after(0, lambda: self._log(
            f"📱 Segnale ({result.source}): {row.get('EventName', '')}  |  "
            f"{row.get('SelectionName', '')}  q.{row.get('Price', '')}"))
        self.after(0, lambda n=len(rows): self._log(
            f"✅ CSV aggiornato ({n} attiv{'o' if n == 1 else 'i'}) → XTrader può piazzare"))

        # Scadenza per-segnale: (ri)programma il tick alla scadenza più vicina (non un
        # ritardo fisso, così un segnale più vecchio non resta oltre il suo timeout).
        self._schedule_expiry(path)
        self.after(0, lambda d=self._queue_timeout: self._log(f"⏱️  Scadenza segnale tra ~{d}s"))

    def _after_non_write(self, decision: str, row: dict) -> None:
        """Gestisce gli esiti che NON scrivono il CSV (PR-21): log chiaro e, in
        DRY_RUN, aggiorna comunque l'ultimo segnale riconosciuto."""
        ev = row.get("EventName", "")
        sel = row.get("SelectionName", "")
        if decision == live_guard.DRY_RUN:
            info = f"🧪 DRY_RUN — {ev}  |  {sel}  q.{row.get('Price', '')}"
            self.after(0, lambda: self._sig_lbl.configure(text=info, text_color="#ffb74d"))
            self.after(0, lambda: self._log(
                f"🧪 DRY_RUN: segnale riconosciuto ma CSV NON scritto (simulazione): "
                f"{ev} | {sel}"))
        elif decision == live_guard.DUPLICATE:
            self.after(0, lambda: self._log(
                f"♻️ Duplicato ignorato (nessuna doppia scommessa): {ev} | {sel}"))
        elif decision == live_guard.RATE_LIMITED:
            self.after(0, lambda: self._log(
                "🚦 Limite al minuto raggiunto: segnale ignorato."))
        elif decision == live_guard.DAILY_LIMITED:
            self.after(0, lambda: self._log(
                "🚦 Limite giornaliero raggiunto: segnale ignorato."))

    def _process_confirmation(self, text: str, cfg: dict) -> None:
        """Interpreta una notifica XTrader (PR-23) rispetto ai segnali in attesa e,
        se associata, marca l'esito rimuovendo il segnale dalla coda + CSV.

        - CONFIRMED (piazzata) o REJECTED (rifiutata/errore) → rimuove il segnale
          (scelta del proprietario: una volta che XTrader ha risposto, la riga non
          resta nel CSV);
        - UNKNOWN (associato ma esito non chiaro) / UNMATCHED (di un'altra scommessa)
          → solo log, nessuna modifica. Il TIMEOUT è già coperto dalla scadenza coda.
        """
        confirm_kw = confirmation_reader.normalize_keywords(cfg.get("confirmation_keywords"))
        reject_kw = confirmation_reader.normalize_keywords(cfg.get("rejection_keywords"))
        with self._queue_lock:
            pending = self._queue.pending() if self._queue is not None else []
        # interpret è puro: lo si chiama fuori dal lock (nessuna mutazione qui).
        result = confirmation_reader.interpret(
            text, pending, confirm_keywords=confirm_kw, reject_keywords=reject_kw)

        if result.status in (confirmation_reader.CONFIRMED, confirmation_reader.REJECTED):
            path = cfg["csv_path"]
            write_error = None
            with self._queue_lock:
                self._queue.confirm(result.signal_id)   # rimuove il segnale dalla coda
                rows = self._queue.active_rows()
                try:
                    write_rows(rows, path)
                except Exception as ex:   # noqa: BLE001 — esito a log, no crash
                    write_error = ex
            esito = ("confermato (CONFIRMED)"
                     if result.status == confirmation_reader.CONFIRMED
                     else "rifiutato (REJECTED)")
            if write_error is not None:
                # Il segnale è già rimosso dalla coda ma il CSV (write fallita) ha
                # ancora la riga: riprova PRESTO (non a timeout pieno, che terrebbe la
                # riga stantia un intero intervallo) così la riga sparisce in fretta.
                self.after(0, lambda e=write_error: self._log(
                    f"❌ Aggiornamento CSV dopo conferma fallito: {e}. Riprovo a breve."))
                self._schedule_expiry(path, delay=_WRITE_RETRY_DELAY)
                return
            self.after(0, lambda v=esito: self._log(
                f"✅ XTrader: segnale {v} → rimosso dal CSV"))
            self._schedule_expiry(path)   # riprogramma per i segnali eventualmente rimasti
        elif result.status == confirmation_reader.UNKNOWN:
            self.after(0, lambda: self._log(
                "ℹ️ Notifica XTrader associata a un segnale ma esito non chiaro: ignorata."))
        else:  # UNMATCHED
            self.after(0, lambda: self._log(
                "ℹ️ Notifica XTrader non associata ad alcun segnale attivo: ignorata."))

    def _schedule_expiry(self, path: str, delay=None) -> None:
        """(Ri)programma il tick di scadenza (PR-22). Con `delay=None` lo programma
        alla **scadenza più vicina** della coda (così un segnale più vecchio non
        resta oltre il suo timeout quando ne arrivano di nuovi); con un `delay`
        esplicito lo usa come ritardo (retry dopo un errore di scrittura)."""
        if delay is None:
            with self._queue_lock:
                nxt = self._queue.next_expiry() if self._queue is not None else None
            if nxt is None:
                return                       # niente di attivo: nessun tick da programmare
            delay = max(0.0, nxt - time.time())
        if self._expire_timer:
            self._expire_timer.cancel()
        self._expire_timer = threading.Timer(delay, lambda: self._expire_tick(path))
        self._expire_timer.daemon = True
        self._expire_timer.start()

    def _expire_tick(self, path: str) -> None:
        """Rimuove i segnali scaduti e riscrive le righe rimaste (o svuota il CSV
        se non ne resta nessuno). La scadenza è basata sul tempo della coda: non
        cancella mai un segnale ancora valido. Si riprogramma alla scadenza più
        vicina finché la coda non è vuota."""
        now = time.time()
        # Lock tenuto ATTRAVERSO la scrittura (monotòno con _process).
        write_error = None
        with self._queue_lock:
            if self._queue is None:
                return
            expired = self._queue.expire(now=now)
            rows = self._queue.active_rows()
            empty = self._queue.is_empty()
            try:
                write_rows(rows, path)    # rows vuota → solo header (CSV svuotato)
            except Exception as ex:       # noqa: BLE001 — esito riportato a log, no crash
                write_error = ex
        if write_error is not None:
            # La coda (memoria) ha già rimosso gli scaduti ma il CSV è rimasto indietro:
            # RIPROVA con un ritardo limitato (non a scadenza, che sarebbe nel passato
            # → busy-loop), così il disco converge allo stato della coda. Riprogramma
            # anche a coda vuota (un segnale scaduto non deve restare nel CSV).
            self.after(0, lambda e=write_error: self._log(
                f"❌ Aggiornamento CSV alla scadenza fallito: {e}. Riprovo a breve."))
            self._schedule_expiry(path, delay=_WRITE_RETRY_DELAY)
            return
        if expired:
            self.after(0, lambda n=len(expired): self._log(
                f"🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV"))
        if not empty:
            self._schedule_expiry(path)

    def _manual_clear(self):
        path = self._e_csv.get().strip()
        if not path:
            return
        # Ferma il tick di scadenza, svuota la coda e il CSV subito (PR-22).
        if self._expire_timer:
            self._expire_timer.cancel()
        with self._queue_lock:
            if self._queue is not None:
                for sid in self._queue.active_ids():
                    self._queue.remove(sid)
        init_csv(path)
        self._log("🗑️  CSV svuotato manualmente")

    def _open_parser_builder(self):
        """Apre la finestra del costruttore di Parser Personalizzati (CP-06).

        Import lazy: la GUI del costruttore non serve all'avvio del bridge."""
        from .custom_parser_gui import CustomParserWindow
        provider = str(self._load_config().get("provider", "")).strip()
        win = CustomParserWindow(self, provider=provider)
        win.focus()
