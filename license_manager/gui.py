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
import os
import threading
import time as _time

import customtkinter as ctk

from license_manager import core, publish_store, publisher, registry
from xtrader_bridge.licensing import revocation

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
                 record_issued=None, read_records=None,
                 record_revocation=None, read_revocations=None,
                 load_publish_config=None, save_publish_config=None,
                 load_publish_token=None, save_publish_token=None, publish_upload=None):
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
        # Store revoche (R3b): append + lettura, iniettabili per i test.
        self._record_revocation = record_revocation or registry.append_revocation
        self._read_revocations = read_revocations or registry.read_revocations
        # Pubblicazione automatica (#157): impostazioni su disco, token nel keyring, upload HTTP —
        # tutti iniettabili, così i test girano senza keyring reale e senza socket.
        self._load_publish_config = load_publish_config or publish_store.load_publish_config
        self._save_publish_config = save_publish_config or publish_store.save_publish_config
        self._load_publish_token = load_publish_token or publish_store.load_publish_token
        self._save_publish_token = save_publish_token or publish_store.save_publish_token
        self._publish_upload = publish_upload or publisher.publish
        self._publish_after_id = None
        self._publish_inflight = False      # un solo upload alla volta (niente accavallamenti)
        self._closing = False
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
        self._renew_serial_entry = None
        self._renew_giorni_entry = None
        self.title("XTrader License Manager")
        # Esito della blindatura della cartella-chiave: se `False`, `_refresh_key_state` avvisa
        # l'utente invece di lasciarlo con un falso senso di sicurezza (review GPT/GLM #147).
        self._dir_secured = self._secure_data_dir()
        self._build_ui()
        self._refresh_key_state()
        # Pubblicazione automatica (#157): arma il tick (ri-pubblica alla cadenza configurata se
        # abilitata) e cablalo alla chiusura, così non resta un `after` su una finestra distrutta.
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:       # noqa: BLE001 — headless/senza window manager: best-effort
            pass
        self._schedule_publish_tick()

    def _on_close(self) -> None:
        """Chiusura finestra: annulla il tick di pubblicazione e distrugge la finestra."""
        self._closing = True
        self._cancel_publish_tick()
        try:
            self.destroy()
        except Exception:       # noqa: BLE001 — finestra già distrutta: best-effort
            pass

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

    def _load_key_or_error(self) -> tuple:
        """`(key, None)` se la chiave è leggibile, altrimenti `(None, error_result)` con lo shape
        `{"accepted", "token", "message"}` fail-closed (chiave corrotta/illeggibile/assente)."""
        try:
            key = self._load_key(self._key_path())
        except core.KeyFileCorruptError:
            return None, {"accepted": False, "token": "",
                          "message": "File-chiave corrotto: ripristina un backup o rigenera."}
        except OSError as exc:
            _log.warning("File-chiave non leggibile in emissione: %s", type(exc).__name__)  # solo tipo
            return None, {"accepted": False, "token": "",
                          "message": "Impossibile leggere il file-chiave (permessi/percorso?)."}
        if key is None:
            return None, {"accepted": False, "token": "",
                          "message": "Nessuna chiave: genera prima la keypair."}
        return key, None

    @staticmethod
    def _parse_days(giorni_str) -> tuple:
        """`(giorni, None)` se `giorni_str` è un intero, altrimenti `(None, error_result)`."""
        try:
            return int(str(giorni_str).strip()), None
        except (TypeError, ValueError):
            return None, {"accepted": False, "token": "",
                          "message": "I giorni devono essere un numero intero."}

    def _sign_and_record(self, nome_completo, giorni, hardware_id, *, seed, verb="generata") -> dict:
        """Firma la licenza (fail-closed sulle validazioni di `issue_license`) e la **registra**
        (best-effort). Riusato da emissione e rinnovo. `verb` = «generata»/«rinnovata» nel messaggio."""
        try:
            token = self._issue_license(seed, nome_completo, giorni,
                                        str(hardware_id).strip(), self._now())
        except ValueError as exc:
            return {"accepted": False, "token": "", "message": str(exc)}
        recorded = self._record_issued_safe(token)
        suffix = "" if recorded else (" ⚠️ registro NON aggiornato (permessi/percorso della "
                                      "cartella?): il token è comunque valido, salvalo a mano.")
        return {"accepted": True, "token": token,
                "message": f"Chiave {verb} per «{nome_completo}» · {giorni} giorni. "
                           f"Inviala all'utente.{suffix}"}

    def _evaluate_issue(self, nome, cognome, giorni_str, hardware_id) -> dict:
        """Valida gli input ed **emette** la licenza firmata. Fail-closed: senza chiave, o con dati
        non validi, non emette nulla. Ritorna ``{"accepted", "token", "message"}``."""
        key, err = self._load_key_or_error()
        if err is not None:
            return err
        giorni, gerr = self._parse_days(giorni_str)
        if gerr is not None:
            return gerr
        nome_completo = " ".join(p for p in (str(nome).strip(), str(cognome).strip()) if p)
        return self._sign_and_record(nome_completo, giorni, hardware_id, seed=key["seed"])

    def _evaluate_renew(self, serial, giorni_str) -> dict:
        """**Rinnovo/ri-emissione** (opzione B): ri-emette una licenza identificata dal `serial`, per
        lo STESSO nome + hardware ID del record, con **nuovi giorni** → nuovo token (nuovo serial; il
        record vecchio resta nello storico). Fail-closed se il serial non è nel registro."""
        rec = registry.find_by_serial(self._read_records(directory=self._key_dir), serial)
        if rec is None:
            return {"accepted": False, "token": "",
                    "message": f"Serial non trovato nel registro: {str(serial).strip()}"}
        key, err = self._load_key_or_error()
        if err is not None:
            return err
        giorni, gerr = self._parse_days(giorni_str)
        if gerr is not None:
            return gerr
        return self._sign_and_record(str(rec.get("name", "")), giorni,
                                     str(rec.get("hardware_id", "")), seed=key["seed"],
                                     verb="rinnovata")

    def _evaluate_resend(self, serial) -> dict:
        """**Ri-mostra** il token già emesso per un `serial` (per rinviarlo all'utente). Sola lettura:
        non firma nulla di nuovo. Ritorna ``{"found", "token", "message"}``.

        Nota (review Sourcery #153): lo shape usa `found` (non `accepted` come emissione/rinnovo) **di
        proposito** — qui non si «emette/accetta» nulla, si **ritrova** un token esistente. L'handler
        GUI (`_on_resend`) usa solo `token`/`message`, quindi la divergenza non complica i chiamanti."""
        rec = registry.find_by_serial(self._read_records(directory=self._key_dir), serial)
        if rec is None:
            return {"found": False, "token": "",
                    "message": f"Serial non trovato nel registro: {str(serial).strip()}"}
        token = str(rec.get("token") or "")
        if not token:
            return {"found": True, "token": "",
                    "message": "Il record non contiene il token (registro vecchio?): ri-emetti con «Rinnova»."}
        return {"found": True, "token": token,
                "message": f"Token di «{rec.get('name', '')}» ({rec.get('serial', '')}). Rinvialo all'utente."}

    def _evaluate_revoke(self, serial) -> dict:
        """**Revoca** (R3b) la licenza identificata dal `serial`: la registra nello store revoche, così
        la lista firmata prodotta con «📤 Esporta lista revoche» la bloccherà sul bridge.

        Fail-closed: serial non nel registro → **niente scrittura**; serial già revocato → messaggio,
        nessun duplicato. Ritorna ``{"accepted", "message"}``. La revoca è **per serial** (reversibile:
        emetti una nuova licenza → serial nuovo, non revocato)."""
        rec = registry.find_by_serial(self._read_records(directory=self._key_dir), serial)
        if rec is None:
            return {"accepted": False,
                    "message": f"Serial non trovato nel registro: {str(serial).strip()}"}
        if registry.is_serial_revoked(self._read_revocations(directory=self._key_dir),
                                      rec.get("serial", "")):
            return {"accepted": False,
                    "message": f"Licenza già revocata: {rec.get('serial', '')} ({rec.get('name', '')})."}
        recorded = self._record_revocation_safe(rec)
        if not recorded:
            return {"accepted": False,
                    "message": "Revoca NON registrata (permessi/percorso della cartella?): riprova."}
        return {"accepted": True,
                "message": f"Licenza revocata: {rec.get('serial', '')} ({rec.get('name', '')}). "
                           "Esporta e ripubblica la lista revoche per applicarla ai bridge."}

    def _record_revocation_safe(self, rec) -> bool:
        """Registra una revoca nello store (R3b), best-effort. Un fallimento (store non scrivibile,
        record senza serial) **non** solleva: si logga solo il tipo eccezione + il path. Ritorna
        `True` se la revoca è stata scritta."""
        try:
            record = registry.revocation_record(rec, now=self._now())
            self._record_revocation(record, directory=self._key_dir)
            return True
        except (OSError, ValueError) as exc:
            _log.warning("Registrazione revoca non riuscita [%s] (dir=%s)",
                         type(exc).__name__, registry.revoked_registry_path(self._key_dir))
            return False

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

    def _build_signed_revocation_list(self) -> tuple:
        """`(signed, n_revoche, errore)` — la **lista di revoche firmata** con il seed privato, dalle
        entry dello store revoche. Sorgente UNICA sia per l'esportazione su file (📤) sia per la
        pubblicazione automatica su GitHub (#157), così le due strade non possono divergere.

        `(None, 0, messaggio)` se la chiave manca/è corrotta o la firma fallisce (fail-closed). Uno
        store **vuoto** produce comunque una lista firmata **valida** («niente revocato»), che è
        esattamente ciò che serve per tenere l'URL sempre popolato e fresco."""
        key, err = self._load_key_or_error()
        if err is not None:
            return None, 0, err["message"]
        entries = registry.revocation_entries(self._read_revocations(directory=self._key_dir))
        try:
            seed = bytes.fromhex(str(key["seed"]))
            signed = revocation.build_revocation_list(seed, entries, now=self._now())
        except (ValueError, KeyError, TypeError) as exc:
            _log.warning("Firma lista revoche non riuscita: %s", type(exc).__name__)  # solo il tipo
            return None, 0, "Firma non riuscita (chiave non valida?)."
        return signed, len(entries), None

    def _evaluate_publish_revocation(self, dest_path) -> dict:
        """Produce la **lista di revoche firmata** (R3b) in `dest_path`: la firma con il seed privato
        (`revocation.build_revocation_list`) sulle entry dello store revoche. È il file che il
        proprietario **carica sull'URL statico**; il bridge lo scarica e lo verifica (R3c).

        Fail-closed: senza percorso o senza chiave non produce nulla. Uno store **vuoto** dà comunque
        una lista firmata **valida** (stato «niente revocato», così l'URL esiste sempre). Ritorna
        ``{"ok", "message"}``."""
        dest = str(dest_path or "").strip()
        if not dest:
            return {"ok": False, "message": "Scegli un percorso per la lista revoche firmata."}
        signed, count, err_msg = self._build_signed_revocation_list()
        if err_msg is not None:
            return {"ok": False, "message": err_msg}
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(signed + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            _log.warning("Scrittura lista revoche non riuscita: %s", type(exc).__name__)
            return {"ok": False, "message": "Scrittura non riuscita (percorso non scrivibile?)."}
        return {"ok": True,
                "message": f"Lista revoche firmata ({count} revoc.) salvata in: {dest}. "
                           "Caricala sull'URL statico che il bridge controlla."}

    # ── PUBBLICAZIONE AUTOMATICA su GitHub (#157) ──────────────────────────────────────────────
    # Il bridge accetta solo liste firmate DI RECENTE (finestra `MAX_LIST_AGE_S`): oltre quel tetto i
    # bridge legittimi si bloccano fail-closed. Qui il tool ri-firma e ri-carica da solo, così non
    # serve ricordarsene. Il **token** sta SOLO nel keyring; le impostazioni (repo/path/branch/
    # intervallo) su disco, mai segreti. Il **seed privato non lascia questo PC**: la firma avviene
    # qui e su GitHub va solo il file già firmato.
    def _evaluate_save_publish_settings(self, repo, path, branch, interval_str, enabled,
                                        token="") -> dict:
        """Valida e salva le impostazioni di pubblicazione (+ eventuale token nel keyring).

        Ritorna ``{"ok", "message", "config"}``. Fail-closed: impostazioni non valide → non si salva
        nulla. Un `token` non vuoto va nel **keyring** (mai su disco); un token vuoto **non cancella**
        quello già salvato (evita di perderlo lasciando il campo vuoto per comodità)."""
        cfg = publish_store.normalize_config({
            "enabled": bool(enabled), "repo": repo, "path": path, "branch": branch,
            "interval_hours": interval_str,
        })
        problema = publish_store.validate_config(cfg)
        if problema is not None:
            return {"ok": False, "message": problema, "config": cfg}
        note = ""
        tok = str(token or "").strip()
        if tok:
            if not self._save_publish_token(tok):
                return {"ok": False, "config": cfg,
                        "message": ("Keyring non disponibile: il token NON è stato salvato "
                                    "(non lo scriviamo mai in chiaro su disco). Impostazioni non salvate.")}
            note = " Token salvato nel keyring."
        elif cfg["enabled"] and not self._load_publish_token():
            return {"ok": False, "config": cfg,
                    "message": "Manca il token: incollalo nel campo per abilitare la pubblicazione."}
        try:
            self._save_publish_config(cfg, directory=self._key_dir)
        except OSError as exc:
            _log.warning("Salvataggio impostazioni pubblicazione non riuscito: %s", type(exc).__name__)
            return {"ok": False, "config": cfg,
                    "message": "Impostazioni non salvate (cartella non scrivibile?)."}
        stato = "attiva" if cfg["enabled"] else "disattivata"
        return {"ok": True, "config": cfg,
                "message": (f"Impostazioni salvate · pubblicazione automatica {stato} "
                            f"(ogni {cfg['interval_hours']}h).{note}")}

    def _evaluate_publish_now(self) -> dict:
        """Ri-firma la lista di revoche e la **carica** su GitHub adesso. Ritorna ``{"ok","message"}``.

        Fail-safe: nessuna eccezione verso la GUI; il **token non compare mai** nei messaggi."""
        cfg = self._load_publish_config(directory=self._key_dir)
        problema = publish_store.validate_config(cfg)
        if problema is not None:
            return {"ok": False, "message": problema}
        token = self._load_publish_token()
        if not token:
            return {"ok": False,
                    "message": "Token assente nel keyring: salvalo nelle impostazioni di pubblicazione."}
        signed, count, err_msg = self._build_signed_revocation_list()
        if err_msg is not None:
            return {"ok": False, "message": err_msg}
        result = self._publish_upload(
            signed + "\n", repo=cfg["repo"], path=cfg["path"], branch=cfg["branch"], token=token,
            message=f"XTrader: lista revoche ({count} revoc.)")
        if not result.get("ok"):
            return {"ok": False, "message": str(result.get("message", "Pubblicazione non riuscita."))}
        return {"ok": True,
                "message": (f"{result.get('message', '')} "
                            f"URL per il bridge: {publisher.raw_url(cfg['repo'], cfg['path'], cfg['branch'])}")}

    # La pubblicazione fa **rete** (GET+PUT, fino a `DEFAULT_TIMEOUT_S` ciascuna): eseguirla sul
    # thread Tk **congelerebbe la finestra** con GitHub lento o irraggiungibile (rilievo GPT-5.5
    # #158). Perciò la parte lenta gira su un **thread daemon** e l'esito rientra sul thread GUI via
    # `after`. Un solo upload alla volta (`_publish_inflight`): un click ripetuto o un tick che cade
    # durante una pubblicazione in corso non ne accavalla una seconda.
    def _spawn_publish_thread(self, target) -> None:
        """Avvia il worker di pubblicazione (iniettabile nei test: eseguono `target()` inline)."""
        threading.Thread(target=target, daemon=True, name="revocation-publish").start()

    def _publish_lock(self):
        """Il lucchetto che protegge `_publish_inflight`, creato pigramente se assente.

        `_publish_inflight` è letto/scritto dal **thread GUI** (avvio, esito) e dal **worker** (ramo
        di fallback a finestra distrutta): il check-and-set va fatto **atomico** con un `Lock`, non
        affidato al GIL (rilievo GLM/GPT-5.5 #158). Così due click ravvicinati — o un tick che cade
        mentre l'utente clicca — non possono mai avviare due upload."""
        lock = self.__dict__.get("_publish_lock_obj")
        if lock is None:
            lock = self._publish_lock_obj = threading.Lock()
        return lock

    def _set_publish_inflight(self, value: bool) -> None:
        """Scrive `_publish_inflight` sotto lucchetto (rilascio dell'upload)."""
        with self._publish_lock():
            self._publish_inflight = bool(value)

    def _publish_async(self) -> bool:
        """Avvia una pubblicazione in background. `True` se avviata, `False` se ce n'è già una in
        corso (nessun accavallamento). Il **check-and-set è atomico** sotto lucchetto."""
        with self._publish_lock():
            if self.__dict__.get("_publish_inflight"):
                return False
            self._publish_inflight = True
        try:
            self._spawn_publish_thread(self._publish_worker)
        except Exception as exc:    # noqa: BLE001 — thread non avviabile: libera il flag e segnala
            self._set_publish_inflight(False)
            _log.warning("Avvio thread pubblicazione non riuscito [%s]", type(exc).__name__)
            return False
        return True

    def _publish_worker(self) -> None:
        """Corpo del thread: fa la parte lenta (firma + rete) FUORI dal thread Tk e rimanda l'esito
        alla GUI. Non solleva mai: un errore imprevisto diventa un esito negativo."""
        try:
            result = self._evaluate_publish_now()
        except Exception as exc:    # noqa: BLE001 — il thread non deve morire in silenzio
            _log.warning("Pubblicazione in background non riuscita [%s]", type(exc).__name__)
            result = {"ok": False, "message": "Pubblicazione non riuscita (errore imprevisto)."}
        try:
            self.after(0, lambda: self._publish_finish(result))
        except Exception:       # noqa: BLE001 — finestra distrutta: nessuna UI da aggiornare
            self._set_publish_inflight(False)

    def _publish_finish(self, result) -> None:
        """Applica l'esito sul thread GUI e libera il lucchetto."""
        self._set_publish_inflight(False)
        self._set_msg(("✅ " if (result or {}).get("ok") else "⚠️ ") + str((result or {}).get("message", "")))

    def _publish_tick(self) -> None:
        """Tick della pubblicazione automatica: se abilitata avvia la pubblicazione **in background**
        e si **ri-arma** sempre (non aspetta l'esito della rete). Best-effort: un errore non deve
        fermare il ciclo né rompere la finestra."""
        self._publish_after_id = None
        try:
            cfg = self._load_publish_config(directory=self._key_dir)
            if cfg.get("enabled"):
                self._publish_async()
        except Exception as exc:    # noqa: BLE001 — il ciclo non deve morire per un errore imprevisto
            _log.warning("Tick pubblicazione non riuscito [%s]", type(exc).__name__)
        self._schedule_publish_tick()

    def _schedule_publish_tick(self) -> None:
        """(Ri)programma il tick alla cadenza configurata. Non riprogramma in chiusura; `after` è
        best-effort (finestra distrutta → nessun ri-arm)."""
        if self.__dict__.get("_closing"):
            return
        # La lettura della cadenza è essa stessa best-effort: se le impostazioni non sono leggibili
        # (disco/provider in errore) si ripiega sulla cadenza di default invece di far MORIRE il ciclo
        # — il tick deve ri-armarsi sempre.
        try:
            cfg = self._load_publish_config(directory=self._key_dir)
            hours = int(cfg.get("interval_hours") or publish_store.DEFAULTS["interval_hours"])
        except Exception:       # noqa: BLE001 — impostazioni illeggibili: cadenza di default
            hours = publish_store.DEFAULTS["interval_hours"]
        delay_ms = max(publish_store.MIN_INTERVAL_HOURS,
                       min(publish_store.MAX_INTERVAL_HOURS, hours)) * 3_600_000
        try:
            self._publish_after_id = self.after(delay_ms, self._publish_tick)
        except Exception:       # noqa: BLE001 — finestra distrutta/headless: niente ri-arm
            self._publish_after_id = None

    def _cancel_publish_tick(self) -> None:
        """Annulla il tick pendente (chiusura finestra): best-effort su id già scaduto."""
        after_id = self.__dict__.get("_publish_after_id")
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:   # noqa: BLE001 — id scaduto/invalido: ininfluente
                pass
            self._publish_after_id = None

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

        # Rinnovo / ri-emissione da serial (opzione B): riusa nome+hardware del record esistente
        ctk.CTkLabel(self, text="Rinnova / ri-mostra da serial (copia il serial dall'elenco):",
                     anchor="w").pack(fill="x", padx=12, pady=(6, 2))
        self._renew_serial_entry = ctk.CTkEntry(self, placeholder_text="Serial (LIC-…)")
        self._renew_serial_entry.pack(fill="x", padx=12, pady=2)
        self._renew_giorni_entry = ctk.CTkEntry(self, placeholder_text="Nuovi giorni per il rinnovo (es. 15)")
        self._renew_giorni_entry.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(self, text="🔄 Rinnova (nuovo token)", command=self._on_renew).pack(
            anchor="w", padx=12, pady=(4, 2))
        ctk.CTkButton(self, text="📋 Ri-mostra token esistente", command=self._on_resend).pack(
            anchor="w", padx=12, pady=(0, 2))
        ctk.CTkButton(self, text="🚫 Revoca licenza", command=self._on_revoke).pack(
            anchor="w", padx=12, pady=(0, 6))

        # Revoca online (R3b): esporta la lista firmata da caricare sull'URL statico che il bridge controlla
        ctk.CTkLabel(self, text="Revoca online — esporta la lista firmata da caricare sull'URL:",
                     anchor="w").pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkButton(self, text="📤 Esporta lista revoche firmata",
                      command=self._on_publish_revocation).pack(anchor="w", padx=12, pady=(0, 6))

        # Pubblicazione automatica su GitHub (#157): ri-firma e ri-carica da sola la lista, così la
        # finestra di freschezza del bridge non scade mai per dimenticanza.
        ctk.CTkLabel(self, text="📤 Pubblicazione automatica (GitHub):",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(self, text="Il repo dev'essere PUBBLICO (il bridge lo scarica senza credenziali). "
                                "Il token resta nel keyring di questo PC, mai su disco.",
                     anchor="w", wraplength=560).pack(fill="x", padx=12, pady=(0, 4))
        self._pub_repo_entry = ctk.CTkEntry(self, placeholder_text="Repository (owner/nome, es. tuonome/xtrader-revocation)")
        self._pub_repo_entry.pack(fill="x", padx=12, pady=2)
        self._pub_path_entry = ctk.CTkEntry(self, placeholder_text="File nel repo (es. revocation_list.txt)")
        self._pub_path_entry.pack(fill="x", padx=12, pady=2)
        self._pub_branch_entry = ctk.CTkEntry(self, placeholder_text="Branch (es. main)")
        self._pub_branch_entry.pack(fill="x", padx=12, pady=2)
        self._pub_interval_entry = ctk.CTkEntry(self, placeholder_text="Ogni quante ore (es. 12)")
        self._pub_interval_entry.pack(fill="x", padx=12, pady=2)
        self._pub_token_entry = ctk.CTkEntry(self, placeholder_text="Token GitHub (si salva nel keyring)",
                                             show="*")
        self._pub_token_entry.pack(fill="x", padx=12, pady=2)
        self._pub_enabled_var = ctk.StringVar(value="off")
        self._pub_enabled_check = ctk.CTkCheckBox(self, text="Pubblica automaticamente",
                                                  variable=self._pub_enabled_var,
                                                  onvalue="on", offvalue="off")
        self._pub_enabled_check.pack(anchor="w", padx=12, pady=(4, 2))
        ctk.CTkButton(self, text="💾 Salva impostazioni pubblicazione",
                      command=self._on_save_publish_settings).pack(anchor="w", padx=12, pady=(2, 2))
        ctk.CTkButton(self, text="🚀 Pubblica ora",
                      command=self._on_publish_now).pack(anchor="w", padx=12, pady=(0, 6))
        self._refresh_publish_fields()

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

    def _show_token(self, token: str) -> None:
        """Mostra un token nel box (best-effort headless)."""
        try:
            if self._token_box is not None:
                self._token_box.delete("1.0", "end")
                if token:
                    self._token_box.insert("1.0", token)
        except Exception:       # noqa: BLE001 — render Tk best-effort
            pass

    def _on_renew(self) -> None:
        """Rinnova (ri-emette) la licenza del serial indicato, con i nuovi giorni → nuovo token."""
        result = self._evaluate_renew(self._read(self._renew_serial_entry),
                                      self._read(self._renew_giorni_entry))
        self._show_token(result.get("token", ""))
        self._set_msg(result["message"])
        self._on_registry_refresh()

    def _on_resend(self) -> None:
        """Ri-mostra il token già emesso per il serial indicato (per rinviarlo all'utente)."""
        result = self._evaluate_resend(self._read(self._renew_serial_entry))
        self._show_token(result.get("token", ""))
        self._set_msg(result["message"])

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

    def _on_revoke(self) -> None:
        """Revoca (R3b) la licenza del serial indicato (stesso campo di rinnovo/ri-mostra)."""
        result = self._evaluate_revoke(self._read(self._renew_serial_entry))
        self._set_msg(result["message"])
        self._on_registry_refresh()

    def _refresh_publish_fields(self) -> None:
        """Precompila i campi della pubblicazione con le impostazioni salvate (best-effort headless).
        **Il token non viene mai ri-mostrato**: resta nel keyring, il campo parte vuoto."""
        try:
            cfg = self._load_publish_config(directory=self._key_dir)
            for entry, value in ((self.__dict__.get("_pub_repo_entry"), cfg["repo"]),
                                 (self.__dict__.get("_pub_path_entry"), cfg["path"]),
                                 (self.__dict__.get("_pub_branch_entry"), cfg["branch"]),
                                 (self.__dict__.get("_pub_interval_entry"), str(cfg["interval_hours"]))):
                if entry is not None:
                    entry.delete(0, "end")
                    entry.insert(0, str(value))
            var = self.__dict__.get("_pub_enabled_var")
            if var is not None:
                var.set("on" if cfg["enabled"] else "off")
        except Exception as exc:    # noqa: BLE001 — precompilazione best-effort (headless/widget assenti)
            _log.debug("Precompilazione campi pubblicazione non riuscita [%s]", type(exc).__name__)

    def _on_save_publish_settings(self) -> None:
        """Salva le impostazioni di pubblicazione e ri-programma il tick con la nuova cadenza."""
        var = self.__dict__.get("_pub_enabled_var")
        enabled = (var.get() == "on") if var is not None else False
        result = self._evaluate_save_publish_settings(
            self._read(self.__dict__.get("_pub_repo_entry")),
            self._read(self.__dict__.get("_pub_path_entry")),
            self._read(self.__dict__.get("_pub_branch_entry")),
            self._read(self.__dict__.get("_pub_interval_entry")),
            enabled,
            token=self._read(self.__dict__.get("_pub_token_entry")))
        # Il campo token si svuota SEMPRE dopo il salvataggio: non resta a schermo né in memoria del
        # widget (è già nel keyring se il salvataggio è riuscito).
        try:
            entry = self.__dict__.get("_pub_token_entry")
            if entry is not None:
                entry.delete(0, "end")
        except Exception:       # noqa: BLE001 — widget headless/distrutto: best-effort
            pass
        self._set_msg(result["message"])
        if result.get("ok"):
            self._cancel_publish_tick()
            self._schedule_publish_tick()

    def _on_publish_now(self) -> None:
        """Pubblica adesso la lista firmata su GitHub, **in background** (la finestra non si congela
        se la rete è lenta). L'esito compare nella riga messaggi quando la chiamata termina."""
        if self._publish_async():
            self._set_msg("⏳ Pubblicazione in corso…")
        else:
            self._set_msg("⏳ Una pubblicazione è già in corso: attendi l'esito.")

    def _on_publish_revocation(self) -> None:
        # Il percorso reale lo sceglie un file-dialog (Tk, verifica manuale); headless resta '' → messaggio.
        dest = ""
        try:
            from tkinter import filedialog
            dest = filedialog.asksaveasfilename(
                title="Esporta lista revoche firmata", defaultextension=".txt",
                initialfile="revocation_list.txt")
        except Exception:       # noqa: BLE001 — dialog Tk best-effort
            dest = ""
        result = self._evaluate_publish_revocation(dest)
        self._set_msg(result["message"])
