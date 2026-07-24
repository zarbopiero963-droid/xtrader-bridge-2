# Sistema di licenze del bridge (issue #140)

> Stato: **PR 1 + PR 2 + PR 3a + PR 3b + PR 3c + PR 3d + PR 4 (lock totale GUI) fatte** — il **lock è
> attivo**: senza licenza valida la GUI operativa è bloccata.
> PR 1 = logica (Ed25519 + Hardware ID + verifica). PR 2 = **schermata «🔑 Licenza»** (scheda del Tabview di configurazione):
> mostra l'Hardware ID, permette di incollare e **attivare** la chiave, mostra lo stato, e **persiste**
> la licenza attivata. La verifica resta **isolata dal percorso soldi** (Telegram→CSV). License
> Manager (PR 3) firma le chiavi; il **lock totale della GUI** (PR 4) usa `current_status().valid`
> come gate fail-closed. Il merge resta **manuale del proprietario**.
>
> **PR 2 — pezzi aggiunti:** `license_store.py` (persistenza atomica di token + `last_seen` in
> `%APPDATA%\XTraderBridge\license_state.json`, lettura fail-safe; un file **JSON corrotto** viene
> messo in **backup `.bak`** prima di ripartire da «nessuna licenza», mai su errori di I/O),
> `license_status.py` (stato UI puro: `compute_status`, severità, messaggi, `last_seen` monotòno,
> stato `PERSIST_FAILED`), `license_gui.py` (`LicensePanel` embeddable), e la scheda «🔑 Licenza» in
> `app.py`. Nessun controllo viene disabilitato: l'app funziona come prima.
>
> **Anti-rollback — heartbeat (sintesi review CodeRabbit + GPT-5.5 + Fable #144):** su un **check
> valido** (`current_status`, che in PR 4 sarà il gate del lock) si **registra** `next_last_seen(
> last_seen, now)` — senza, dopo l'attivazione basterebbe tenere l'orologio a un istante pre-scadenza
> per non scadere mai. Politica dei fallimenti di scrittura, che concilia i reviewer:
> - si scrive **solo quando l'orologio è avanzato** (niente write ad ogni refresh → niente
>   `os.replace` concorrenti su Windows);
> - un fallimento **transitorio** (lock antivirus/indexer su `%APPDATA%`) è **tollerato** (la licenza
>   valida resta valida — niente falsi negativi): si conta il numero di fallimenti **consecutivi**;
> - un fallimento **persistente** (≥ `_HEARTBEAT_FAIL_LIMIT` consecutivi, oggi 3) è **fail-closed**
>   (`PERSIST_FAILED`): così non si può negare la scrittura di `last_seen` per non far mai avanzare
>   l'orologio-di-riferimento e aggirare la scadenza. Un write riuscito azzera il conto.
>
> Il **fail-closed** immediato resta all'**attivazione**: se `save_license` non riesce, l'attivazione
> **non riesce** e lo stato precedente atomico resta intatto. I fallimenti dei provider e del heartbeat
> vengono **loggati** (senza segreti) per la diagnosi.

## A cosa serve

Licenza **offline** distribuibile agli utenti, legata all'**Hardware ID** della macchina, a
**tempo (giorni)**, con **chiave di attivazione firmata**. L'utente non può falsificarla né
spostarla su un altro PC.

## Flusso (completo, si realizza nelle PR successive)

1. L'utente apre il bridge → vede il suo **Hardware ID**.
2. Lo manda al proprietario.
3. Il proprietario, dal **License Manager** (tool separato, PR 3), inserisce **Nome, Cognome,
   Giorni** + l'Hardware ID → genera la **chiave di attivazione** firmata.
4. L'utente la incolla nel bridge → verifica **firma + hardware + scadenza** → sblocca per N giorni.

## Modello di sicurezza

- **Firma asimmetrica Ed25519.** Il proprietario ha la chiave **PRIVATA** (firma); il bridge
  contiene solo la **PUBBLICA** (verifica). Senza la privata non si può creare una licenza valida.
- 🔑 **Invariante #1 — la chiave privata non entra MAI nel repository né nell'EXE del bridge.**
  Vive solo nel License Manager, sul PC del proprietario.
- **Hardware ID**: impronta stabile del PC (MachineGuid + seriale volume + MAC, hash SHA-256) → la
  licenza vale solo su quella macchina. Se **nessuna** sorgente è identificabile (VM cieca), l'ID è
  la sentinella riconoscibile `NO_HARDWARE_ID` (`HW1-0000-…`): `verify_license` la **rifiuta
  fail-closed** (review #143), così una licenza non può valere «per tutte» le macchine anonime.
- **Scadenza in giorni + anti-rollback**: il bridge (nelle PR successive) salva l'ultimo timestamp
  visto e rifiuta se l'orologio va indietro oltre una tolleranza (mitiga lo spostamento della data).
- **Onestà**: è una protezione lato client → scoraggia la condivisione/rivendita casuale, **non**
  ferma un cracker esperto. La build **Nuitka** (compilata) alza l'asticella.

## Componenti di questa PR

| File | Ruolo |
|---|---|
| `licensing/ed25519.py` | Ed25519 **pure-Python** (verify + sign), riferimento RFC 8032. Zero dipendenze. Il bridge usa **solo `verify`**. |
| `licensing/hwid.py` | Impronta hardware stabile e offline. Funzione pubblica: `licensing.hardware_id()`. |
| `licensing/license.py` | Formato token + `verify_license(...)` (firma + hardware + scadenza + anti-rollback), **fail-closed**. |

### Perché Ed25519 pure-Python (non `cryptography`/`pynacl`)

Il bridge deve **solo verificare** con una chiave pubblica. Trascinare una libreria crypto
C/Rust complicherebbe la build Windows (PyInstaller **e** Nuitka) e il lockfile riproducibile per
guadagno nullo. La correttezza è blindata dai **vettori di test ufficiali RFC 8032**
(`tests/unit/test_licensing_ed25519.py`). La firma con chiave privata (che richiede più cautela)
vive nel License Manager (PR 3), che gira sul PC del proprietario e può usare una libreria dedicata.

## Formato del token licenza (base64, decisione proprietario #140 §4)

```
<b64url(payload_json)>.<b64url(signature)>
```

- `payload_json` = JSON compatto ordinato: `{"v":1,"name":"Nome Cognome","hw":"HW1-…","iss":…,"exp":…}`
  (`iss`/`exp` = unix seconds UTC).
- `signature` = Ed25519 sul **payload trasportato verbatim** (nessuna ri-serializzazione in
  verifica → nessun rischio di mismatch tra chi firma e chi verifica).

## Esiti di `verify_license`

`VALID` · `MALFORMED` · `INVALID_SIGNATURE` · `WRONG_HARDWARE` · `EXPIRED` · `CLOCK_ROLLBACK`.
Ordine dei controlli: formato → firma → hardware → anti-rollback → scadenza. Qualunque anomalia →
`valid=False` (fail-closed): una licenza non verificabile **non sblocca mai**.

## Chiave pubblica: placeholder e sostituzione

`license.LICENSE_PUBLIC_KEY_HEX` è oggi un **placeholder di TEST** (il seed corrispondente è noto
nei test, così il flusso è esercitabile in sviluppo). **Prima di distribuire copie licenziate**, il
proprietario genera la keypair reale (via License Manager, PR 3) e **sostituisce quella riga** con
la propria chiave **pubblica**. La chiave privata resta solo sul suo PC.

Marcatore rilevabile (review #143): `license.LICENSE_PUBLIC_KEY_IS_PLACEHOLDER` è `True` finché è in uso la
chiave di TEST. Sostituendo la chiave, il proprietario **deve portarlo a `False`** (un test lega i
due, così lo swap è deliberato e non silenzioso); un gate di release / il lock GUI (PR 4) potrà
rifiutarsi di operare in distribuzione finché è `True` (chiave di test = licenze forgiabili).

## License Manager — tool del proprietario (PR 3)

Il **License Manager** è il tool con cui il proprietario genera le chiavi e firma le licenze. Vive
in un package **separato** (`license_manager/`, NON sotto `xtrader_bridge/`) così la logica di firma
e di custodia della chiave privata **non entra mai nell'EXE del bridge** (la build colleziona solo
`xtrader_bridge`, invariante #1). Il bridge **verifica** soltanto; il License Manager **firma**.

### PR 3a — logica pura (fatta)

`license_manager/core.py` (solo logica, nessuna GUI):

| Funzione | Ruolo |
|---|---|
| `generate_keypair()` | Nuova keypair Ed25519 → `(seed_privato_hex, chiave_pubblica_hex)` (seed da `os.urandom`). Il proprietario incolla la **pubblica** nel bridge e custodisce il **seed**. |
| `save_signing_key` / `load_signing_key` | Custodia del seed privato in `%APPDATA%\XTraderLicenseManager\signing_key.json` (file **separato** da quelli del bridge), scrittura **atomica**, permessi `0o600` (POSIX). |
| `export_signing_key` | **Backup FEDELE** (copia byte-per-byte della sorgente validata: nessun metadato alterato) su un percorso a scelta; atomico; come `save` **non sovrascrive** un backup esistente senza `overwrite=True`. |
| `issue_license(seed, nome, giorni, hardware_id, now)` | Firma la licenza (`iss=now`, `exp=now+giorni·86400`) riusando `build_license` (PR 1). Validazioni **fail-closed**: nome non vuoto, giorni intero `1..MAX_LICENSE_DAYS` (~10 anni), Hardware ID **identificabile**. |

**Custodia della chiave (decisione proprietario): file locale + backup**, mai nel repo/EXE. Regola
di sicurezza specifica del file-chiave — diversa dallo stato-licenza del bridge: un file-chiave
**corrotto NON viene mai scartato in silenzio** (`load_signing_key` **solleva** `KeyFileCorruptError`)
e `save_signing_key` (e `export_signing_key` verso il backup) **rifiuta** di sovrascrivere una
chiave valida senza `overwrite=True` — enforcement **atomico** via `O_EXCL` (nessuna race TOCTOU tra
il controllo e la scrittura). Il seed nasce con permessi `0o600` **espliciti** sul temporaneo (niente
finestra a umask largo) e la scrittura fa `fsync` di file **e directory** (durabilità su crash).
Motivo: perdere il seed = non poter più rinnovare le licenze dei bridge già distribuiti. La coerenza
seed↔pubblica è verificata sia al salvataggio sia al caricamento (intercetta manomissioni/bit-rot).

### PR 3b — mini-GUI (fatta)

`license_manager/gui.py` (`LicenseManagerApp`, CustomTkinter) + entrypoint `license_manager_main.py`.
Il proprietario la lancia **da sorgente** sul suo PC: `python license_manager_main.py`. Riusa **solo**
`license_manager.core`:

1. **Genera / mostra la keypair**: al primo avvio genera la keypair e mostra la **chiave pubblica**
   (da incollare in `xtrader_bridge/licensing/license.py`); il seed privato resta in `%APPDATA%`. Non
   rigenera mai sopra una chiave esistente; un file-chiave **corrotto** non viene sovrascritto (si
   ripristina un backup a mano).
2. **Emetti licenza**: `Nome`, `Cognome`, `Giorni`, `Hardware ID` dell'utente → **token firmato** da
   inviare. Fail-closed: senza chiave, giorni non interi, o Hardware ID non identificabile non emette
   nulla.
3. **Backup** della chiave privata su un percorso a scelta (usa `export_signing_key`, no-overwrite).

Come per la GUI del bridge, gli **handler puri** (`_ensure_keypair`, `_evaluate_issue`,
`_evaluate_export`) sono testati **headless** (`tests/unit/test_license_manager_gui.py`); il rendering
Tk reale è **smoke manuale su Windows**. Il modulo importa `customtkinter` → **non** è importato da
`license_manager/__init__.py`, così `import license_manager` (e i test della logica pura) restano
headless.

### PR 3c — blindatura permessi della cartella-chiave (fatta)

`core.secure_dir(path)` / `core.ensure_secure_dir(directory)` restringono la **cartella-dati** del
License Manager al **solo utente proprietario**, e la GUI la chiama all'avvio (`_secure_data_dir`):

- **POSIX**: la cartella è creata **owner-only fin dalla prima syscall** (`os.makedirs(..., mode=0o700)`,
  review CodeRabbit #147 — senza, resterebbe una breve finestra `0o777`&umask prima del chmod), poi
  `chmod 0o700` (il file-chiave è già `0o600`);
- **Windows**: ACL via `icacls`, perché `chmod` non tocca le ACL NTFS (rilievo Fugu #146; su NTFS il
  `0o600` del file è inefficace, quindi la protezione dipende **interamente** da questa DACL). **Un
  solo comando fail-closed** (review Fugu #147): `icacls … /inheritance:r /grant:r
  "<principal>:(OI)(CI)F"` — `/inheritance:r` rimuove le ACE **ereditate**, `/grant:r` concede il
  controllo al **solo** utente corrente. **Niente `icacls /reset` prima del grant**: quel comando
  ripristinerebbe l'ereditarietà **larga** (fail-open) e, se il `/grant` successivo fallisse,
  lascerebbe la cartella-chiave più esposta di prima. Con l'unico comando, se `icacls` fallisce la
  cartella resta **al più ristretta** (fail-closed: al peggio inaccessibile anche all'owner, che è
  avvisato), **mai** allargata. La cartella è creata da noi in `%APPDATA%` (eredita già ACL
  solo-owner), quindi non ci sono ACE **esplicite** pregresse di altri utenti da azzerare. Il
  `<principal>` è **domain-qualified** (`USERDOMAIN\utente` quando `%USERDOMAIN%` è presente — forma
  valida per account locali, di dominio e AzureAD), così `/grant` risolve anche fuori da un account
  locale; l'utente si ricava da `getpass.getuser()` (fallback `USERNAME`/`USER`).

**Limite accettato (review GPT/GLM #147).** `/inheritance:r /grant:r` rimuove le ACE **ereditate** e
(ri)concede l'owner, ma **non** rimuove eventuali ACE **esplicite** di *altri* principal già presenti
su una cartella preesistente. Nel flusso reale non ne esistono (la cartella la creiamo noi; le
versioni precedenti non scrivevano ACL, lasciando solo ACE ereditate che `/inheritance:r` rimuove).
Rimuoverle richiederebbe `/reset` (che reintrodurrebbe il fail-open) o l'enumerazione dei principal
(fragile su gruppi localizzati/dominio): si preferisce **non allargare mai**. Il caso residuo —
cartella preesistente **manomessa** con ACE esplicite di terzi — è coperto dallo **smoke manuale su
Windows**, non dal lockdown automatico.

**Best-effort e non solleva** — se `icacls`/`chmod` mancano o falliscono il tool **prosegue ma con
la protezione della cartella NON garantita** (loggato, solo il tipo eccezione). Il comando `icacls`
è verificato in test via runner **iniettato** (nessun Windows reale necessario); il comportamento
reale su Windows — **incluso un account di dominio/AzureAD e una cartella preesistente con ACE
larghe** — resta **smoke manuale**. La blindatura riguarda **solo** la cartella-dati del tool, mai le
cartelle di **export** scelte dall'utente.

`secure_dir` / `ensure_secure_dir` **ritornano un booleano** che dice se la blindatura è **davvero**
riuscita (review GPT/GLM #147): `True` solo se `chmod`/`icacls` sono andati a buon fine
(su Windows il comando `icacls` con exit code 0), `False` altrimenti (utente non ricavabile,
eccezione, exit code ≠ 0, o `makedirs` fallito). All'avvio la GUI usa questo esito: se è `False` e non
c'è già un errore di chiave, `_refresh_key_state` mostra un **avviso** («non è stato possibile
proteggere la cartella-chiave…») invece di lasciare l'utente con un **falso senso di sicurezza**. Il
booleano non cambia il carattere best-effort: il tool resta comunque utilizzabile, ma l'utente sa che
su un PC condiviso il seed potrebbe non essere protetto.

### PR 3d — workflow di build EXE (fatta)

L'EXE dedicato del License Manager ha il suo workflow **`.github/workflows/build-license-manager.yaml`**:
PyInstaller `--onefile --windowed`, nome **`XTrader-License-Manager`**, script `license_manager_main.py`,
`--collect-submodules license_manager` + `--collect-all customtkinter`, **nessun `--add-data`** e
**nessun** collect esplicito di `xtrader_bridge` (i moduli `xtrader_bridge.licensing.*` li segue
PyInstaller da solo via import; collezionarli a mano farebbe scattare il detector di isolamento).
Trigger **solo `workflow_dispatch`** (niente `push`/`tags`): **zero minuti CI automatici** finché il
proprietario non lancia la build a mano (un runner Windows costa 2× minuti). Resta **fail-closed**: i
test girano prima della compilazione e sono bloccanti; è solo **artifact** scaricabile, **mai una
Release** pubblica.

**Supply-chain fail-closed (review Fugu #148).** Poiché questo EXE compila il tool che **firma le
licenze**, l'install delle dipendenze è **solo** `--require-hashes -r requirements-build.lock`
(versioni + hash pinnati): **nessun fallback legacy non-hashato**. Se il lock manca/è corrotto la
build **fallisce** invece di tirare dipendenze non verificate nell'EXE di custodia della chiave. Il
lock si (ri)genera col workflow «Generate Windows Lockfile».

Il gate anti-drift `tests/safety/test_build_exe_safety.py` ora riconosce **due prodotti**: le build del
bridge restano soggette alle invarianti bridge **invariate**, mentre la build del License Manager è
**scorporata** e verificata da un **gate parallelo** con la sua allowlist (nome/script/collect del
tool). Il classificatore è lo script (`license_manager_main.py` → prodotto LM); qualunque build con uno
script inatteso resta nel gate bridge e ne fa fallire la forma-canonica, così **nessuna build sfugge a
un gate**.

> **Build non eseguita in questo ambiente** (CI Linux/sandbox): la compilazione PyInstaller reale gira
> **solo su Windows** quando il proprietario lancia il workflow. Il gate verifica la **forma** del
> comando in modo deterministico e offline, non produce l'EXE.

Il License Manager si può comunque usare **da sorgente** (`python license_manager_main.py`).

**Isolamento (test):** un test di sicurezza (`tests/safety/test_license_manager_isolation.py`)
verifica che **nessun modulo di `xtrader_bridge` importi `license_manager`** e che i workflow di
build non lo collezionino — così la firma/chiave privata non finisce mai nell'EXE del bridge.

### PR 4 — Lock totale della GUI (fatta)

Il bridge **non opera senza licenza valida**. Cablato in `xtrader_bridge/app.py`:

- **Gate fail-closed** `_license_is_valid()`: `True` **solo** se `self._license_panel.current_status().valid`
  è vero; qualunque assenza (pannello non ancora costruito), errore o stato non determinabile → `False`
  (bloccato). Non apre mai per errore.
- **Lock dei controlli** `_set_operational_lock(locked)`: (dis)abilita i widget operativi **registrati**
  (`_register_lockable`) — campi ⚙️ Generale, opzioni 🎯/🛡️/✅, 📁 Sfoglia / 📄 Crea CSV, **🗑️ Svuota
  CSV**, **💾 Salva Config**, **🧰 Strumenti**, **🧙 Wizard** — **escludendo** START/STOP (governati
  dalla macchina sessione) e la scheda **🔑 Licenza** (mai registrata → sempre usabile). Best-effort
  per-widget (un `CTkLabel` senza `state` non rompe il lock).
- **`_apply_license_lock()`**: rivaluta e (dis)blocca; **START** disabilitato quando bloccato, e se una
  sessione è **viva** al momento dell'invalidazione → **`_stop()`** immediato (fail-closed). Quando
  torna valida, **START** riabilitato solo se non c'è una sessione in corso.
- **Cablaggio**: `on_status_change=self._on_license_status` sul `LicensePanel` (rivaluta a ogni
  attivazione/refresh); valutazione autorevole a fine `_build_ui`; gate in cima a **`_start`** e
  short-circuit in **`_maybe_auto_start`** (niente auto-start senza licenza); **tick periodico**
  `_license_tick` ogni `_LICENSE_TICK_MS` (60 s) che coglie una scadenza a sessione viva. Il tick è
  cancellato in `_on_close`.
- **Chiave TEST**: `LICENSE_PUBLIC_KEY_IS_PLACEHOLDER=True` **non** blocca di per sé (decisione
  proprietario 1A) — il gate è la sola validità della licenza; sostituire la chiave pubblica reale
  prima della distribuzione resta un passo manuale.

**Test hard** (`tests/integration/test_license_lock_140.py`, headless): gate fail-closed
(valida/invalida/pannello assente/`current_status` che solleva), lock/unlock dei widget + tolleranza
widget senza `state`, STOP a sessione viva, START gated, auto-start gated, tick che rivaluta e si
ri-arma, no-riarmo in chiusura. Handoff design aggiornato (`docs/design/design_handoff.md`).

## Azione una-tantum del proprietario (NON una PR)

Generare la **keypair Ed25519**: rimandabile (serve un PC). La farà il License Manager (PR 3b, GUI)
al primo avvio, riusando `generate_keypair()` + `save_signing_key()` sopra. Fino ad allora si
sviluppa/mergia con le **chiavi di TEST** + placeholder; il PC serve solo **prima di distribuire**
copie licenziate reali.

## Test hard (questa PR)

- `test_licensing_ed25519.py` — vettori ufficiali **RFC 8032** (pub/sign/verify), tamper messaggio/
  firma, chiave sbagliata, fail-closed su input malformato, round-trip casuale.
- `test_licensing_hardware_id.py` — impronta pura deterministica/formato/lista vuota, stabilità
  della macchina reale, `components()` non solleva.
- `test_licensing_license.py` — round-trip valido, hardware errato, scaduta, anti-rollback (con
  tolleranza), token malformato, versione errata, firma non valida, override chiave pubblica.
