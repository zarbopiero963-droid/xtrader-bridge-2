"""Schermata «🔑 Licenza» (#140 PR 2) — pannello embeddable, **SENZA blocco**.

Mostra l'**Hardware ID** della macchina (da comunicare al proprietario), un campo per **incollare
la chiave** di attivazione, un pulsante **«Attiva»** e lo **stato** corrente (nome, scadenza,
giorni / motivo). L'attivazione verifica la chiave (`license_status.compute_status`, fail-closed) e,
solo se valida, la **persiste** (`license_store`). In questa PR **non disabilita nulla**: l'app
funziona come prima. Il lock totale della GUI è la PR 4 (che riuserà questo stesso pannello).

Logica pura testata a parte (`license_status`, `license_store`); qui c'è solo il cablaggio Tk
(best-effort, verifica manuale su Windows) e l'handler di attivazione — scritto per essere
esercitabile headless su un `self` finto (stesso pattern dei meta-test GUI del repo).
"""

from __future__ import annotations

import logging

import customtkinter as ctk

from . import i18n, ui_theme, license_status

_log = logging.getLogger(__name__)

# Heartbeat anti-rollback: quanti fallimenti di scrittura CONSECUTIVI si tollerano (lock transitori
# di antivirus/indexer su `%APPDATA%`) prima di considerare la persistenza rotta in modo PERSISTENTE
# e passare a fail-closed (review GPT-5.5/Fable #144). Sotto soglia la licenza valida resta valida.
_HEARTBEAT_FAIL_LIMIT = 3

# Colori di stato (token WCAG-safe del design system; semantica invariata: verde=ok, rosso=errore,
# arancio=avviso). ACCENT = pulsante primario «Attiva».
_COLOR_OK = ui_theme.STATUS_OK
_COLOR_ERR = ui_theme.STATUS_ERR
_COLOR_WARN = ui_theme.STATUS_WARN
_COLOR_MUTED = ui_theme.TEXT2
_SEVERITY_COLOR = {"ok": _COLOR_OK, "warn": _COLOR_WARN, "error": _COLOR_ERR}


class LicensePanel(ctk.CTkFrame):
    """Pannello della schermata Licenza (embeddable in una scheda o, in PR 4, a tutta finestra).

    Dipendenze iniettate (così è testabile e disaccoppiato dalla GUI principale):
        hardware_id_provider: () -> str      — impronta macchina (mai vuota; sentinella se cieca).
        load_state:           () -> (token, last_seen)   — stato persistito (o (None, None)).
        save_state:           (token, last_seen) -> None — persiste una licenza attivata.
        now_provider:         () -> int       — unix seconds UTC correnti.
        on_status_change:     (LicenseStatus) -> None    — hook opzionale (PR 4: gate lock).
    """

    def __init__(self, master=None, *, hardware_id_provider=None, load_state=None,
                 save_state=None, now_provider=None, on_status_change=None):
        super().__init__(master)
        self._hardware_id_provider = hardware_id_provider
        self._load_state = load_state
        self._save_state = save_state
        self._now_provider = now_provider
        self._on_status_change = on_status_change
        self._entry = None
        self._status_lbl = None
        self._msg_lbl = None
        self._heartbeat_failures = 0     # fallimenti heartbeat CONSECUTIVI (anti-rollback)
        self._build_ui()
        self.refresh_options()

    # ── costruzione UI (verifica manuale su Windows) ──────────────────────────────────────────
    def _build_ui(self) -> None:
        ctk.CTkLabel(self, text=i18n.tr("🔑 Licenza"),
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(
                         fill="x", padx=10, pady=(10, 2))

        # Hardware ID + copia
        hw_row = ctk.CTkFrame(self, fg_color="transparent")
        hw_row.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(hw_row, text=i18n.tr("Hardware ID di questa macchina:"),
                     anchor="w").pack(side="top", fill="x")
        self._hw_value = ctk.CTkLabel(hw_row, text="—", anchor="w",
                                      font=ctk.CTkFont(family=ui_theme.FONT_MONO, size=13,
                                                       weight="bold"))
        self._hw_value.pack(side="left", padx=(0, 8))
        ctk.CTkButton(hw_row, text=i18n.tr("📋 Copia"), width=90, height=ui_theme.H_CTRL,
                      fg_color=ui_theme.SURFACE3, hover_color=ui_theme.BORDER,
                      text_color=ui_theme.TEXT, command=self._copy_hardware_id).pack(side="left")
        ctk.CTkLabel(self, text=i18n.tr("Comunica questo codice al fornitore per ricevere la chiave."),
                     text_color=_COLOR_MUTED, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        # Stato corrente
        self._status_lbl = ctk.CTkLabel(self, text="—", anchor="w",
                                        font=ctk.CTkFont(weight="bold"))
        self._status_lbl.pack(fill="x", padx=10, pady=(4, 8))

        # Campo chiave + Attiva
        ctk.CTkLabel(self, text=i18n.tr("Incolla qui la chiave di attivazione:"),
                     anchor="w").pack(fill="x", padx=10, pady=(2, 2))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 4))
        self._entry = ctk.CTkEntry(row, height=ui_theme.H_CTRL,
                                   placeholder_text=i18n.tr("chiave licenza…"))
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text=i18n.tr("✅ Attiva"), width=110, height=ui_theme.H_CTRL,
                      fg_color=ui_theme.ACCENT, hover_color=ui_theme.ACCENT_HOV,
                      command=self._on_activate).pack(side="left")

        # Esito dell'ultima attivazione
        self._msg_lbl = ctk.CTkLabel(self, text="", anchor="w", text_color=_COLOR_MUTED)
        self._msg_lbl.pack(fill="x", padx=10, pady=(2, 10))

    # ── azioni ────────────────────────────────────────────────────────────────────────────────
    def _copy_hardware_id(self) -> None:
        """Copia l'Hardware ID negli appunti (best-effort)."""
        try:
            hwid = self._hardware_id_provider() if self._hardware_id_provider else ""
            self.clipboard_clear()
            self.clipboard_append(hwid)
            if self._msg_lbl is not None:
                self._msg_lbl.configure(text=i18n.tr("📋 Hardware ID copiato."),
                                        text_color=_COLOR_MUTED)
        except Exception:       # noqa: BLE001 — clipboard best-effort: non deve rompere la finestra
            pass

    def _on_activate(self) -> None:
        """Verifica la chiave incollata e, se valida, la persiste. Nessun blocco: aggiorna lo stato."""
        outcome = self._evaluate_activation(self._read_entry())
        if self._msg_lbl is not None:
            sev = "ok" if outcome["accepted"] else "error"
            self._msg_lbl.configure(text=outcome["message"],
                                    text_color=_SEVERITY_COLOR.get(sev, _COLOR_MUTED))
        self.refresh_options()

    def _read_entry(self) -> str:
        """Testo del campo chiave (best-effort headless)."""
        try:
            return (self._entry.get() or "").strip() if self._entry is not None else ""
        except Exception:       # noqa: BLE001 — entry non disponibile (headless/teardown)
            return ""

    def _evaluate_activation(self, pasted_token: str) -> dict:
        """Logica PURA dell'attivazione (esercitabile su self finto): verifica la chiave incollata
        contro l'Hardware ID corrente; se valida la persiste con `last_seen` monotòno. Ritorna
        ``{accepted, message}``. Non solleva: input vuoto → messaggio d'invito."""
        if not pasted_token:
            return {"accepted": False, "message": i18n.tr("⚠️ Incolla prima una chiave.")}
        hwid = self._hardware_id_provider() if self._hardware_id_provider else ""
        now = int(self._now_provider()) if self._now_provider else 0
        _token, last_seen = self._load_state() if self._load_state else (None, None)
        status = license_status.compute_status(pasted_token, hwid, now, last_seen=last_seen)
        if not status.valid:
            return {"accepted": False, "message": license_status.status_message(status)}
        if self._save_state:
            try:
                self._save_state(pasted_token, license_status.next_last_seen(last_seen, now))
            except Exception:       # noqa: BLE001 — persistenza fallita (disco/permessi): attivazione
                # NON riuscita, lo stato precedente su disco resta intatto (save atomico). Il metodo
                # mantiene il contratto «non solleva»: ritorna un esito di errore leggibile.
                return {"accepted": False,
                        "message": i18n.tr("⚠️ Impossibile salvare la licenza su disco (permessi?). "
                                           "Riprova.")}
        return {"accepted": True,
                "message": i18n.tr("✅ Licenza attivata — {name}.").format(name=status.name or "")}

    def current_status(self):
        """Stato licenza corrente + **heartbeat anti-rollback** (usabile anche da PR 4 come gate).

        Il heartbeat registra `next_last_seen(last_seen, now)` così, dopo l'attivazione, tenere
        l'orologio a un istante pre-scadenza non basta a non scadere mai. Politica (sintesi delle
        review CodeRabbit/GPT/Fable #144):
        - si scrive **solo quando l'orologio è AVANZATO** (`advanced > last_seen`): niente write ad
          ogni refresh/gate → niente `os.replace` concorrenti su Windows;
        - un fallimento di scrittura **transitorio** (lock antivirus/indexer) è **tollerato** (la
          licenza valida resta valida): si conta il numero di fallimenti CONSECUTIVI;
        - un fallimento **PERSISTENTE** (≥ `_HEARTBEAT_FAIL_LIMIT` consecutivi) è **fail-closed**
          (`PERSIST_FAILED`): un utente non può negare la scrittura di `last_seen` per non far mai
          avanzare l'orologio-di-riferimento e aggirare la scadenza. Un write riuscito azzera il conto.

        Non solleva: i **provider** (hwid/now/load_state) sono racchiusi qui — un provider difettoso
        (es. WMI/registro Windows) degrada a stato neutro «nessuna licenza» senza rompere il chiamante.

        Limite onesto (review GPT/GLM #144): il contatore `_heartbeat_failures` è **in memoria**, quindi
        si azzera al riavvio dell'app; inoltre nessun check offline è perfetto (issue #140). In questa
        PR **non c'è alcun blocco** (la scheda è informativa), perciò questo non ha conseguenze reali; la
        politica anti-rollback robusta — e se renderla restart-safe — è una decisione della **PR 4**
        (il lock), dove il meccanismo gate ha davvero effetto. Persistere il contatore qui non aiuterebbe
        (se il disco non è scrivibile, non si potrebbe scriverlo comunque).
        """
        try:
            hwid = self._hardware_id_provider() if self._hardware_id_provider else ""
            now = int(self._now_provider()) if self._now_provider else 0
            token, last_seen = self._load_state() if self._load_state else (None, None)
        except Exception as exc:    # noqa: BLE001 — provider difettoso: non determinabile → neutro
            _log.warning("License providers non disponibili: %s: %s", type(exc).__name__, exc)
            return license_status.LicenseStatus(valid=False, reason=license_status.NOT_PRESENT,
                                                name=None, issued=None, expiry=None, days_left=0)

        # `prev` sanitizzato al confine (review Fable #144): un `last_seen` NON numerico (stato
        # corrotto, provider anomalo) → None, mai un `int()` che solleverebbe dentro `verify_license`
        # (anti-rollback) o nell'heartbeat. `load_license` già sanifica in produzione; qui è
        # belt-and-suspenders in un solo punto, così sia `compute_status` sia il heartbeat vedono
        # lo stesso valore pulito, senza un catch ampio che mascheri gli errori veri di compute.
        try:
            prev = int(last_seen) if last_seen is not None else None
        except (TypeError, ValueError):
            prev = None

        status = license_status.compute_status(token, hwid, now, last_seen=prev)
        if status.valid and token and self._save_state:
            advanced = license_status.next_last_seen(prev, now)
            if prev is None or advanced > prev:
                try:
                    self._save_state(token, advanced)
                    self._heartbeat_failures = 0                    # write riuscito → reset conto
                except Exception as exc:    # noqa: BLE001 — heartbeat: tollera i transitori, fail-closed
                    # sui persistenti (né `pass` cieco né fail-closed al primo lock).
                    self._heartbeat_failures = getattr(self, "_heartbeat_failures", 0) + 1
                    _log.warning("Heartbeat licenza non persistibile (%d/%d): %s: %s",
                                 self._heartbeat_failures, _HEARTBEAT_FAIL_LIMIT,
                                 type(exc).__name__, exc)
                    if self._heartbeat_failures >= _HEARTBEAT_FAIL_LIMIT:
                        return license_status.LicenseStatus(
                            valid=False, reason=license_status.PERSIST_FAILED, name=status.name,
                            issued=status.issued, expiry=status.expiry, days_left=0)
        return status

    def refresh_options(self) -> None:
        """Ricalcola e mostra Hardware ID + stato dalla persistenza (hook al cambio scheda)."""
        # `current_status` non solleva: racchiude i provider al suo interno (un provider difettoso
        # degrada a stato neutro), quindi qui NON serve un catch ampio che maschererebbe anche gli
        # errori di `compute_status`/heartbeat (review Fable #144).
        status = self.current_status()
        # SOLO il rendering Tk è best-effort (un widget distrutto/headless non deve rompere la
        # scheda, come gli altri pannelli sola-lettura).
        try:
            hwid = self._hardware_id_provider() if self._hardware_id_provider else "—"
            if getattr(self, "_hw_value", None) is not None:
                self._hw_value.configure(text=hwid or "—")
            if self._status_lbl is not None:
                sev = license_status.status_severity(status)
                self._status_lbl.configure(text=license_status.status_message(status),
                                           text_color=_SEVERITY_COLOR.get(sev, _COLOR_MUTED))
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass
        # Hook di stato FUORI dal try (review Fable #144): in PR 4 questo sarà il **gate del lock** —
        # se sollevasse, un `except` che lo inghiotte lo renderebbe silenziosamente fail-OPEN.
        # Lasciandolo propagare, un gate difettoso è visibile (fail-closed-friendly), non nascosto.
        if self._on_status_change:
            self._on_status_change(status)
