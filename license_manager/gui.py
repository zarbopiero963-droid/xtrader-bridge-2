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

from xtrader_bridge import ui_theme

from license_manager import backup as backup_mod
from license_manager import core, publish_store, publisher, registry
from xtrader_bridge.licensing import revocation

_log = logging.getLogger(__name__)

_MONO = ("Consolas", "Courier New", "monospace")

# Pubblicazione automatica (#157). All'avvio si pubblica SUBITO (catch-up): se il PC è rimasto spento
# oltre la finestra di freschezza del bridge, la lista è già scaduta e i bridge sono bloccati —
# aspettare l'intero intervallo li terrebbe bloccati per ore (rilievo Fugu #158). Il ritardo è solo
# quel poco che serve alla finestra per finire di costruirsi.
_PUBLISH_STARTUP_MS = 3_000
# Se un giro viene SALTATO (una pubblicazione era già in volo, o il thread non è partito) si riprova
# a breve invece di aspettare l'intero intervallo (rilievo Fable #158).
_PUBLISH_RETRY_MS = 5 * 60_000

# Colori SEMANTICI del design system, non decorativi: verde = a posto, arancio = un giro saltato,
# rosso = i bridge si stanno bloccando. Sono gli stessi token che il bridge usa per ATTIVO /
# RICONNESSIONE / OFFLINE, così il significato del colore resta uno solo in tutto il prodotto.
# A livello di MODULO, non di classe: `_publish_status` è logica pura esercitata headless su un
# `self` finto, e una costante di classe costringerebbe ogni harness a modellarla.
_PUBLISH_STATUS_COLORS = {
    publish_store.FRESHNESS_OK: ui_theme.STATUS_OK,
    publish_store.FRESHNESS_WARN: ui_theme.STATUS_WARN,
    publish_store.FRESHNESS_EXPIRED: ui_theme.STATUS_ERR,
    publish_store.FRESHNESS_NEVER: ui_theme.STATUS_WARN,
}


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
        build_backup / save_backup / load_backup / restore_backup / auto_backup
                          — accessi a disco del backup completo (#183), stessa firma di
                            `license_manager.backup`.
    """

    def __init__(self, master=None, *, key_dir=None, now_provider=None,
                 generate_keypair=None, load_key=None, save_key=None,
                 export_key=None, issue_license=None,
                 record_issued=None, read_records=None,
                 record_revocation=None, read_revocations=None,
                 load_publish_config=None, save_publish_config=None,
                 load_publish_token=None, save_publish_token=None, publish_upload=None,
                 check_access=None,
                 load_last_publish=None, save_last_publish=None,
                 build_backup=None, save_backup=None, load_backup=None,
                 restore_backup=None, auto_backup=None, restore_in_progress=None):
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
        self._check_access = check_access or publisher.check_access
        # Stato «ultima pubblicazione riuscita» (#157): iniettabili come gli altri accessi a disco,
        # così i test non toccano la cartella reale del License Manager.
        self._load_last_publish = load_last_publish or publish_store.load_last_publish
        self._save_last_publish = save_last_publish or publish_store.save_last_publish
        # Backup completo / ripristino (#183): iniettabili come gli altri accessi a disco.
        self._build_backup = build_backup or backup_mod.build_backup
        self._save_backup = save_backup or backup_mod.save_backup
        self._load_backup = load_backup or backup_mod.load_backup
        self._restore_backup = restore_backup or backup_mod.restore_backup
        self._auto_backup = auto_backup or backup_mod.auto_backup
        self._restore_in_progress = restore_in_progress or backup_mod.restore_in_progress
        self._pub_last_lbl = None
        self._publish_after_id = None
        self._publish_inflight = False      # un solo upload alla volta (niente accavallamenti)
        # Lucchetto creato **subito** (non pigramente): così non esiste nemmeno in teoria la finestra
        # in cui due thread ne creerebbero due diversi (rilievo GPT-5.5 #158). La creazione pigra in
        # `_publish_lock()` resta solo come rete per i `self` finti dei test.
        self._publish_lock_obj = threading.Lock()
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
        self._schedule_publish_tick(first=True)

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
        self._auto_backup_safe()        # #183: emissione = lo stato è cambiato
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

    def _evaluate_renew(self, serial, giorni_str, *, conferma_revoca: bool = False) -> dict:
        """**Rinnovo/ri-emissione** (opzione B): ri-emette una licenza identificata dal `serial`, per
        lo STESSO nome + hardware ID del record, con **nuovi giorni** → nuovo token (nuovo serial; il
        record vecchio resta nello storico). Fail-closed se il serial non è nel registro.

        **Rinnovo di un serial REVOCATO = riattivazione.** Il token nuovo ha un serial nuovo, che non
        è nella lista di revoche: il cliente torna operativo. È il percorso di riattivazione previsto
        dal modello (la revoca è per emissione, non per persona), ma prima avveniva **in silenzio** —
        e combinato con la vista che non mostrava lo stato revocato si poteva riattivare un cliente
        tolto, per errore, senza accorgersene. Ora serve `conferma_revoca=True`, che la GUI ottiene
        da un dialogo esplicito. Fail-closed: senza conferma non si emette nulla."""
        rec = registry.find_by_serial(self._read_records(directory=self._key_dir), serial)
        if rec is None:
            return {"accepted": False, "token": "",
                    "message": f"Serial non trovato nel registro: {str(serial).strip()}"}
        # La lettura si fa SEMPRE, anche quando la conferma è già stata data (secondo rilievo
        # bloccante di Fable 5). Prima `conferma_revoca=True` saltava l'intero blocco: si poteva
        # riemettere un revocato **senza aver mai letto lo store**, dietro un dialogo che per
        # giunta afferma «il cliente che avevi revocato» quando in realtà non lo sappiamo.
        #
        # Una conferma autorizza l'ESITO di una verifica riuscita; non la sostituisce.
        try:
            revocati = self._revoked_serials(strict=True)
        except Exception as exc:    # noqa: BLE001 — stato ignoto: si ferma, NON si chiede
            _log.debug("Revoche illeggibili durante il rinnovo [%s]", type(exc).__name__)
            # Niente `needs_confirm`: «non riesco a leggere» non è una domanda da porre
            # all'utente — sarebbe un tasto per saltare il controllo. È un errore transitorio
            # (lock, permessi) che si risolve e si riprova.
            return {"accepted": False, "token": "",
                    "message": "⚠️ Impossibile leggere l'elenco delle revoche: il rinnovo è "
                               "sospeso. Chiudi i programmi che tengono aperto revoked.jsonl "
                               "e riprova."}
        if not conferma_revoca and registry.normalize_serial(rec.get("serial")) in revocati:
            return {"accepted": False, "token": "", "needs_confirm": True,
                    "message": f"⚠️ La licenza {str(rec.get('serial', '')).strip()} è REVOCATA. "
                               "Rinnovarla emette un token nuovo che tornerà a funzionare."}
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
        self._auto_backup_safe()        # #183: revoca = lo stato è cambiato
        if not recorded:
            return {"accepted": False,
                    "message": "Revoca NON registrata (permessi/percorso della cartella?): riprova."}
        return {"accepted": True,
                "message": f"Licenza revocata: {rec.get('serial', '')} ({rec.get('name', '')}). "
                           "Diventa attiva sui bridge quando la lista è pubblicata."}

    def _auto_backup_safe(self) -> bool:
        """Backup automatico dello stato mutevole (#183). Agganciato a **emissione e revoca** — i due
        momenti in cui i dati cambiano — non alla pubblicazione della lista, che ri-firma e carica ma
        non tocca il disco.

        `backup.auto_backup` è già best-effort, ma qui c'è comunque una rete **strutturale** (rilievo
        Claude Fable 5 #184). Misurato: senza questo `except`, un'eccezione imprevista dal backup
        **fa fallire l'emissione della licenza** — cioè la rete di sicurezza romperebbe esattamente
        l'operazione che dovrebbe proteggere. Oggi non succede perché `auto_backup` cattura i tipi
        che sa di poter incontrare; ma quella garanzia vive in un altro modulo e un domani può
        cambiare, mentre il danno cadrebbe qui. Stessa scelta già fatta per il fail-open del gate
        revoca (#159), dove la sola diagnostica poteva vanificare il fail-open.

        Nel log finisce **solo il tipo** dell'eccezione: il messaggio può contenere il percorso della
        cartella-dati, che su Windows include il nome account."""
        try:
            return self._auto_backup(self._key_dir, now=self._now())
        except Exception as exc:    # noqa: BLE001 — il backup NON deve poter far fallire emissione/revoca
            _log.warning("Backup automatico non riuscito: %s", type(exc).__name__)
            return False

    def _evaluate_export_backup(self, dest_path, *, overwrite: bool = False) -> dict:
        """📦 Esporta backup **completo** (migrazione): seed + registro + revoche + impostazioni.

        ⚠️ Il file contiene il **seed**: il messaggio lo dice esplicitamente, perché è l'unico momento
        in cui l'utente decide dove metterlo. Il token GitHub **non** entra (vive nel keyring)."""
        dest = str(dest_path or "").strip()
        if not dest:
            return {"ok": False, "message": "Scegli un percorso per il backup."}
        try:
            contenuto = self._build_backup(self._key_dir, now=self._now())
            self._save_backup(dest, contenuto, overwrite=overwrite)
        except backup_mod.BackupExistsError as exc:
            # Recuperabile con una conferma: `needs_confirm` lo dice all'handler, che chiede.
            return {"ok": False, "needs_confirm": True, "message": str(exc)}
        except backup_mod.BackupError as exc:
            return {"ok": False, "message": str(exc)}
        except (OSError, core.KeyFileCorruptError) as exc:
            _log.warning("Backup non riuscito: %s", type(exc).__name__)      # mai il messaggio
            return {"ok": False, "message": "Backup non riuscito (percorso non scrivibile o chiave "
                                            "corrotta)."}
        quanti = len(contenuto.get("files", {}))
        return {"ok": True,
                "message": (f"Backup completo salvato in: {dest} ({quanti} file). "
                            "⚠️ Contiene la CHIAVE PRIVATA: tienilo su un supporto offline, mai in "
                            "cartelle sincronizzate o condivise. Il token GitHub non è incluso: sul "
                            "nuovo PC va re-inserito.")}

    def _evaluate_restore_backup(self, src_path, *, overwrite_key: bool = False) -> dict:
        """📥 Ripristina un backup.

        Sostituisce il passo fragile di oggi — copiare a mano un file in `%APPDATA%` **prima** di
        avviare il programma: sbagliare l'ordine genera una seconda keypair, e le licenze firmate con
        quella non verificano contro la chiave pubblica compilata nell'EXE distribuito."""
        src = str(src_path or "").strip()
        if not src:
            return {"ok": False, "message": "Scegli il file di backup da ripristinare."}
        try:
            contenuto = self._load_backup(src)
            esito = self._restore_backup(contenuto, self._key_dir, overwrite_key=overwrite_key)
        except backup_mod.BackupKeyMismatchError as exc:
            return {"ok": False, "needs_confirm": True, "message": str(exc)}
        except backup_mod.BackupError as exc:
            return {"ok": False, "message": str(exc)}
        except (OSError, core.KeyFileCorruptError) as exc:
            _log.warning("Ripristino non riuscito: %s", type(exc).__name__)
            return {"ok": False, "message": "Ripristino non riuscito (cartella non scrivibile o "
                                            "chiave attuale corrotta)."}
        return {"ok": True,
                "message": ("Ripristinati: " + ", ".join(esito["scritti"]) +
                            ". Gli eventuali dati già presenti e NON contenuti nel backup (es. "
                            "revoche più recenti) sono stati lasciati invariati. Riavvia il "
                            "License Manager per rileggere lo stato.")}

    def _conferma(self, testo: str) -> bool:
        """Conferma esplicita per le azioni **irreversibili o pericolose**: sovrascrivere un backup
        esistente, sostituire una keypair diversa, riattivare un cliente revocato. (Si chiamava
        `_confirm_backup` finché serviva solo al backup; il nome mentiva da quando fa da gate anche al
        rinnovo.) Seam iniettabile e **fail-closed**: se il dialogo
        non è disponibile (headless, Tk rotto) la risposta è «no» — meglio non fare che fare un danno
        irreversibile senza che nessuno l'abbia confermato."""
        try:
            from tkinter import messagebox
            return bool(messagebox.askyesno("Conferma", testo, icon="warning", default="no"))
        except Exception:       # noqa: BLE001 — dialog Tk best-effort, fail-closed
            return False

    def _on_export_backup(self) -> None:
        """📦 Esporta backup completo. Il percorso lo sceglie un file-dialog; headless resta '' →
        messaggio, nessuna scrittura."""
        dest = ""
        try:
            from tkinter import filedialog
            dest = filedialog.asksaveasfilename(
                title="Backup completo (contiene la CHIAVE PRIVATA)", defaultextension=".json",
                initialfile="xtrader_licenser_backup.json")
        except Exception:       # noqa: BLE001 — dialog Tk best-effort
            dest = ""
        result = self._evaluate_export_backup(dest)
        if result.get("needs_confirm") and self._conferma(
                f"{result['message']}\n\nSovrascriverlo? Se quel file è il backup di un'ALTRA "
                "keypair, perderesti l'unica copia di quella chiave e non potresti più rinnovare "
                "le licenze firmate con essa."):
            result = self._evaluate_export_backup(dest, overwrite=True)
        self._set_msg(result["message"])

    def _on_restore_backup(self) -> None:
        """📥 Ripristina un backup scelto dal file-dialog."""
        src = ""
        try:
            from tkinter import filedialog
            src = filedialog.askopenfilename(title="Ripristina backup completo",
                                             filetypes=[("Backup XTrader", "*.json")])
        except Exception:       # noqa: BLE001 — dialog Tk best-effort
            src = ""
        result = self._evaluate_restore_backup(src)
        if result.get("needs_confirm") and self._conferma(
                f"{result['message']}\n\nSostituire comunque la keypair attuale con quella del "
                "backup?"):
            result = self._evaluate_restore_backup(src, overwrite_key=True)
        self._set_msg(result["message"])
        self._refresh_key_state()
        self._on_registry_refresh()

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
        return registry.view_rows(records, query=str(query or ""), now=self._now(),
                                  revoked_serials=self._revoked_serials())

    def _revoked_serials(self, *, strict: bool = False) -> set:
        """I serial revocati. **Due modi, deliberatamente diversi** (rilievo bloccante di Fable 5 e
        Fugu Ultra, indipendenti).

        `strict=False` (default, per la **vista**): se lo store non è leggibile l'insieme è vuoto e
        la tabella mostra gli stati per data. Degradare a «non so chi è revocato» è accettabile per
        un elenco — che gira anche subito dopo un'emissione e non deve mai far fallire l'azione.

        `strict=True` (per l'**autorizzazione**): l'errore **propaga**. Riusare il degrado
        best-effort come gate era un fail-OPEN reale: con `revoked.jsonl` illeggibile o lockato —
        frequente su Windows — un serial revocato saltava la conferma e veniva riemesso in
        silenzio. Non poter leggere le revoche **non è** «nessuno è revocato»: è «non lo so», e su
        un gate le due cose non possono coincidere."""
        try:
            return {registry.normalize_serial(r.get("serial"))
                    for r in self._read_revocations(directory=self._key_dir)}
        except Exception as exc:    # noqa: BLE001 — vista best-effort; il gate passa `strict=True`
            if strict:
                raise
            _log.debug("Lettura revoche per la vista non riuscita [%s]", type(exc).__name__)
            return set()

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
        esattamente ciò che serve per tenere l'URL sempre popolato e fresco.

        ⚠️ **Ma non se un ripristino è rimasto a metà** (bloccante Fugu Ultra #184). Lì «store vuoto»
        non significa «nessuno revocato»: significa «le revoche non sono ancora state scritte».
        Firmare quella lista la renderebbe indistinguibile da una legittima — valida, firmata, più
        recente — e ri-attiverebbe tutti i revocati. Il controllo sta **qui** e non nei due chiamanti
        perché questo metodo è la sorgente unica di entrambi: un gate messo più in là potrebbe essere
        aggirato da una strada nuova."""
        if self._restore_in_progress(self._key_dir):
            return (None, 0,
                    "⛔ Ripristino di un backup rimasto INCOMPLETO: la lista revoche non viene "
                    "firmata, perché in questo stato potrebbe risultare vuota e ri-attivare tutti i "
                    "revocati. Rifai «📥 Ripristina backup completo» fino in fondo.")
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
        # Registra l'istante SOLO su esito riuscito, e solo qui: questo metodo è il passaggio unico di
        # entrambe le strade (🚀 «Pubblica ora» e tick automatico), quindi l'etichetta non può
        # divergere fra le due. Best-effort: `save_last_publish` non solleva.
        self._save_last_publish(int(self._now()), directory=self._key_dir)
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

    def _evaluate_check_access(self) -> dict:
        """Verifica **preventiva e in sola lettura** che la pubblicazione funzionerà.
        Ritorna ``{"ok","message"}``. Non scrive nulla, né su GitHub né su disco.

        Fail-safe come `_evaluate_publish_now`: nessuna eccezione verso la GUI, e il **token non
        compare mai** nel messaggio."""
        cfg = self._load_publish_config(directory=self._key_dir)
        problema = publish_store.validate_config(cfg)
        if problema is not None:
            return {"ok": False, "message": problema}
        token = self._load_publish_token()
        if not token:
            return {"ok": False,
                    "message": "Token assente nel keyring: salvalo nelle impostazioni di pubblicazione."}
        esito = self._check_access(cfg["repo"], cfg["path"], cfg["branch"], token=token)
        return {"ok": bool(esito.get("ok")), "message": str(esito.get("message", ""))}

    def _check_access_worker(self) -> None:
        """Corpo del thread della verifica (stessa forma di `_publish_worker`). Non solleva mai."""
        try:
            result = self._evaluate_check_access()
        except Exception as exc:    # noqa: BLE001 — il thread non deve morire in silenzio
            _log.warning("Verifica accesso non riuscita [%s]", type(exc).__name__)
            result = {"ok": False, "message": "Verifica non riuscita (errore imprevisto)."}
        try:
            self.after(0, lambda: self._check_access_finish(result))
        except Exception:       # noqa: BLE001 — finestra distrutta: nessuna UI da aggiornare
            self._set_publish_inflight(False)

    def _check_access_async(self) -> bool:
        """Avvia la verifica in background. Condivide `_publish_inflight` con la pubblicazione:
        sono due operazioni di rete con lo **stesso token** verso lo **stesso repo**, e lasciarle
        accavallare significherebbe che un tick automatico parte mentre l'utente sta diagnosticando
        — con due esiti che si sovrascrivono nella riga messaggi e nessuno dei due leggibile."""
        with self._publish_lock():
            if self.__dict__.get("_publish_inflight"):
                return False
            self._publish_inflight = True
        try:
            self._spawn_publish_thread(self._check_access_worker)
        except Exception as exc:    # noqa: BLE001 — thread non avviabile: libera il flag e segnala
            self._set_publish_inflight(False)
            _log.warning("Avvio thread verifica accesso non riuscito [%s]", type(exc).__name__)
            return False
        return True

    def _check_access_finish(self, result) -> None:
        """Applica l'esito della verifica sul thread GUI e libera il lucchetto.

        A differenza di `_publish_finish` **non** ridipinge l'etichetta dell'ultima pubblicazione:
        una verifica non pubblica nulla, e toccare quell'etichetta suggerirebbe il contrario."""
        self._set_publish_inflight(False)
        self._set_msg(("" if (result or {}).get("ok") else "⚠️ ") + str((result or {}).get("message", "")))

    def _publish_finish(self, result) -> None:
        """Applica l'esito sul thread GUI e libera il lucchetto."""
        self._set_publish_inflight(False)
        # L'istante l'ha gia' scritto il worker (in `_evaluate_publish_now`, solo su successo): qui si
        # rilegge da disco per ridipingere. Il refresh gira SEMPRE, anche su fallimento — cosi' dopo un
        # tentativo andato male resta in vista quanto e' vecchia l'ultima riuscita, che e' proprio il
        # dato che serve per capire quanto tempo resta prima che i bridge si blocchino.
        self._refresh_publish_status()
        self._set_msg(("✅ " if (result or {}).get("ok") else "⚠️ ") + str((result or {}).get("message", "")))

    def _publish_tick(self) -> None:
        """Tick della pubblicazione automatica: se abilitata avvia la pubblicazione **in background**
        e si **ri-arma** sempre (non aspetta l'esito della rete). Best-effort: un errore non deve
        fermare il ciclo né rompere la finestra."""
        self._publish_after_id = None
        saltata = False
        try:
            cfg = self._load_publish_config(directory=self._key_dir)
            if cfg.get("enabled"):
                # `False` = pubblicazione NON avviata (una era già in volo, o il thread non è
                # partito): non si può aspettare un intero intervallo, altrimenti si allunga la
                # distanza fra due liste fresche verso la finestra del bridge (rilievo Fable #158)
                # → si riprova **a breve**.
                saltata = not self._publish_async()
        except Exception as exc:    # noqa: BLE001 — il ciclo non deve morire per un errore imprevisto
            _log.warning("Tick pubblicazione non riuscito [%s]", type(exc).__name__)
            saltata = True
        self._schedule_publish_tick(retry_soon=saltata)

    def _schedule_publish_tick(self, *, retry_soon: bool = False, first: bool = False) -> None:
        """(Ri)programma il tick: alla cadenza configurata, **quasi subito** all'avvio
        (`first=True`, catch-up di una lista già scaduta) oppure **fra pochi minuti** se la
        pubblicazione di questo giro è stata **saltata** (`retry_soon=True`), così un salto non
        allunga la distanza fra due liste fresche. Non riprogramma in chiusura; `after` è best-effort
        (finestra distrutta → nessun ri-arm)."""
        if self.__dict__.get("_closing"):
            return
        if first:
            # Catch-up d'avvio: pubblica quasi subito. Se il PC è stato spento a lungo la lista sul
            # repo è già scaduta e i bridge sono bloccati: attendere l'intero intervallo li terrebbe
            # bloccati per ore (rilievo Fugu #158).
            try:
                self._publish_after_id = self.after(_PUBLISH_STARTUP_MS, self._publish_tick)
            except Exception:   # noqa: BLE001 — finestra distrutta/headless: niente ri-arm
                self._publish_after_id = None
            return
        if retry_soon:
            try:
                self._publish_after_id = self.after(_PUBLISH_RETRY_MS, self._publish_tick)
            except Exception:   # noqa: BLE001 — finestra distrutta/headless: niente ri-arm
                self._publish_after_id = None
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
    # ── Costruzione della finestra ───────────────────────────────────────────────────────────
    #
    # A SCHEDE dal 2026-07-31 (richiesta del proprietario, con screenshot). Prima era una colonna
    # unica di ~40 widget impilati e **senza `geometry()`**: la finestra prendeva la propria altezza
    # naturale, che su un portatile sfonda lo schermo. Non era un problema estetico —
    # «💾 Backup della chiave privata», «🚫 Revoca licenza» e tutta la pubblicazione automatica
    # finivano **sotto il bordo dello schermo, irraggiungibili**: il pulsante che salva l'unica
    # chiave non rigenerabile del sistema era invisibile.
    #
    # Le schede raggruppano per COMPITO, non per modulo: quello che si fa una volta sola (la chiave)
    # è separato da quello che si fa ogni giorno (emettere, cercare) e da quello che si fa in
    # emergenza (revocare). La riga messaggi e l'intestazione restano FUORI dalle schede, sempre
    # visibili: un esito non deve poter finire in una scheda che non stai guardando.
    _SCHEDE = ("🔑 Chiave", "✅ Emetti", "📋 Registro", "🚫 Revoche", "📦 Backup")

    def _build_ui(self) -> None:
        # Dimensione esplicita: senza, la finestra si dimensiona sul contenuto e sfonda lo schermo.
        # `minsize` impedisce di rimpicciolirla fino a nascondere di nuovo i controlli.
        try:
            self.geometry("900x660")
            self.minsize(780, 580)
        except Exception:       # noqa: BLE001 — headless/Tk assente: la GUI non è il gate
            pass

        # Intestazione fuori dalle schede: identità del tool sempre visibile.
        ctk.CTkLabel(self, text="🔐 XTrader License Manager",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
                     text_color=ui_theme.TITLE_TEXT).pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(self, text="Tool del proprietario — genera le chiavi di attivazione. "
                     "La chiave PRIVATA resta solo su questo PC.",
                     anchor="w", text_color=ui_theme.TEXT2).pack(fill="x", padx=12, pady=(0, 6))

        schede = ctk.CTkTabview(self, corner_radius=ui_theme.RADIUS_CARD)
        schede.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        for nome in self._SCHEDE:
            schede.add(nome)
        # Contenuto SCORREVOLE: le schede da sole non bastano. Misurato alla `minsize` dichiarata
        # (780×580) restano ~450px utili dentro una scheda, e «Registro» ne chiede ~464 — con lo
        # scaling di Windows al 125%/150%, normale sui portatili, sforano anche le altre. Senza
        # scorrimento sarebbe lo stesso difetto di prima, solo spostato dentro le schede.
        self._build_scheda_chiave(self._area_scorrevole(schede.tab("🔑 Chiave")))
        self._build_scheda_emetti(self._area_scorrevole(schede.tab("✅ Emetti")))
        self._build_scheda_registro(schede.tab("📋 Registro"))      # layout suo: vedi il metodo
        self._build_scheda_revoche(self._area_scorrevole(schede.tab("🚫 Revoche")))
        self._build_scheda_backup(self._area_scorrevole(schede.tab("📦 Backup")))

        # Riga messaggi fuori dalle schede: l'esito di un'azione dev'essere visibile qualunque
        # scheda sia aperta (una revoca si conferma dalla scheda Registro e l'esito arriva qui).
        self._msg_lbl = ctk.CTkLabel(self, text="", anchor="w")
        self._msg_lbl.pack(fill="x", padx=12, pady=(2, 10))

        self._refresh_publish_fields()
        self._refresh_publish_status()

    @staticmethod
    def _area_scorrevole(tab):
        """Contenitore scorrevole che riempie una scheda — nulla resta irraggiungibile.

        Il difetto originale era «il contenuto è più alto della finestra e la parte sotto non
        esiste per l'utente». Le schede lo riducono ma non lo eliminano: bastano una finestra
        rimpicciolita o lo scaling di Windows al 125% perché una scheda torni a tagliare. Qui il
        contenuto eccedente diventa **scorribile** invece che invisibile."""
        area = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        area.pack(fill="both", expand=True)
        return area

    # ── scheda: chiave di firma ──────────────────────────────────────────────────────────────
    def _build_scheda_chiave(self, tab) -> None:
        ctk.CTkLabel(tab, text="Chiave pubblica — incollala in xtrader_bridge/licensing/license.py",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        # La chiave sta in un Textbox e non in una Label: da una Label il testo NON è selezionabile,
        # quindi finora l'unico modo di prenderla era ricopiarla a mano da 64 caratteri esadecimali.
        self._public_value = ctk.CTkTextbox(tab, height=54, wrap="char",
                                            font=ctk.CTkFont(family=_MONO[0], size=12))
        self._public_value.pack(fill="x", padx=10, pady=(0, 4))
        riga = ctk.CTkFrame(tab, fg_color="transparent")
        riga.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(riga, text="🔑 Genera / mostra keypair", command=self._on_generate).pack(
            side="left", padx=(0, 6))
        ctk.CTkButton(riga, text="📋 Copia chiave pubblica", command=self._on_copy_public,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(side="left")

        ctk.CTkLabel(tab, text="La chiave PRIVATA non si copia e non si mostra: si salva su file.",
                     anchor="w", text_color=ui_theme.TEXT2, wraplength=760).pack(
                         fill="x", padx=10, pady=(6, 2))
        # Nessun pulsante «copia il seed»: gli appunti sono leggibili da qualunque processo e i
        # gestori di clipboard ne conservano lo storico. Il seed esce SOLO su file, con permessi.
        ctk.CTkButton(tab, text="💾 Backup della chiave privata", command=self._on_export).pack(
            anchor="w", padx=10, pady=(2, 10))

    # ── scheda: emissione ────────────────────────────────────────────────────────────────────
    def _build_scheda_emetti(self, tab) -> None:
        ctk.CTkLabel(tab, text="Dati dell'utente", font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        griglia = ctk.CTkFrame(tab, fg_color="transparent")
        griglia.pack(fill="x", padx=10)
        griglia.grid_columnconfigure(1, weight=1)
        campi = (("Nome", "_nome_entry", "Mario"),
                 ("Cognome", "_cognome_entry", "Rossi"),
                 ("Giorni", "_giorni_entry", "15"),
                 ("Hardware ID", "_hwid_entry", "HW1-…  (te lo manda l'utente)"))
        for r, (etichetta, attributo, esempio) in enumerate(campi):
            ctk.CTkLabel(griglia, text=etichetta, anchor="w", width=110).grid(
                row=r, column=0, sticky="w", pady=3)
            entry = ctk.CTkEntry(griglia, placeholder_text=esempio)
            entry.grid(row=r, column=1, sticky="ew", pady=3)
            setattr(self, attributo, entry)
        ctk.CTkButton(tab, text="✅ Genera chiave di attivazione", command=self._on_issue,
                      fg_color=ui_theme.SUCCESS, hover_color=ui_theme.SUCCESS_HOV).pack(
                          anchor="w", padx=10, pady=(10, 6))

        ctk.CTkLabel(tab, text="Chiave di attivazione da mandare all'utente",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
                         fill="x", padx=10, pady=(6, 2))
        self._token_box = ctk.CTkTextbox(tab, height=76, wrap="char",
                                         font=ctk.CTkFont(family=_MONO[0], size=12))
        self._token_box.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(tab, text="📋 Copia chiave di attivazione", command=self._on_copy_token,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(anchor="w", padx=10, pady=(0, 10))

    # ── scheda: registro (tabella) ───────────────────────────────────────────────────────────
    def _build_scheda_registro(self, tab) -> None:
        # Questa scheda NON usa `_area_scorrevole`: annidare una tabella che scorre dentro un
        # pannello che scorre dà due barre verticali sovrapposte e una rotellina che non si sa
        # quale delle due muove. Qui l'ordine di `pack` fa il lavoro: i comandi si ancorano in
        # BASSO per primi, poi la tabella prende ciò che resta. Rimpicciolendo la finestra è la
        # tabella a restringersi — e scorre — invece di spingere i pulsanti fuori dallo schermo.
        cerca = ctk.CTkFrame(tab, fg_color="transparent")
        cerca.pack(fill="x", padx=10, pady=(8, 4))
        self._reg_query_entry = ctk.CTkEntry(cerca, placeholder_text="Cerca (nome / hardware ID / serial)")
        self._reg_query_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(cerca, text="🔍 Cerca / 🔄 Aggiorna", width=170,
                      command=self._on_registry_refresh).pack(side="left")

        # Tabella vera (ttk.Treeview): prima era un blocco di testo monospaziato, da cui il serial
        # andava selezionato a mano carattere per carattere.
        #
        # `ttk` si importa **qui dentro**, non in testa al modulo. `tkinter` è stdlib ma NON è
        # sempre installato (Debian lo separa in `python3-tk`), e la suite gira headless stubbando
        # `customtkinter` — un `from tkinter import ttk` a livello di modulo fa fallire l'import di
        # `license_manager.gui` e con esso **tutti** i test GUI. È esattamente l'errore già fatto
        # con PyYAML nella #206: una dipendenza d'ambiente presa a livello di modulo per comodità.
        # Questo metodo gira solo dentro una sessione GUI reale, dove Tk c'è per definizione.
        from tkinter import ttk

        self._stila_tabella()
        intestazioni = (("stato", "Stato", 90), ("serial", "Serial", 150), ("nome", "Nome", 170),
                        ("hw", "Hardware ID", 190), ("giorni", "Giorni", 70),
                        ("scadenza", "Scadenza", 100))
        # Derivate, non ri-dichiarate: due elenchi separati divergono al primo rinomino.
        colonne = tuple(chiave for chiave, _titolo, _larghezza in intestazioni)
        # ── comandi ANCORATI IN BASSO (packati per primi, `side="bottom"`) ────────────────────
        # Vanno prima nel codice ma stanno sotto nella finestra: così restano visibili qualunque
        # sia l'altezza. È esattamente ciò che mancava nella versione a colonna unica.
        bottoni = ctk.CTkFrame(tab, fg_color="transparent")
        bottoni.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        ctk.CTkButton(bottoni, text="🔄 Rinnova (nuovo token)", command=self._on_renew).pack(
            side="left", padx=(0, 6))
        ctk.CTkButton(bottoni, text="📋 Ri-mostra token", command=self._on_resend,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(side="left", padx=(0, 6))
        # Revoca in DANGER: è l'azione distruttiva di questa scheda e dev'essere distinguibile
        # a colpo d'occhio dalle altre due (semantica di sicurezza, §13 dell'handoff).
        ctk.CTkButton(bottoni, text="🚫 Revoca licenza", command=self._on_revoke,
                      fg_color=ui_theme.DANGER, hover_color=ui_theme.DANGER_HOV).pack(side="left")

        azioni = ctk.CTkFrame(tab, fg_color="transparent")
        azioni.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(tab, text="Seleziona una riga: il serial finisce nel campo qui sotto.",
                     anchor="w", text_color=ui_theme.TEXT2).pack(
                         side="bottom", fill="x", padx=10, pady=(2, 4))

        # ── tabella + barre di scorrimento (prende lo spazio che resta) ──────────────────────
        # Verticale: le righe crescono senza limite: con 20 licenze e 11 righe visibili, le altre
        # 9 sarebbero IRRAGGIUNGIBILI. Orizzontale: l'Hardware ID è lungo e in una finestra
        # stretta le colonne «Giorni» e «Scadenza» finirebbero oltre il bordo destro.
        contenitore = ctk.CTkFrame(tab, fg_color="transparent")
        contenitore.pack(fill="both", expand=True, padx=10, pady=(2, 0))
        contenitore.grid_rowconfigure(0, weight=1)
        contenitore.grid_columnconfigure(0, weight=1)
        self._registry_table = ttk.Treeview(contenitore, columns=colonne, show="headings",
                                            height=8, style="LM.Treeview")
        for chiave, titolo, larghezza in intestazioni:
            self._registry_table.heading(chiave, text=titolo)
            self._registry_table.column(chiave, width=larghezza, minwidth=60,
                                        stretch=False, anchor="w")
        barra_v = ttk.Scrollbar(contenitore, orient="vertical",
                                command=self._registry_table.yview)
        barra_h = ttk.Scrollbar(contenitore, orient="horizontal",
                                command=self._registry_table.xview)
        self._registry_table.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)
        self._registry_table.grid(row=0, column=0, sticky="nsew")
        barra_v.grid(row=0, column=1, sticky="ns")
        barra_h.grid(row=1, column=0, sticky="ew")
        self._registry_table.bind("<<TreeviewSelect>>", self._on_registry_select)
        # Il textbox legacy non esiste più: `_on_registry_refresh` lo tratta come opzionale, e i
        # test lo tengono a `None`. L'attributo resta per non rompere quel contratto.
        self._registry_box = None
        azioni.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(azioni, text="Serial", anchor="w", width=110).grid(row=0, column=0, sticky="w", pady=3)
        self._renew_serial_entry = ctk.CTkEntry(azioni, placeholder_text="LIC-…")
        self._renew_serial_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ctk.CTkLabel(azioni, text="Nuovi giorni", anchor="w", width=110).grid(row=1, column=0, sticky="w", pady=3)
        self._renew_giorni_entry = ctk.CTkEntry(azioni, placeholder_text="15  (solo per il rinnovo)")
        self._renew_giorni_entry.grid(row=1, column=1, sticky="ew", pady=3)

    # ── scheda: revoche + pubblicazione ──────────────────────────────────────────────────────
    def _build_scheda_revoche(self, tab) -> None:
        ctk.CTkLabel(tab, text="Esporta la lista firmata da caricare sull'URL che il bridge controlla:",
                     anchor="w", wraplength=780).pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkButton(tab, text="📤 Esporta lista revoche firmata",
                      command=self._on_publish_revocation).pack(anchor="w", padx=10, pady=(0, 10))

        ctk.CTkLabel(tab, text="Pubblicazione automatica (GitHub)",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(tab, text="Il repo dev'essere PUBBLICO (il bridge lo scarica senza credenziali). "
                               "Il token resta nel keyring di questo PC, mai su disco.",
                     anchor="w", wraplength=780, text_color=ui_theme.TEXT2).pack(
                         fill="x", padx=10, pady=(0, 4))
        griglia = ctk.CTkFrame(tab, fg_color="transparent")
        griglia.pack(fill="x", padx=10)
        griglia.grid_columnconfigure(1, weight=1)
        campi = (("Repository", "_pub_repo_entry", "tuonome/xtrader-revocation", None),
                 ("File nel repo", "_pub_path_entry", "revocation_list.txt", None),
                 ("Branch", "_pub_branch_entry", "main", None),
                 ("Ogni quante ore", "_pub_interval_entry", "12", None),
                 ("Token GitHub", "_pub_token_entry", "si salva nel keyring", "*"))
        for r, (etichetta, attributo, esempio, maschera) in enumerate(campi):
            ctk.CTkLabel(griglia, text=etichetta, anchor="w", width=130).grid(
                row=r, column=0, sticky="w", pady=3)
            entry = (ctk.CTkEntry(griglia, placeholder_text=esempio, show=maschera) if maschera
                     else ctk.CTkEntry(griglia, placeholder_text=esempio))
            entry.grid(row=r, column=1, sticky="ew", pady=3)
            setattr(self, attributo, entry)

        self._pub_enabled_var = ctk.StringVar(value="off")
        self._pub_enabled_check = ctk.CTkCheckBox(tab, text="Pubblica automaticamente",
                                                  variable=self._pub_enabled_var,
                                                  onvalue="on", offvalue="off")
        self._pub_enabled_check.pack(anchor="w", padx=10, pady=(8, 4))
        bottoni = ctk.CTkFrame(tab, fg_color="transparent")
        bottoni.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(bottoni, text="💾 Salva impostazioni", command=self._on_save_publish_settings,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bottoni, text="🔍 Verifica accesso", command=self._on_check_access,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bottoni, text="🚀 Pubblica ora", command=self._on_publish_now).pack(side="left")
        # Etichetta PERSISTENTE dell'ultima pubblicazione riuscita (#157). Non è un messaggio
        # transitorio come `_msg_lbl`: quella riga la sovrascrive qualunque altra azione, e il modo di
        # rottura più probabile della pubblicazione automatica (tick perso dopo una sospensione) non
        # produce **nessun** messaggio. Qui invece lo stato è sempre presente e visibile all'apertura.
        self._pub_last_lbl = ctk.CTkLabel(tab, text="", anchor="w", wraplength=780)
        self._pub_last_lbl.pack(fill="x", padx=10, pady=(6, 10))

    # ── scheda: backup ───────────────────────────────────────────────────────────────────────
    def _build_scheda_backup(self, tab) -> None:
        ctk.CTkLabel(tab, text="Backup completo — migrazione su un altro PC",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        # Il perché della distinzione, scritto dove serve: col SOLO seed il registro e le revoche
        # non migrano, e un PC nuovo ri-attiverebbe in silenzio tutti i revocati (#183).
        ctk.CTkLabel(tab, text="Il backup della sola chiave (scheda «Chiave») salva il seed: basta a non "
                               "perderlo, NON a migrare il tool. Questo salva anche registro, revoche e "
                               "impostazioni — senza, un PC nuovo ri-attiverebbe in silenzio tutti i revocati.",
                     anchor="w", wraplength=780, text_color=ui_theme.TEXT2).pack(
                         fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(tab, text="📦 Esporta backup completo",
                      command=self._on_export_backup).pack(anchor="w", padx=10, pady=(0, 6))
        ctk.CTkButton(tab, text="📥 Ripristina backup completo", command=self._on_restore_backup,
                      fg_color=ui_theme.SURFACE3, text_color=ui_theme.TEXT,
                      hover_color=ui_theme.BORDER).pack(anchor="w", padx=10, pady=(0, 10))
        ctk.CTkLabel(tab, text="⚠️ Tienilo su un supporto OFFLINE: contiene il seed di firma. Chi lo "
                               "ottiene può emettere licenze indistinguibili dalle tue, e su una "
                               "chiavetta i permessi del file non esistono.",
                     anchor="w", wraplength=780, text_color=ui_theme.STATUS_WARN).pack(
                         fill="x", padx=10, pady=(0, 10))

    def _stila_tabella(self) -> None:
        """Adatta `ttk.Treeview` al tema CustomTkinter (best-effort).

        `ttk` non conosce il tema di CustomTkinter: senza questo la tabella resterebbe bianca in una
        finestra scura. I colori vengono da `ui_theme`, la fonte unica — indice `[1]` = variante
        dark, che è il tema in cui gira il tool."""
        try:
            from tkinter import ttk       # import LOCALE: vedi `_build_scheda_registro`
            stile = ttk.Style()
            stile.theme_use("clam")     # l'unico tema ttk che accetta i colori senza ignorarli
            stile.configure("LM.Treeview",
                            background=ui_theme.SURFACE[1], fieldbackground=ui_theme.SURFACE[1],
                            foreground=ui_theme.TEXT[1], borderwidth=0, rowheight=26)
            stile.configure("LM.Treeview.Heading",
                            background=ui_theme.SURFACE3[1], foreground=ui_theme.TEXT[1],
                            borderwidth=0, relief="flat")
            stile.map("LM.Treeview", background=[("selected", ui_theme.ACCENT[1])],
                      foreground=[("selected", "#ffffff")])
        except Exception:       # noqa: BLE001 — lo stile è cosmetico: se fallisce la tabella resta usabile
            _log.debug("Stile tabella non applicato")

    def _copia_negli_appunti(self, testo: str, *, cosa: str) -> bool:
        """Copia `testo` negli appunti e lo conferma nella riga messaggi.

        Il **seed privato non passa mai di qui**: gli appunti sono leggibili da qualunque processo
        e i gestori di clipboard ne conservano lo storico, quindi la chiave privata esce solo su
        file (pulsante di backup). Qui passano la chiave PUBBLICA e il token di attivazione, che
        sono per costruzione destinati a uscire.

        Ritorna `True` se la copia è riuscita. Best-effort come il resto del rendering Tk: senza
        clipboard (headless) l'azione non solleva, ma **lo dice** invece di fingere il successo."""
        if not testo:
            self._set_msg(f"⚠️ Niente da copiare: {cosa} non è ancora disponibile.")
            return False
        try:
            self.clipboard_clear()
            self.clipboard_append(testo)
            self.update_idletasks()     # su Windows senza questo il contenuto si perde alla chiusura
        except Exception as exc:        # noqa: BLE001 — clipboard assente/occupata
            _log.debug("Copia negli appunti non riuscita [%s]", type(exc).__name__)
            self._set_msg(f"⚠️ Copia non riuscita: seleziona e copia {cosa} a mano.")
            return False
        self._set_msg(f"✅ {cosa} copiata negli appunti.")
        return True

    @staticmethod
    def _testo_widget(widget) -> str:
        """Contenuto di un Textbox Tk, o stringa vuota se assente/headless."""
        try:
            return (widget.get("1.0", "end") or "").strip() if widget is not None else ""
        except Exception:       # noqa: BLE001 — lettura Tk best-effort
            return ""

    def _on_copy_public(self) -> None:
        """Copia la chiave PUBBLICA — quella da incollare in `license.py`."""
        self._copia_negli_appunti(self._testo_widget(self._public_value),
                                  cosa="La chiave pubblica")

    def _on_copy_token(self) -> None:
        """Copia la chiave di attivazione appena emessa — quella da mandare all'utente."""
        self._copia_negli_appunti(self._testo_widget(self._token_box),
                                  cosa="La chiave di attivazione")

    def _on_registry_select(self, _event=None) -> None:
        """Riga selezionata nella tabella → il suo serial finisce nel campo delle azioni.

        Prima il serial andava selezionato a mano da un blocco di testo monospaziato e incollato:
        un `LIC-` sbagliato di un carattere significa rinnovare o **revocare la licenza di un altro
        utente**, quindi l'errore di trascrizione qui non era cosmetico."""
        try:
            selezione = self._registry_table.selection()
            if not selezione:
                return
            # Per NOME, non per indice: `values[1]` si lega all'ordine delle colonne, e il serial
            # sbagliato revoca o rinnova la licenza di un ALTRO utente.
            serial = self._registry_table.set(selezione[0], "serial")
            if self._renew_serial_entry is not None:
                self._renew_serial_entry.delete(0, "end")
                self._renew_serial_entry.insert(0, serial)
        except Exception as exc:    # noqa: BLE001 — selezione best-effort, non deve mai sollevare
            _log.debug("Selezione registro non applicata [%s]", type(exc).__name__)

    def _render_registry(self, rows: list) -> None:
        """Dipinge il registro nella tabella (e nel textbox legacy, se presente).

        Entrambi i widget sono **opzionali**: i test costruiscono l'app senza Tk e li tengono a
        `None`, e `_on_registry_refresh` gira anche subito dopo un'emissione — il rendering non
        deve mai far fallire l'azione che l'ha innescato."""
        tabella = getattr(self, "_registry_table", None)
        if tabella is not None:
            for riga in tabella.get_children():
                tabella.delete(riga)
            for r in rows:
                exp = r.get("expiry")
                scad = _time.strftime("%Y-%m-%d", _time.gmtime(exp)) if isinstance(exp, int) else "?"
                tabella.insert("", "end", values=(r["status"], r["serial"], r["name"],
                                                  r["hardware_id"], f"{r['days_left']}g", scad))
        if getattr(self, "_registry_box", None) is not None:
            self._registry_box.delete("1.0", "end")
            self._registry_box.insert("1.0", self._format_registry_rows(rows))

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
                # È un Textbox (non più una Label): il testo dev'essere SELEZIONABILE, altrimenti
                # 64 caratteri esadecimali si possono solo ricopiare a mano.
                # Sbloccata solo per riscrivere, poi RI-BLOCCATA: il testo resta selezionabile e
                # copiabile, ma non modificabile — una pubblica editata a mano e poi copiata
                # finirebbe nel bridge e farebbe rifiutare ogni licenza valida.
                self._public_value.configure(state="normal")
                self._public_value.delete("1.0", "end")
                self._public_value.insert("1.0", state["public"] or "— (nessuna chiave: premi «Genera»)")
                self._public_value.configure(state="disabled")
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
        # Fonte UNICA del rendering della pubblica. Qui c'era un `configure(text=…)`, che un
        # Textbox NON accetta: sollevava, l'except nudo la ingoiava, e dopo «Genera» la casella
        # mostrava ancora «nessuna chiave» — mentre «Copia» copiava il segnaposto.
        self._refresh_key_state()
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
            self._render_registry(rows)
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
        serial, giorni = (self._read(self._renew_serial_entry),
                          self._read(self._renew_giorni_entry))
        result = self._evaluate_renew(serial, giorni)
        # Riattivazione di un revocato: si chiede, con la conseguenza scritta per esteso. Il dialogo
        # è fail-closed (headless → «no»), quindi nel dubbio non si riattiva nessuno.
        if result.get("needs_confirm") and self._conferma(
                f"{result['message']}\n\nÈ una RIATTIVAZIONE: il cliente che avevi revocato tornerà "
                "operativo. Il serial vecchio resta revocato, quello nuovo no.\n\nProcedere?"):
            result = self._evaluate_renew(serial, giorni, conferma_revoca=True)
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
        """Revoca (R3b) la licenza del serial indicato (stesso campo di rinnovo/ri-mostra), poi
        **propaga** la revoca ai bridge (#157). Vedi `_propaga_revoca`."""
        result = self._evaluate_revoke(self._read(self._renew_serial_entry))
        messaggio = result["message"]
        if result.get("accepted"):
            messaggio = f"{messaggio} {self._propaga_revoca()}"
        self._set_msg(messaggio)
        self._on_registry_refresh()

    def _propaga_revoca(self) -> str:
        """Propaga ai bridge una revoca **appena registrata**; ritorna il testo da aggiungere al
        messaggio. Chiamata solo dopo un esito `accepted` (una non-revoca non si pubblica).

        Perché esiste (#157). Una revoca che resta su questo PC **non revoca nulla**: i bridge
        applicano soltanto la lista *pubblicata*. Prima, `_on_revoke` si fermava alla scrittura su
        disco e la propagazione dipendeva dal solo tick automatico — cioè fino a `interval_hours`
        (default 6) in cui il proprietario crede di aver revocato un cliente che invece continua a
        lavorare. Con la pubblicazione automatica spenta, mai.

        Se l'automatica è **spenta** non si pubblica: quella spunta è una decisione dell'utente e un
        upload non richiesto sarebbe un effetto collaterale a sorpresa. Ma **lo si dice**, invece del
        generico «esporta e ripubblica» che non distingueva i due casi.

        Se una pubblicazione è **già in volo** `_publish_async` ritorna `False`, ed è il caso
        insidioso: quella in volo è partita *prima* di questa revoca, quindi **non la contiene**.
        Senza un nuovo tentativo la revoca aspetterebbe l'intervallo pieno → si riprogramma il tick
        a breve, la stessa strada che `_publish_tick` già usa quando salta un giro.

        **Non solleva mai**, e la promessa copre *tutto* il corpo — non solo la lettura della
        config (rilievo di Fable 5 e Sourcery, indipendenti e concordi). È invocata dentro un
        handler della GUI: se un'eccezione uscisse di qui, `_set_msg` non verrebbe mai chiamato e
        l'utente non vedrebbe **alcuna** conferma di una revoca che invece è già su disco — potendo
        crederla fallita e riprovare. Sarebbe lo stesso difetto che questa funzione esiste per
        chiudere, entrato da un'altra porta."""
        try:
            abilitata = bool(self._load_publish_config(directory=self._key_dir).get("enabled"))
        except Exception as exc:    # noqa: BLE001 — config illeggibile: non si tace, si avvisa
            _log.warning("Impostazioni di pubblicazione illeggibili dopo una revoca [%s]",
                         type(exc).__name__)
            return ("⚠️ Impossibile leggere le impostazioni di pubblicazione: la revoca NON è "
                    "ancora attiva sui bridge. Pubblicala dalla scheda «Revoche».")
        if not abilitata:
            return ("⚠️ Pubblicazione automatica SPENTA: la revoca NON è ancora attiva sui bridge. "
                    "Usa «🚀 Pubblica ora» nella scheda «Revoche».")
        try:
            if self._publish_async():
                return "Pubblicazione della lista in corso…"
            # Il tick normale programmato da `_publish_tick` è ancora in coda: va **annullato**
            # prima di programmare il retry, altrimenti restano due timer vivi e ognuno ne
            # programma un altro (rilievo CodeRabbit, e seconda metà del rilievo Fable).
            # `_schedule_publish_tick` sovrascrive `_publish_after_id` senza annullare — non è
            # idempotente fuori da `_publish_tick`, che invece azzera l'id in testa perché il suo
            # timer è appena scattato.
            self._cancel_publish_tick()
            self._schedule_publish_tick(retry_soon=True)
        except Exception as exc:    # noqa: BLE001 — vedi «non solleva mai» nel docstring
            _log.warning("Propagazione della revoca non avviata [%s]", type(exc).__name__)
            return ("⚠️ La revoca è registrata ma la pubblicazione non è partita: NON è ancora "
                    "attiva sui bridge. Usa «🚀 Pubblica ora» nella scheda «Revoche».")
        return ("Una pubblicazione era già in corso e non contiene questa revoca: "
                "riprovo fra poco.")

    def _publish_status(self) -> tuple:
        """`(testo, colore)` dell'etichetta, da stato su disco + orologio iniettabile. Logica pura:
        nessun widget, quindi testabile headless."""
        testo, stato = publish_store.format_last_publish(
            self._load_last_publish(directory=self._key_dir), int(self._now()))
        return testo, _PUBLISH_STATUS_COLORS.get(stato, ui_theme.STATUS_WARN)

    def _refresh_publish_status(self) -> None:
        """Ridipinge l'etichetta dell'ultima pubblicazione (best-effort headless, come le altre)."""
        try:
            if self.__dict__.get("_pub_last_lbl") is not None:
                testo, colore = self._publish_status()
                self._pub_last_lbl.configure(text=testo, text_color=colore)
        except Exception:       # noqa: BLE001 — render Tk best-effort, come `_set_msg`
            pass

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

    def _on_check_access(self) -> None:
        """Verifica **in sola lettura** che il token possa davvero pubblicare, **in background**
        (fa rete come la pubblicazione: sul thread Tk congelerebbe la finestra).

        Nasce dal collaudo del proprietario sul secondo PC: fino a ieri l'unico modo di scoprire
        che il token non aveva i permessi era **tentare una pubblicazione vera** — cioè
        accorgersene proprio quando serviva, revocando una licenza."""
        if self._check_access_async():
            self._set_msg("⏳ Verifica dell'accesso a GitHub in corso…")
        else:
            self._set_msg("⏳ Un'operazione di rete è già in corso: attendi l'esito.")

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
