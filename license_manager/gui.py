"""License Manager — **mini-GUI** del proprietario (issue #140, PR 3b).

Tool separato dal bridge (package `license_manager`, mai nell'EXE del bridge — invariante #1). La
GUI riusa **solo** `license_manager.core`:

1. al primo avvio **genera la keypair** Ed25519 e ne **mostra la chiave PUBBLICA** (da incollare in
   `xtrader_bridge/licensing/license.py`); il **seed PRIVATO** resta in
   `%APPDATA%\\XTraderLicenseManager\\signing_key.json`, mai nel repo/EXE;
2. per emettere una licenza: **Nome, Cognome, Giorni** + **Hardware ID** dell'utente → **chiave
   firmata** (token) da inviare all'utente;
3. **Backup** del file-chiave su un percorso a scelta.

Come per la GUI del bridge, il **cablaggio Tk** è best-effort (verifica manuale su Windows), mentre
gli **handler puri** (`_ensure_keypair`, `_evaluate_issue`, `_evaluate_export`) sono scritti per
essere esercitabili **headless** su un `self` finto (stesso pattern dei meta-test GUI del repo).

NB: questo modulo importa `customtkinter` → NON è importato da `license_manager/__init__.py`, così
`import license_manager` (e i test della logica pura) restano headless (come `app` per il bridge).
"""

from __future__ import annotations

import logging
import time as _time

import customtkinter as ctk

from license_manager import core, registry

_log = logging.getLogger(__name__)

_MONO = ("Consolas", "Courier New", "monospace")


class LicenseManagerApp(ctk.CTk):
    """Finestra del License Manager. Dipendenze iniettate (testabilità + disaccoppiamento):

        key_dir:          str | None    — cartella del file-chiave (None = `core.manager_dir()`).
        now_provider:     () -> int      — unix seconds UTC correnti.
        generate_keypair: () -> (seed_hex, public_hex).
        load_key:         (path) -> dict | None   — solleva `KeyFileCorruptError` se corrotto.
        save_key:         (path, seed, public, now) -> None.
        export_key:       (src, dest) -> None.
        issue_license:    (seed, nome, giorni, hardware_id, now) -> token.
        record_issued:    (record, *, directory) -> record   — append al registro licenze.
        read_records:     (*, directory) -> list             — lettura del registro licenze.
    """

    def __init__(self, master=None, *, key_dir=None, now_provider=None,
                 generate_keypair=None, load_key=None, save_key=None,
                 export_key=None, issue_license=None,
                 record_issued=None, read_records=None):
        super().__init__()
        self._key_dir = key_dir
        self._now = now_provider or (lambda: int(_time.time()))
        self._generate_keypair = generate_keypair or core.generate_keypair
        self._load_key = load_key or core.load_signing_key
        self._save_key = save_key or core.save_signing_key
        self._export_key = export_key or core.export_signing_key
        self._issue_license = issue_license or core.issue_license
        # Registro licenze emesse (opzione A): append + lettura, iniettabili per i test.
        self._record_issued = record_issued or registry.append_record
        self._read_records = read_records or registry.read_records
        # widget refs (popolati da _build_ui)
        self._public_value = None
        self._nome_entry = None
        self._cognome_entry = None
        self._giorni_entry = None
        self._hwid_entry = None
        self._token_box = None
        self._msg_lbl = None
        self._reg_query_entry = None
        self._registry_box = None
        self.title("XTrader License Manager")
        # Esito della blindatura della cartella-chiave: se `False`, `_refresh_key_state` avvisa
        # l'utente invece di lasciarlo con un falso senso di sicurezza (review GPT/GLM #147).
        self._dir_secured = self._secure_data_dir()
        self._build_ui()
        self._refresh_key_state()

    # ── logica pura (testabile headless su self finto) ─────────────────────────────────────────
    def _secure_data_dir(self) -> bool:
        """Crea e **restringe** la cartella-dati del tool all'avvio (issue #140 PR 3c, rilievo Fugu
        #146): `0o700` su POSIX / ACL solo-owner su Windows, così il seed privato non è leggibile da
        altri account locali. Best-effort — `core.ensure_secure_dir` non solleva.

        Ritorna `True` se la cartella è stata creata **e** ristretta con successo, `False` altrimenti
        (review GPT/GLM #147): l'avvio usa l'esito per avvisare l'utente se la blindatura è fallita."""
        return core.ensure_secure_dir(self._key_dir)

    def _key_path(self) -> str:
        """Percorso del file-chiave (nella cartella iniettata o in `core.manager_dir()`)."""
        return core.signing_key_path(self._key_dir)

    def _current_key_state(self) -> dict:
        """Stato del file-chiave: ``{"public": hex|None, "error": str|None}``.

        Assente → `public=None, error=None`. **Corrotto → error** (mai `None` silenzioso: non si
        rigenera sopra un file forse recuperabile)."""
        try:
            key = self._load_key(self._key_path())
        except core.KeyFileCorruptError:
            return {"public": None,
                    "error": "Il file-chiave è corrotto: non verrà sovrascritto. Ripristina un "
                             "backup o rimuovilo a mano prima di rigenerare."}
        except OSError as exc:
            # File-chiave illeggibile (permessi/lock su %APPDATA%): fail-SAFE per non far crashare
            # la GUI all'avvio (review GLM #146) e per NON rigenerare sopra una chiave che potrebbe
            # esistere ma non è leggibile ora.
            _log.warning("File-chiave non leggibile: %s", type(exc).__name__)  # solo il tipo (CR #146)
            return {"public": None,
                    "error": "Impossibile leggere il file-chiave (permessi/percorso su %APPDATA%?)."}
        if key is None:
            return {"public": None, "error": None}
        return {"public": key.get("public"), "error": None}

    def _ensure_keypair(self) -> dict:
        """Assicura una keypair: se **assente**, la genera e la salva; se **presente**, la riusa; se
        **corrotta**, si ferma. Non sovrascrive mai una chiave esistente (rigenerarla invaliderebbe
        i bridge già distribuiti). Ritorna ``{"public", "created", "error"}``."""
        state = self._current_key_state()
        if state["error"] is not None:
            return {"public": None, "created": False, "error": state["error"]}
        if state["public"] is not None:
            return {"public": state["public"], "created": False, "error": None}
        # assente → genera + salva (no-overwrite atomico lato core)
        seed_hex, public_hex = self._generate_keypair()
        try:
            self._save_key(self._key_path(), seed_hex, public_hex, self._now())
        except core.KeyExistsError:
            # race: creata nel frattempo → riusa quella su disco
            again = self._current_key_state()
            return {"public": again["public"], "created": False, "error": again["error"]}
        except OSError as exc:
            _log.warning("Salvataggio keypair non riuscito: %s: %s", type(exc).__name__, exc)
            return {"public": None, "created": False,
                    "error": "Impossibile salvare la chiave su disco (permessi/percorso?)."}
        return {"public": public_hex, "created": True, "error": None}

    def _evaluate_issue(self, nome, cognome, giorni_str, hardware_id) -> dict:
        """Valida gli input ed **emette** la licenza firmata. Fail-closed: senza chiave, o con dati
        non validi, non emette nulla. Ritorna ``{"accepted", "token", "message"}``."""
        try:
            key = self._load_key(self._key_path())
        except core.KeyFileCorruptError:
            return {"accepted": False, "token": "",
                    "message": "File-chiave corrotto: ripristina un backup o rigenera."}
        except OSError as exc:
            _log.warning("File-chiave non leggibile in emissione: %s", type(exc).__name__)  # solo tipo
            return {"accepted": False, "token": "",
                    "message": "Impossibile leggere il file-chiave (permessi/percorso?)."}
        if key is None:
            return {"accepted": False, "token": "",
                    "message": "Nessuna chiave: genera prima la keypair."}
        try:
            giorni = int(str(giorni_str).strip())
        except (TypeError, ValueError):
            return {"accepted": False, "token": "",
                    "message": "I giorni devono essere un numero intero."}
        nome_completo = " ".join(p for p in (str(nome).strip(), str(cognome).strip()) if p)
        try:
            token = self._issue_license(key["seed"], nome_completo, giorni,
                                        str(hardware_id).strip(), self._now())
        except ValueError as exc:
            return {"accepted": False, "token": "", "message": str(exc)}
        recorded = self._record_issued_safe(token)
        suffix = "" if recorded else (" ⚠️ registro NON aggiornato (permessi/percorso della "
                                      "cartella?): il token è comunque valido, salvalo a mano.")
        return {"accepted": True, "token": token,
                "message": f"Chiave generata per «{nome_completo}» · {giorni} giorni. "
                           f"Inviala all'utente.{suffix}"}

    def _record_issued_safe(self, token) -> bool:
        """Registra la licenza appena emessa nel **registro locale** (opzione A), best-effort.

        Un fallimento (registro non scrivibile, token non interpretabile) **non** blocca l'emissione:
        il token è già firmato e va consegnato all'utente comunque; si logga solo il tipo eccezione.
        Ritorna `True` se il record è stato scritto."""
        try:
            record = registry.record_from_token(token, now=self._now())
            self._record_issued(record, directory=self._key_dir)
            return True
        except (OSError, ValueError) as exc:
            # Tipo eccezione + path del registro per diagnosticare, MA non il messaggio grezzo
            # `str(exc)` (review GLM/GPT-5.5 #152): un provider custom potrebbe includervi dati; il
            # path è sufficiente a capire cosa non è stato scritto, senza rischiare leak dal messaggio.
            _log.warning("Registrazione licenza nel registro non riuscita [%s] (dir=%s)",
                         type(exc).__name__, registry.registry_path(self._key_dir))
            return False

    def _registry_view(self, query: str = "") -> list:
        """Righe del **registro licenze** filtrate per `query` (sola lettura, headless-testabile).
        Fail-safe: se la lettura del registro fallisce, `read_records` ritorna `[]` (nessun crash)."""
        records = self._read_records(directory=self._key_dir)
        return registry.view_rows(records, query=str(query or ""), now=self._now())

    @staticmethod
    def _format_registry_rows(rows: list) -> str:
        """Rende le righe del registro come testo leggibile per la vista. **Non** mostra mai il
        token di attivazione (già escluso da `view_rows`). Vuoto = messaggio esplicito."""
        if not rows:
            return "(nessuna licenza registrata)"
        lines = []
        for r in rows:
            exp = r.get("expiry")
            exp_str = _time.strftime("%Y-%m-%d", _time.gmtime(exp)) if isinstance(exp, int) else "?"
            lines.append(
                f"{r['status']:8} · {r['serial']} · {r['name']} · HW {r['hardware_id']} · "
                f"{r['days_left']}g rimasti · scad. {exp_str}")
        return "\n".join(lines)

    def _evaluate_export(self, dest_path) -> dict:
        """**Backup** del file-chiave in `dest_path`. Ritorna ``{"ok", "message"}``."""
        dest = str(dest_path or "").strip()
        if not dest:
            return {"ok": False, "message": "Scegli un percorso di destinazione per il backup."}
        try:
            self._export_key(self._key_path(), dest)
        except FileNotFoundError:
            return {"ok": False, "message": "Nessuna chiave da esportare: genera prima la keypair."}
        except core.KeyExistsError:
            return {"ok": False, "message": "Esiste già un backup in quel percorso: scegline un altro."}
        except (core.KeyFileCorruptError, OSError) as exc:
            _log.warning("Backup chiave non riuscito: %s: %s", type(exc).__name__, exc)
            return {"ok": False, "message": "Backup non riuscito (chiave corrotta o percorso non scrivibile)."}
        return {"ok": True, "message": f"Backup salvato in: {dest}"}

    # ── cablaggio Tk (verifica manuale su Windows) ─────────────────────────────────────────────
    def _build_ui(self) -> None:
        ctk.CTkLabel(self, text="🔐 XTrader License Manager",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(
                         fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(self, text="Tool del proprietario — genera le chiavi di attivazione. "
                     "La chiave PRIVATA resta solo su questo PC.",
                     anchor="w").pack(fill="x", padx=12, pady=(0, 8))

        # Chiave pubblica (da incollare nel bridge)
        ctk.CTkLabel(self, text="Chiave pubblica (incollala in xtrader_bridge/licensing/license.py):",
                     anchor="w").pack(fill="x", padx=12, pady=(6, 2))
        self._public_value = ctk.CTkLabel(self, text="—", anchor="w", wraplength=560,
                                          font=ctk.CTkFont(family=_MONO[0], size=12))
        self._public_value.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(self, text="🔑 Genera / mostra keypair", command=self._on_generate).pack(
            anchor="w", padx=12, pady=(0, 10))

        # Emissione licenza
        ctk.CTkLabel(self, text="Emetti una licenza:", font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(6, 2))
        self._nome_entry = ctk.CTkEntry(self, placeholder_text="Nome")
        self._nome_entry.pack(fill="x", padx=12, pady=2)
        self._cognome_entry = ctk.CTkEntry(self, placeholder_text="Cognome")
        self._cognome_entry.pack(fill="x", padx=12, pady=2)
        self._giorni_entry = ctk.CTkEntry(self, placeholder_text="Giorni (es. 15)")
        self._giorni_entry.pack(fill="x", padx=12, pady=2)
        self._hwid_entry = ctk.CTkEntry(self, placeholder_text="Hardware ID dell'utente (HW1-…)")
        self._hwid_entry.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(self, text="✅ Genera chiave di attivazione", command=self._on_issue).pack(
            anchor="w", padx=12, pady=(6, 6))

        # Token risultante
        self._token_box = ctk.CTkTextbox(self, height=70)
        self._token_box.pack(fill="x", padx=12, pady=(0, 6))

        # Registro licenze emesse (opzione A): elenco + ricerca (sola lettura, nessun token mostrato)
        ctk.CTkLabel(self, text="Registro licenze emesse:", font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        self._reg_query_entry = ctk.CTkEntry(self, placeholder_text="Cerca (nome / hardware ID / serial)")
        self._reg_query_entry.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(self, text="🔍 Cerca / 🔄 Aggiorna", command=self._on_registry_refresh).pack(
            anchor="w", padx=12, pady=(4, 4))
        self._registry_box = ctk.CTkTextbox(self, height=120)
        self._registry_box.pack(fill="x", padx=12, pady=(0, 6))

        # Backup + messaggi
        ctk.CTkButton(self, text="💾 Backup della chiave privata", command=self._on_export).pack(
            anchor="w", padx=12, pady=(0, 6))
        self._msg_lbl = ctk.CTkLabel(self, text="", anchor="w")
        self._msg_lbl.pack(fill="x", padx=12, pady=(2, 12))

    def _set_msg(self, text: str) -> None:
        """Aggiorna la riga messaggi (best-effort: un widget assente/headless non rompe l'handler)."""
        try:
            if self._msg_lbl is not None:
                self._msg_lbl.configure(text=text)
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass

    def _refresh_key_state(self) -> None:
        """Mostra la chiave pubblica corrente (o «nessuna chiave»). Non genera nulla."""
        state = self._current_key_state()
        try:
            if self._public_value is not None:
                self._public_value.configure(text=state["public"] or "— (nessuna chiave: premi «Genera»)")
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass
        if state["error"]:
            self._set_msg(state["error"])
        elif not getattr(self, "_dir_secured", True):
            # Nessun errore di chiave, ma la cartella-dati non è stata blindata: avvisa invece di
            # dare un falso senso di sicurezza (review GPT/GLM #147).
            self._set_msg("⚠️ Attenzione: non è stato possibile proteggere la cartella-chiave "
                          "(permessi/ACL). Su un PC condiviso il seed privato potrebbe essere "
                          "leggibile da altri account: controlla i permessi della cartella.")

    def _on_generate(self) -> None:
        result = self._ensure_keypair()
        try:
            if self._public_value is not None:
                self._public_value.configure(text=result["public"] or "—")
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass
        if result["error"]:
            self._set_msg(result["error"])
        elif result["created"]:
            self._set_msg("Nuova keypair generata e salvata. Incolla la pubblica nel bridge.")
        else:
            self._set_msg("Keypair già presente.")

    def _read(self, entry) -> str:
        """Legge un CTkEntry (best-effort: ritorna '' se il widget non c'è)."""
        try:
            return entry.get() if entry is not None else ""
        except Exception:       # noqa: BLE001 — lettura Tk best-effort
            return ""

    def _on_issue(self) -> None:
        result = self._evaluate_issue(self._read(self._nome_entry), self._read(self._cognome_entry),
                                      self._read(self._giorni_entry), self._read(self._hwid_entry))
        try:
            if self._token_box is not None:
                self._token_box.delete("1.0", "end")
                if result["token"]:
                    self._token_box.insert("1.0", result["token"])
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass
        self._set_msg(result["message"])
        # Aggiorna la vista del registro così la licenza appena emessa compare subito.
        self._on_registry_refresh()

    def _on_registry_refresh(self) -> None:
        """Ricarica e mostra il registro licenze, filtrato per il testo di ricerca.

        **Interamente best-effort** (review GPT-5.5 #152): gira anche subito dopo l'emissione, quindi
        né il fetch (`_registry_view`→`read_records`) né il rendering Tk devono mai far fallire
        l'azione. Il `read_records` di default è già fail-safe; questo guard copre anche un provider
        iniettato/custom che non rispettasse il contratto."""
        try:
            rows = self._registry_view(self._read(self._reg_query_entry))
            text = self._format_registry_rows(rows)
            if self._registry_box is not None:
                self._registry_box.delete("1.0", "end")
                self._registry_box.insert("1.0", text)
        except Exception as exc:       # noqa: BLE001 — vista registro best-effort (fetch + render)
            # Non silenzioso (review GLM/GPT-5.5 #152): un errore soppresso resta visibile a livello
            # DEBUG per diagnosi, senza far fallire l'azione (che gira anche dopo l'emissione).
            _log.debug("Refresh registro non riuscito [%s]", type(exc).__name__)

    def _on_export(self) -> None:
        # Il percorso reale lo sceglie un file-dialog (Tk, verifica manuale); headless resta '' → messaggio.
        dest = ""
        try:
            from tkinter import filedialog
            dest = filedialog.asksaveasfilename(
                title="Backup chiave privata", defaultextension=".json",
                initialfile="signing_key_backup.json")
        except Exception:       # noqa: BLE001 — dialog Tk best-effort
            dest = ""
        result = self._evaluate_export(dest)
        self._set_msg(result["message"])
