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
due, così lo swap è deliberato e non silenzioso).

### Gate di release (fatto) — la chiave di TEST non può finire in un EXE distribuito

I workflow di build del bridge (`.github/workflows/build.yaml`, job `build` Windows e `build-linux`)
hanno uno step **«Gate release licenza»** (`id: license-release-gate`) che, subito dopo `setup-python`
e **prima** dell'install/compilazione, legge `LICENSE_PUBLIC_KEY_IS_PLACEHOLDER` dal modulo puro (solo
stdlib → gira fail-fast, senza dipendenze) e decide così:

- **valore sicuro** = `"0"` (chiave pubblica reale, flag `False`) → gate OK, la build prosegue;
- **release** = un **push di tag** (`github.event_name == push` + `refs/tags/`, la **stessa
  condizione** con cui più sotto viene creata la Release pubblica; il workflow è già filtrato a `v*`
  da `on.push.tags`) con flag ancora `True` **o non leggibile** → la build **FALLISCE** (`::error::` +
  `exit 1`): una release con la chiave di TEST accetterebbe licenze **forgiabili** col seed di test;
- **build manuali** (`workflow_dispatch`, **anche se lanciate da un ref di tag**) con flag `True` →
  solo un **`::warning::`**, la build prosegue: coerente con la **decisione 1A** (lo sviluppo con
  chiavi di TEST resta possibile, il lock GUI non dipende dal placeholder).

Il gate è **fail-closed** (review Sourcery #150): `"0"` è l'**unico** valore che sblocca; se il check
Python fallisce (interprete assente, import error) il valore letto è ≠ `"0"` e viene trattato come
**non sicuro** — su una release **blocca**, in sviluppo **avvisa** — così un errore di lettura del
flag non apre mai la strada a una release con chiave di test. Legare il gate all'**evento** (push di
tag) e non al solo ref evita che un `workflow_dispatch` da un ref di tag venga scambiato per una
release (review GPT-5.5/Sourcery #150).

Il gate è **anti-distrazione**, non una difesa da un avversario con accesso in scrittura ai workflow
(chi edita i workflow può editare anche il gate): impedisce di **taggare per sbaglio** una release con
la chiave di TEST ancora dentro. Il gate anti-drift `tests/safety/test_build_exe_safety.py` verifica
che ogni job di build del bridge **release-capable** (workflow con trigger `push`) contenga il guard
(fail su tag + warning in sviluppo) e che il guard **preceda** la compilazione — così un futuro
workflow di release senza guard (es. Nuitka promosso a build ufficiale su tag) fa fallire i test.

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

### Registro delle licenze emesse (opzione A)

Fino a qui l'emissione di una licenza era **stateless**: il tool produceva un token e non registrava
nulla. Il modulo **`license_manager/registry.py`** aggiunge un **registro locale** append-only —
`licenses.jsonl` nella cartella del License Manager (`%APPDATA%\XTraderLicenseManager`, la stessa del
seed privato, **mai** nel repo/EXE) — così il proprietario può **ritrovare** chi ha ricevuto cosa e
con che scadenza.

- **Serial deterministico** (`license_serial`): l'identificatore di una licenza è
  `LIC-<12 hex di sha256(token)>`, calcolato **dal token firmato**. Deterministico e stabile: il tool
  (che ha appena emesso il token) e — in una fase successiva — il bridge (che ha il token attivato)
  calcolano lo **stesso** serial, **senza** aggiungere campi al formato token (nessuna migrazione).
- **Record dal payload** (`record_from_token`): il record si costruisce leggendo il payload del token
  (nome/hardware/emissione/scadenza **autoritativi**), così il registro combacia sempre con la licenza
  realmente firmata. Campi: `serial`, `name`, `hardware_id`, `issued`, `expiry`, `days`, `token`
  (per ri-invio/rinnovo futuri) e `recorded_at`.
- **Append-only robusto** (`append_record`/`read_records`): stesso idiom di
  `xtrader_bridge.event_journal` — guardia sulla riga troncata (crash a metà append) + `flush`/`fsync`,
  lettura tollerante che **salta** le righe malformate. File assente → `[]` (fail-safe).
- **Vista + ricerca** (`view_rows`): elenco filtrabile **case-insensitive per sottostringa** su
  `serial`/`name`/`hardware_id`, annotato con **stato** (`ATTIVA`/`SCADUTA`, calcolato su «adesso») e
  **giorni rimasti**. Le righe della vista **non** espongono mai il token di attivazione.
- **GUI:** la mini-GUI del License Manager ora, dopo ogni emissione, **registra** la licenza
  (best-effort: un fallimento di scrittura **non** blocca l'emissione — il token è già valido e va
  consegnato; l'utente viene avvisato) e mostra un **elenco con ricerca** («🔍 Cerca / 🔄 Aggiorna»).

**Test hard:** `tests/unit/test_license_manager_registry.py` (serial deterministico, decode/record dal
token, append+read tollerante alla riga troncata, stato/giorni, filtro ricerca, nessun token in vista)
e i casi GUI in `tests/unit/test_license_manager_gui.py` (registrazione all'emissione, fallimento
registro non bloccante, vista fail-safe).

### Rinnovo / ri-emissione (opzione B)

Dato il **serial** di una licenza dell'elenco, il License Manager permette due azioni:

- **🔄 Rinnova** (`_evaluate_renew`): ri-emette una licenza per lo **stesso nome + hardware ID** del
  record, con **nuovi giorni** → **nuovo token** (nuovo serial). Il record vecchio **resta** nel
  registro (storico); il nuovo viene aggiunto. Fail-closed se il serial non è nel registro o i giorni
  non sono validi. Riusa lo stesso percorso firma+registrazione dell'emissione (`_sign_and_record`).
  **Nota (review GLM #153):** il rinnovo **non invalida** il token vecchio — quello resta valido fino
  alla **sua** scadenza (stesso hardware/utente: nessun rischio di doppia scommessa, è la stessa
  macchina). L'**invalidazione anticipata** di una licenza ancora attiva è la **revoca** (fase
  successiva, opzione R3).
- **📋 Ri-mostra token** (`_evaluate_resend`): **sola lettura** — ritrova il record dal serial e
  **ri-mostra il token già emesso** (per rinviarlo all'utente), **senza** firmare nulla di nuovo né
  creare record. Messaggio esplicito se il serial non c'è o se il record (vecchio) non contiene il token.

`registry.find_by_serial` fa il lookup (confronto esatto, spazi/maiuscole normalizzati). **Test hard:**
rinnovo ri-emette stesso hw/nome con nuovi giorni e preserva lo storico, serial non trovato → fail-closed,
giorni non validi → fail-closed, ri-mostra ritorna il token esistente senza nuovi record, serial assente →
`found=False`. È il secondo passo verso la **revoca** (sotto).

### Revoca — fondamenta (modulo firmato) — R3a

La **revoca** permette di invalidare una licenza **ancora valida** prima della sua scadenza. Il
modello è **online e firmato**: il proprietario pubblica una **lista di revoche firmata** su un URL
statico; il bridge la scarica, ne verifica la firma con la chiave pubblica incorporata e **blocca** le
licenze revocate (l'integrazione runtime nel bridge — fetch/cache/reconnect/lock, con gate **fail-open**
che blocca **solo** una licenza esplicitamente revocata — è la fase successiva, R3c).

Questa prima fetta (**R3a**) è la **logica pura e condivisa** in
[`xtrader_bridge/licensing/revocation.py`](../xtrader_bridge/licensing/revocation.py):

- `build_revocation_list(seed, entries, now)` → lista **firmata Ed25519** (la usa il **License
  Manager**; il bridge non ha il seed). Envelope identico al token licenza:
  `<b64u(payload)>.<b64u(firma)>`, `payload = {"v":1,"iss":<unix>,"revoked":[{"serial"|"hw"}...]}`
  canonico. La revoca è **per serial** (una singola emissione) **e/o per Hardware ID** (un'intera
  macchina, stabile tra i rinnovi).
- `verify_revocation_list(signed, public_key_hex=None)` → **fail-closed**: envelope corrotto, firma non
  valida, versione/tipi errati → **`None`** (lista **non fidata**); altrimenti una
  `RevocationList(issued, serials, hardware_ids)`. La firma si verifica sul **payload verbatim** (nessun
  mismatch firma/verifica), come per le licenze. Il contratto fail-closed è **stretto** (review
  CodeRabbit #154): `v` e `iss` devono essere **interi esatti** (nessuna coercizione da stringa/float,
  nessuna confusione bool→int come `True == 1`), e ogni entry di `revoked` dev'essere una revoca
  **canonica** — un elemento non-dict o senza alcun criterio valido (né serial né hw) **non** viene
  silenziosamente saltato: l'intera lista è considerata corrotta → `None`. Saltare una entry potrebbe
  altrimenti far **sparire una revoca legittima** (un utente revocato resterebbe attivo). La
  normalizzazione permissiva (trim/upper, scarto entry vuote) resta **solo lato costruzione**
  (`normalize_entries`, usata dal License Manager sui propri input); la verifica lato bridge non si fida
  di nulla.
- `is_revoked(revlist, serial=, hardware_id=)` → `True` se il serial **o** l'Hardware ID è nella lista;
  `revlist=None` → `False` (la policy su lista assente/non verificabile è del **bridge**, non di questa
  funzione pura).

**Test hard:** `tests/unit/test_licensing_revocation.py` — round-trip firma/verifica, firma sbagliata →
`None`, payload manomesso (firma non valida) → `None`, malformato/versione errata → `None`, chiave pubblica
hex malformata → `None`, envelope con parti extra → `None`, **payload firmato ma non canonico** rifiutato
(`v`/`iss` non interi esatti, entry non-dict o senza criterio → `None`), dedup insiemi, entry mista
serial+hw, normalizza e scarta le entry vuote (lato build), `is_revoked` per serial (case-insensitive) e
per Hardware ID (esatto), lista `None` e criteri vuoti → `False`, lista vuota firmata è valida. Prossima
fetta: **R3c** (fetch/verifica/cache/lock nel bridge; dal 2026-07-30 il gate è **fail-open**: blocca solo una licenza esplicitamente revocata).

### Revoca — License Manager (store + lista firmata) — R3b

Il License Manager ora **revoca** una licenza e **produce la lista firmata** che il proprietario carica
sull'URL statico (il bridge la scaricherà e verificherà in R3c). Tutto **sul PC del proprietario**, mai
nel repo/EXE.

- **Store revoche** (`license_manager/registry.py`, file `revoked.jsonl` accanto a `licenses.jsonl` in
  `%APPDATA%\XTraderLicenseManager`): stesso idiom append-only fail-safe del registro licenze
  (lock di processo, `flush`+`fsync`, guardia anti riga-troncata, lettura tollerante). Contiene **solo**
  serial/hardware/nome + `revoked_at` — **mai** il seed privato.
  - `revocation_record(record, now)` → record di revoca dal record di licenza (serial autoritativo +
    metadati); `ValueError` se il record non ha serial (fail-closed).
  - `append_revocation` / `read_revocations` → append + lettura fail-safe.
  - `is_serial_revoked(revocations, serial)` → dedup/stato (normalizza spazi/maiuscole).
  - `revocation_entries(revocations)` → entry `[{"serial": ..}]` **deduplicate** per la firma.
- **Azione «🚫 Revoca licenza»** (`gui.py::_evaluate_revoke`): dato un serial dell'elenco, registra la
  revoca nello store. **Fail-closed**: serial non nel registro → niente scrittura; serial già revocato →
  nessun duplicato; store non scrivibile → non dichiarata accettata (best-effort come l'emissione).
  La revoca è **per serial** (la singola emissione): è sufficiente a tagliare fuori un utente — solo il
  proprietario emette token, quindi non può auto-rigenerarsi un serial nuovo — ed è **reversibile**
  (emetti una nuova licenza → serial nuovo, non revocato). L'`hardware_id` è conservato nello store come
  metadato ma **non** emesso nella lista (un blacklist di macchina è un'azione più forte, non il default
  di R3b).
- **Azione «📤 Esporta lista revoche firmata»** (`gui.py::_evaluate_publish_revocation`): firma le entry
  dello store con `revocation.build_revocation_list` (seed privato dal file-chiave) e scrive il file
  `<b64u(payload)>.<b64u(firma)>` da caricare sull'URL. **Fail-closed**: senza percorso o senza chiave non
  produce nulla; uno store **vuoto** dà comunque una lista firmata **valida** («niente revocato»), così
  l'URL esiste sempre e il bridge fail-closed di R3c non si blocca solo perché non c'è nulla da revocare.
- **Import/isolamento:** `license_manager` importa `xtrader_bridge.licensing.revocation` (direzione
  **consentita**, come già `core` importa `license`/`ed25519`); il bridge continua a **non** importare
  `license_manager` (test isolamento invariato).

**Test hard:** `tests/unit/test_license_manager_registry.py` (store: `revocation_record` valido/senza
serial, append/read round-trip separato dal registro, file assente/riga troncata, `is_serial_revoked`,
`revocation_entries` dedup serial-only) e `tests/unit/test_license_manager_gui.py` (revoca registra /
serial assente non scrive / già-revocata nessun duplicato / store fallito non accetta; **round-trip
publish→`verify_revocation_list`** ritrova il serial, store vuoto → lista valida, senza percorso/chiave →
fail-closed).

### Revoca — bridge: fetch + verifica + cache + lock — R3c

Il bridge **applica** la revoca: scarica la lista firmata dall'**URL statico**, la verifica, la mantiene
in cache e la integra nel **lock licenza** — **fail-open** dal 2026-07-30 (prima era fail-closed senza grazia: il
bridge deve **raggiungere e verificare** l'URL per operare).

- **Serial condiviso** (`xtrader_bridge/licensing/license.py::license_serial`): il serial deterministico
  (`LIC-` + sha256(token)) vive ora nel **pacchetto condiviso**, così bridge e License Manager lo
  calcolano **identico** senza che il bridge importi `license_manager` (isolamento #140 preservato;
  `license_manager.registry` lo ri-esporta per compatibilità).
- **Client** (`xtrader_bridge/licensing/revocation_client.py`, logica pura + probe iniettabile):
  - `REVOCATION_LIST_URL` — **URL costante nel codice** (decisione 1a). **Dal #157 è l'URL REALE**
    (`https://raw.githubusercontent.com/zarbopiero963-droid/xtrader-revocation/main/revocation_list.txt`,
    lo stesso che il License Manager produce con `publisher.raw_url`) → **la revoca online è ATTIVA**.
    Il vecchio placeholder `.invalid` resta come costante di confronto (`_PLACEHOLDER_URL`: non
    risolvibile → fail-closed se qualcuno lo ripristinasse). L'**attivazione è DERIVATA dall'URL** (`is_placeholder_url`,
    `REVOCATION_URL_IS_PLACEHOLDER` è un marcatore **calcolato**, non una seconda fonte di verità):
    impostare un URL reale **attiva** la revoca — impossibile lasciare «URL reale ma flag a True» e
    disattivarla in silenzio (rilievo Fugu/GLM). Un **gate di release** (`build.yaml`) fa fallire una
    release taggata finché l'URL è ancora placeholder (come per la chiave pubblica).

    > **Il gate sul placeholder non basta da solo — e lo si è visto attivando l'URL** (rilievi
    > bloccanti Fable 5 e Fugu Ultra, #159, indipendenti e concordi). Quel gate verifica che l'URL non
    > sia quello di sviluppo; **non** verifica che a quell'indirizzo ci sia davvero una lista. Nel
    > momento in cui si imposta l'URL reale il flag diventa `False`, il gate stampa «OK» e passa: da
    > lì l'unica garanzia sarebbe che il proprietario si ricordi di pubblicare **prima** di taggare.
    > Un EXE distribuito mentre l'URL risponde 404 avrebbe la revoca online **silenziosamente inefficace**: nessun
    > cliente** — fail-closed corretto, esito disastroso.
    >
    > Perciò `build.yaml` ha un **secondo gate**, `id: revocation-live-gate`, in **entrambi** i job
    > (`build` e `build-linux`, così nessuna delle due strade di distribuzione resta scoperta). Verifica
    > la catena vera end-to-end: la lista è **scaricabile** dall'URL configurato → la **firma è valida**
    > per la chiave pubblica incorporata → il contenuto è **fresco** entro `MAX_LIST_AGE_S` e non datato
    > nel futuro (riusa `fetch_signed`/`accept_signed`, cioè la stessa porta che attraversa il bridge in
    > produzione, non una riscrittura che potrebbe divergere). Su tag `v*` **blocca**; su build manuali o
    > di PR **avvisa** soltanto, così lo sviluppo non dipende dalla rete. È l'unica chiamata di rete del
    > workflow. Con l'URL ancora placeholder non fa rete e non si applica: competente è il gate
    > precedente.
    >
    > Test: `tests/safety/test_revocation_release_gate_159.py` **estrae lo script dall'heredoc del
    > workflow e lo esegue** — così non può divergere dalla logica che gira davvero in CI — con i casi
    > lista assente / non verificabile / stantia / valida / vuota-ma-valida / placeholder, più la
    > verifica che i due job applichino lo **stesso** gate.
  - `fetch_signed(url, fetch=…)` → **fail-closed**: qualunque errore di scarico (rete/DNS/HTTP/timeout/
    TLS/decodifica/lista troppo grande) → `None`. Il *probe* è iniettabile (test senza socket reali).
  - `accept_signed(signed, min_iss=…)` → `verify_revocation_list` + **anti-replay** (`iss >= min_iss`):
    nessuno può «de-revocare» ripubblicando una lista vecchia firmata.
  - `license_revoked(revlist, token=…, hardware_id=…)` → serial dal token **o** Hardware ID nella lista.
  - `gate_allows(revlist, token=…, hardware_id=…)` → **decisione sincrona fail-OPEN** (decisione
    proprietario 2026-07-30, che ribalta il precedente «fail-closed no-grace»): `False` **solo se** la
    licenza risulta **esplicitamente revocata** in una lista verificata. Lista assente, URL
    irraggiungibile, lista stantia, cache mancante, errore imprevisto → **`True`**, non si blocca.

    > **Perché.** Il fail-closed fermava i bridge **a sessione viva** — potenzialmente con posizioni
    > Betfair aperte e nessuno a gestirle — per un disservizio di `raw.githubusercontent.com` o per una
    > ri-pubblicazione dimenticata. Punire un utente legittimo per un guasto altrui non è accettabile:
    > *chi ha licenza valida e non è revocato non dev'essere bloccato, per nessun motivo.*
    >
    > **Il prezzo.** Chi rende l'URL irraggiungibile **prima** che la propria revoca sia pubblicata non
    > viene intercettato. È inevitabile: dall'interno del bridge «GitHub è giù» e «me lo sto
    > nascondendo» sono lo stesso stato, e scegliere di non punire il primo implica non vedere il
    > secondo.
    >
    > **Cosa resta, e fin dove.** Una revoca che arriva **una sola volta** persiste: entra nella cache su
    > disco, viene ricaricata a ogni avvio, e l'anti-replay monotòno (`min_iss`) impedisce di
    > **sostituirla con una più vecchia**. Copre il caso reale: chi smette di pagare e continua a usare
    > l'app, anche restando offline.
    >
    > ⚠️ **Non è permanenza crittografica** (rilievi bloccanti Fable 5 e Fugu Ultra #159, indipendenti e
    > concordi — la versione precedente di questa nota affermava il falso). Cache e floor stanno in
    > `config_dir()`, sul disco dell'utente: **cancellare `revocation_cache.json` + rendere l'URL
    > irraggiungibile** riporta `revlist=None` e `min_iss=0` → gate aperto. **Basta cancellare un file**;
    > il seed privato non c'entra. La firma impedisce di *forgiare* un «non revocato», ma sotto fail-open
    > non serve forgiare: basta far mancare la lista. È il limite invalicabile di una protezione che gira
    > sulla macchina dell'utente — misura contro l'utente **non ostile**, non contro il sabotatore.
    > Pinnato da `test_cache_cancellata_e_URL_irraggiungibile_apre_il_gate`.
    >
    > Le finestre (`FRESHNESS_MAX_AGE_S`, `MAX_LIST_AGE_S`) **non sono più condizioni di avvio**:
    > misurano **quanto in fretta una revoca si propaga**. `verified_at`/`now` restano accettati per
    > compatibilità dei chiamanti ma non decidono — un test lo pinna, così non torna implicito.
- **Integrazione nel lock** (`xtrader_bridge/app.py`): un **supervisore** in background
  (`_revocation_loop`, thread daemon come `_run_bot`) scarica ogni `REFRESH_INTERVAL_S`, verifica,
  aggiorna in memoria lo stato `_rev_state = (lista, verificata_a)` — **tupla unica sostituita
  atomicamente** (nessuna lettura di coppia incoerente tra thread) — e la cache; su fallimento
  **backoff** (`reconnect_policy`, decisione 2a: blip transitorio ritentato, irraggiungibilità
  **persistente** → stantio → gate chiude). Il gate `_license_is_valid()` ora è: licenza valida **e**
  `_revocation_gate_ok()`; il **tick licenza (~60 s)** e ogni fine ciclo del supervisore (`_safe_after`)
  ri-valutano il lock — una licenza revocata a sessione viva → **STOP fail-closed** (stesso path del PR
  4). L'Hardware ID è **memoizzato** (niente WMI/subprocess a ogni tick sul thread GUI). Con l'URL
  **placeholder** il gate sarebbe **bypassato** (dev, come la chiave di TEST) — **oggi non è il caso**:
  l'URL è reale, quindi il gate è **attivo e fail-closed**.

**Test hard:** `tests/unit/test_revocation_client.py` (fetch fail-closed/probe, accept + anti-replay,
`license_revoked` per serial/hw, `gate_allows` assente/stantia/fresca/revocata, cache round-trip/corrotta)
e `tests/integration/test_license_lock_r3c.py` (bypass placeholder, **nessun blocco senza lista**, revoca per
serial, staleness fetch **e contenuto (3 giorni)**, anti-replay per età dell'`iss`, **data nel futuro
rifiutata all'ingresso e nel gate**, attivazione derivata
dall'URL, Hardware ID memoizzato, backoff su fallimenti ripetuti, integrazione in
`_license_is_valid`/`_apply_license_lock` con **STOP a sessione viva**, ciclo del supervisore
ok/fallito/anti-replay, stop supervisore).

**Azioni proprietario prima/durante la distribuzione:** (1) ~~impostare `REVOCATION_LIST_URL` reale~~ —
**FATTO (#157)**: l'URL punta al repository pubblico `zarbopiero963-droid/xtrader-revocation`, quindi il
marcatore placeholder è `False`, l'attivazione è avvenuta e il gate di release non blocca più il tag per
questo motivo. ⚠️ **Prerequisito operativo, da soddisfare PRIMA di avviare o distribuire**: il file
`revocation_list.txt` deve **esistere** a quell'indirizzo — si crea con **🚀 Pubblica ora** dalla sezione
«📤 Pubblicazione automatica» del License Manager (#158). ⚠️ **Aggiornato 2026-07-30 (fail-open):** finché
l'URL risponde 404 i bridge **partono comunque** — quello che non funziona è la **revoca**, che resta
silenziosamente inefficace perché nessun client riceve mai una lista. Non è più un blocco, è una
protezione che non c'è; per questo il gate di release rifiuta di taggare in quello stato; (2) **ri-pubblicare la lista firmata almeno ogni
finestra (3 giorni)** (anche invariata, automatizzato dalla pubblicazione #158) — oltre `MAX_LIST_AGE_S`
le revoche smettono di **propagarsi**. Nota disponibilità (aggiornata 2026-07-30): il gate è ora
**fail-open**, quindi un'irraggiungibilità dell'URL — anche persistente — **non blocca più** i client a
sessione viva. Era la conseguenza «accettata» della scelta iniziale «niente grazia»; il proprietario l'ha
ribaltata perché fermare utenti legittimi per un guasto dell'hosting non è accettabile. Le due finestre
restano costanti tarabili, ma ora misurano la **tempestività della propagazione**, non l'avvio.

### Revoca — pubblicazione automatica su GitHub (#157)

Il punto (2) qui sopra — *ri-pubblicare la lista firmata entro la finestra* — è la sola parte che
dipende dalla memoria del proprietario. Col fail-open dimenticarla **non blocca più nessuno**: rende però
le **nuove** revoche inefficaci, perché un bridge che non l'ha ancora ricevuta continua a funzionare finché
non riceve una lista aggiornata (quelle già arrivate restano applicate). Questa fetta la **automatizza dentro il License Manager**, senza spostare il seed privato.

**Dove sta cosa (invariante):**

| | Dove | Perché |
|---|---|---|
| **Seed privato** (firma) | Solo sul PC, `signing_key.json` | Non lascia mai la macchina: la firma avviene **qui** |
| **Token GitHub** (upload) | Solo nel **keyring** (`SERVICE="XTraderLicenseManager"`) | Credenziale: mai su disco, mai nei log |
| **Impostazioni** (repo/path/branch/intervallo/on-off) | `publish_config.json` in `manager_dir()` | Non segrete, scritte **atomicamente** |
| **Lista firmata** | Repo GitHub **pubblico** | Il bridge la scarica senza credenziali; è firmata → infalsificabile |

- **`license_manager/publish_store.py`** — impostazioni + keyring. `normalize_config` (default
  fail-closed: pubblicazione **spenta**; `enabled` solo su `True` vero; intervallo limitato a
  `MIN_INTERVAL_HOURS..MAX_INTERVAL_HOURS`; **scarta** qualunque campo `token`), `validate_config`
  (repo nella forma `owner/nome` **con i soli caratteri ammessi da GitHub** — `A-Z a-z 0-9 . _ -`;
  niente whitespace in `path`/`branch`),
  `load/save_publish_config` (atomico via `atomic_io`, fail-safe su file assente/corrotto),
  **cadenza vincolata alla finestra del bridge**: `MAX_INTERVAL_HOURS` è **derivato** da
  `revocation_client.MAX_LIST_AGE_S` (un terzo della finestra → 24 h su 72 h), non un numero ricopiato,
  così i due valori non possono divergere. Prima erano ammesse fino a 168 h: una cadenza **più lunga
  della finestra** avrebbe salvato con «successo» una configurazione che **garantisce il lockout** di
  tutti i bridge fra una pubblicazione e l'altra (rilievo CodeRabbit/Fable/Fugu #158). Col cap a un
  terzo, la lista resta fresca **anche saltando un giro**;
  `save/load/delete_publish_token` + `keyring_available` (import `keyring` **soft**, ogni errore del
  backend = «non disponibile», mai un crash).
- **`license_manager/publisher.py`** — upload via **GitHub Contents API**: `GET` per lo `sha`
  (404 → si crea) poi `PUT` con contenuto base64, `message`, `branch` e `sha` in aggiornamento.
  **Nessun follow dei redirect** (`_NoRedirectHandler`, rilievo Fable #158): `urllib` seguirebbe i
  3xx **ri-inviando `Authorization: Bearer <token>`** all'host di destinazione — anche diverso da
  `api.github.com` — cioè un **leak del token**; un 3xx è quindi trattato come errore (soglia `>= 300`,
  non `>= 400`: un redirect non è una pubblicazione riuscita).
  `raw_url(repo, path, branch)` restituisce **l'URL da mettere in `REVOCATION_LIST_URL`** e codifica
  `repo`/`path`/`branch` **esattamente come `contents_url`** (rilievi Fugu/Fable #158): l'API pubblica
  all'indirizzo *codificato*, quindi un raw URL con caratteri grezzi punterebbe a un file inesistente
  → il bridge smette di scaricare la lista → **lockout fail-closed di tutti i bridge**. Se a quotare
  fosse **uno solo** dei due, la divergenza tornerebbe. Errori
  mappati per codice (401/403 permessi, 404 repo/branch, 409/422 conflitto, 429, 5xx) — **il token non
  compare MAI** nei messaggi. HTTP dietro **probe iniettabile** (test senza socket).
- **GUI** (`license_manager/gui.py`, sezione «📤 Pubblicazione automatica (GitHub)»): campi repo/path/
  branch/intervallo + token (`show="*"`, svuotato dopo il salvataggio), checkbox on/off, **💾 Salva
  impostazioni** e **🚀 Pubblica ora**; un **tick** (`_publish_tick`/`_schedule_publish_tick`) ri-firma
  e ri-carica alla cadenza scelta, si **ri-arma sempre** (anche dopo un errore) e viene annullato alla
  chiusura (`_on_close`). All'avvio il primo tick è **ravvicinato** (catch-up: se il PC è stato spento
  a lungo la lista è già scaduta e i bridge sono bloccati — attendere l'intero intervallo li terrebbe
  bloccati per ore); se un giro viene **saltato** (pubblicazione già in volo) si **riprova fra pochi
  minuti** invece che dopo l'intero intervallo (rilievi Fugu/Fable #158). `_build_signed_revocation_list()` è la **sorgente unica** della lista firmata,
  condivisa con l'esportazione su file (📤) così le due strade non divergono.
- **Etichetta «Ultima pubblicazione riuscita»** (`publish_store.load/save_last_publish`,
  `format_last_publish`, `gui._publish_status`/`_refresh_publish_status`). La pubblicazione automatica
  gira **solo mentre il License Manager è aperto**: se si ferma — timer perso dopo una sospensione di
  Windows, rete giù, token scaduto — il guasto sarebbe **muto**, e il primo segnale arriverebbe dai
  bridge bloccati giorni dopo. La riga messaggi (`_msg_lbl`) non basta: è transitoria, la sovrascrive
  qualunque altra azione, e nel caso peggiore (tick che non scatta) **non viene nemmeno scritta**.

  Perciò l'istante dell'ultima pubblicazione **riuscita** è persistito in `publish_state.json` — file
  **separato** da `publish_config.json`, perché quello è configurazione dell'utente (validata,
  normalizzata) e questo è stato osservato scritto dal programma — e mostrato in un'etichetta
  permanente, dipinta **all'apertura della finestra** e dopo ogni tentativo (riuscito **o** fallito:
  dopo un fallimento serve proprio sapere quanto è vecchia l'ultima riuscita).

  Stati e soglie **derivate** da `MAX_LIST_AGE_S`, non ricopiate: `ok` (verde) sotto un terzo della
  finestra; `warn` (arancio) da un terzo in su — è la cadenza massima ammessa, quindi **almeno un giro
  è saltato**, con ancora due terzi di finestra per rimediare; `expired` (rosso) oltre la finestra, con
  la conseguenza scritta in chiaro («le revoche non si propagano più»); `never` se non si è mai
  pubblicato da quel PC. I colori sono i token semantici del design system (`STATUS_OK`/`WARN`/`ERR`),
  gli stessi che il bridge usa per ATTIVO/RICONNESSIONE/OFFLINE.

  **Fail-safe in direzione sicura** su tutta la linea: file assente/corrotto/valore assurdo → «mai
  pubblicato»; errore di scrittura dello stato → **non** propaga (una pubblicazione riuscita non deve
  diventare un fallimento perché non si scrive un timestamp). In entrambi i casi l'etichetta mostra una
  situazione **peggiore** del reale e porta a controllare, invece di rassicurare a torto. L'istante si
  registra **solo** in `_evaluate_publish_now` a esito riuscito — passaggio unico di 🚀 «Pubblica ora» e
  del tick automatico, così le due strade non possono divergere.
- **La rete NON gira sul thread Tk** (rilievo GPT-5.5 #158): firma + `GET`/`PUT` (fino a
  `DEFAULT_TIMEOUT_S` ciascuna) girerebbero per decine di secondi con GitHub lento/irraggiungibile,
  **congelando la finestra**. `_publish_async` avvia un **thread daemon** (`_publish_worker`) e l'esito
  rientra sul thread GUI via `after(0, …)` (`_publish_finish`); il tick **si ri-arma subito**, senza
  aspettare la rete. Un **lucchetto** (`_publish_inflight`) impedisce upload accavallati (click ripetuto
  o tick che cade durante una pubblicazione in corso) e viene **sempre liberato**, anche su errore
  imprevisto o finestra distrutta.

**Fail-closed dove conta:** impostazioni non valide → non si salva; abilitare senza token → rifiutato;
keyring non disponibile → **si rifiuta** invece di scrivere il token in chiaro; token vuoto al ri-salvataggio
→ **non** cancella quello già nel keyring.

**Test hard:** `tests/unit/test_license_manager_publish_store.py` (normalizzazione/validazione,
round-trip, file assente/corrotto, keyring finto assente/rotto, **token mai su disco**),
`tests/unit/test_license_manager_publisher.py` (URL raw/contents, create-vs-update con `sha`, errori
HTTP mappati, rete KO, **token mai nel risultato**) e `tests/unit/test_license_manager_gui.py`
(salvataggio valido/invalido, abilitata-senza-token, keyring KO, token vuoto non cancella, pubblica-ora
end-to-end **verificando la firma della lista caricata**, upload fallito, tick abilitato/disabilitato +
ri-arma dopo errore, annullamento in chiusura).

**Nota operativa:** il tick gira **mentre il License Manager è aperto**. ⚠️ **Aggiornato 2026-07-30
(fail-open):** se il PC resta spento oltre la finestra di freschezza i bridge **non si bloccano più**
(prima, con la scelta «niente grazia», si bloccavano) — si ferma solo la **propagazione delle revoche**:
un bridge che **non ha ancora ricevuto** quella revoca continua a funzionare finché non riceve una lista
aggiornata. ⚠️ Attenzione a non leggerlo più largo di quanto sia: le revoche **già arrivate in cache
restano applicate** anche offline e anche molto oltre la finestra: `gate_allows` decide solo sulla
presenza esplicita della licenza fra i revocati, non sull'età della lista (pinnato da
`test_una_revoca_gia_in_cache_blocca_ANCHE_quando_la_lista_e_stantia`). Per una propagazione
24/7 servirebbe una modalità headless su una macchina sempre accesa — tracciata in #157, **non** in
questa fetta.

### Backup completo e migrazione su un altro PC (#183)

**Il problema.** Il backup preesistente (`export_signing_key`, pulsante «💾 Backup della chiave
privata») copia **solo il seed**, ed è corretto per quello che fa. Non basta però a **migrare** il tool
su un altro PC, e usarlo per quello causa un guasto **silenzioso e grave**: sul PC nuovo `revoked.jsonl`
è vuoto, quindi al primo «🚀 Pubblica ora» si pubblica una lista firmata che dice **«nessuno è
revocato»**. È valida, è firmata, e ha `iss` più recente della precedente: l'anti-replay monotòno del
bridge rifiuta solo le liste *più vecchie*, quindi la accetta. Risultato: **tutti i revocati tornano
attivi**, senza un errore e senza un avviso. E senza `licenses.jsonl` smettono di funzionare «Rinnova» e
«Ri-mostra token» per le licenze già emesse.

**Il modulo.** `license_manager/backup.py` — nessuna GUI, quindi testabile headless:

| Funzione | Ruolo |
|---|---|
| `build_backup(dir, *, now, include_key=True)` | Legge lo stato completo: `signing_key.json` (**obbligatorio**) + `licenses.jsonl` + `revoked.jsonl` + `publish_config.json` + `publish_state.json` (gli ultimi quattro possono legittimamente non esistere ancora). Il campo `public` in testa dice **quale keypair** contiene il backup senza doverne leggere il seed. |
| `save_backup(dest, contenuto, *, overwrite=False)` | Scrittura **atomica** + permessi `0o600` fin dalla prima syscall; come `export_signing_key` **non sovrascrive** senza conferma (→ `BackupExistsError`). Il no-overwrite passa dallo **stesso primitivo che custodisce il seed** (`core._persist_key_file`, `O_CREAT\|O_EXCL`): un «controlla se esiste, poi scrivi» lascerebbe una finestra TOCTOU (rilievo CodeRabbit #184). |
| `load_backup(path)` | Validazione **severa e tutta prima** di qualsiasi scrittura: JSON valido, versione di formato nota, nomi-file solo dall'allowlist, contenuti testuali, e **contenuto di ogni stato interpretabile** (righe JSONL che siano record, JSON di primo livello che sia un oggetto). Quest'ultimo controllo non è pignoleria: gli store leggono **fail-safe** e salterebbero in silenzio le righe illeggibili, quindi un `revoked.jsonl` corrotto dentro il backup avrebbe sostituito uno store valido e prodotto una lista **senza quelle revoche**, senza nemmeno un errore (rilievo CodeRabbit #184). Un backup rotto non arriva mai a toccare lo stato reale. |
| `backup_public(contenuto)` | La pubblica del backup, **ri-derivata dal seed** e non letta dal campo `public` (dichiarativo: un backup manomesso potrebbe averlo incoerente). |
| `restore_backup(contenuto, dir, *, overwrite_key=False)` | Ripristina e ritorna **quali file** ha scritto. Se in `dir` c'è già una keypair **diversa**, rifiuta (`BackupKeyMismatchError`) salvo conferma esplicita. |
| `auto_backup(dir, *, now)` | Backup automatico dello stato **mutevole**, `auto_backup.json` nella cartella del tool. **Best-effort**: non solleva mai. |

**Due scelte di sicurezza, entrambe deliberate.**

- **Il file di backup contiene il seed**, ed è l'oggetto più prezioso del sistema in forma portabile:
  chi lo ottiene può emettere licenze indistinguibili da quelle del proprietario. Il messaggio della
  GUI lo dice esplicitamente («⚠️ Contiene la CHIAVE PRIVATA … supporto offline, mai in cartelle
  sincronizzate o condivise»), perché è l'unico momento in cui l'utente decide **dove** metterlo. Per
  la stessa ragione il **backup automatico esclude il seed**: ogni copia in più è un posto in più da
  cui può uscire, e il seed va salvato **una volta**, consapevolmente.
- **Il token GitHub non entra mai nel backup**: vive nel **keyring** del sistema operativo, che è il
  posto giusto (cifrato, legato all'utente, non copiabile per sbaglio insieme a un file). Sul PC nuovo
  si re-incolla — ed è un segreto **sostituibile** in un minuto, a differenza del seed.

**Quando scatta l'automatismo:** su **emissione** e su **revoca** — i due momenti in cui lo stato su
disco cambia davvero — e **non** sulla pubblicazione della lista, che ri-firma e carica ma non tocca il
disco (un backup lì riscriverebbe gli stessi byte a ogni ciclo, senza proteggere niente).

**GUI** (`_on_export_backup` / `_on_restore_backup`, pulsanti «📦 Esporta backup completo» e «📥
Ripristina backup completo»). Le due azioni distruttive — sovrascrivere un file esistente, sostituire
una keypair diversa — chiedono una **conferma esplicita** che dice *cosa si perde*, non un generico
«sei sicuro?». Il caso reale coperto dalla seconda: sul PC nuovo si è già premuto «Genera keypair»
prima di ripristinare; senza la via d'uscita col conferma-e-riprova si resterebbe bloccati, e senza la
conferma le licenze emesse dopo non verificherebbero più contro la pubblica compilata nell'EXE
distribuito. La conferma è **fail-closed**: dialogo non disponibile → risposta «no».

**Migrazione, passi esatti:** sul PC vecchio «📦 Esporta backup completo» → copia il file su un
supporto **offline** → sul PC nuovo apri il License Manager, «📥 Ripristina backup completo», riavvia
il tool, re-incolla il **token GitHub** nelle impostazioni di pubblicazione. Questo sostituisce il passo
fragile di prima (copiare a mano un file in `%APPDATA%` **prima** di avviare il programma: sbagliare
l'ordine genera una seconda keypair).

**Limiti onesti:**

- Il ripristino **sovrascrive** i file che il backup contiene e **lascia intatti** quelli che non
  contiene: su una destinazione già usata lo stato risulta «misto» (rilievo GPT-5.5 sulla #184). È
  voluto, e l'unica direzione possibile è quella conservativa — la destinazione può avere **più**
  revoche del backup, mai meno. Cancellare i file assenti produrrebbe esattamente il guasto che
  questo modulo esiste per impedire: ripristinare un backup fatto *prima* delle revoche azzererebbe
  `revoked.jsonl`, e la prima pubblicazione ri-attiverebbe tutti i revocati. Il messaggio della GUI
  lo dice, e un test lo fissa.
- La validazione è tutta prima della scrittura, ma il ripristino dei singoli file **non è una
  transazione unica** — un guasto di I/O a metà lascia alcuni file ripristinati e altri no. Ogni
  singolo file è però scritto in modo **atomico**, quindi nessuno resta troncato.
- Il **backup automatico** sta nella **stessa cartella** del tool: protegge da una cancellazione
  accidentale dei file di stato, **non** da un guasto del disco. Contro quello serve l'export
  completo su un supporto esterno.

**Test hard:** `tests/unit/test_license_manager_backup_183.py` — il test centrale **riproduce il
guasto** (migrare col solo seed → la lista pubblicata dice «nessuno revocato»; col backup completo i
revocati restano revocati), più round-trip byte-a-byte, token mai nel file, backup malformato/troncato
che non scrive nulla, seed↔pubblica incoerenti, keypair diversa rifiutata (e accettata con conferma),
auto-backup senza seed / best-effort / cartella vuota. In `tests/unit/test_license_manager_gui.py`:
aggancio a emissione e revoca, **nessun** backup sulla pubblicazione, avviso «CHIAVE PRIVATA» nel
messaggio, round-trip dagli handler, e la strada dialogo → handler → disco con le due conferme
(sovrascrittura e keypair diversa) verificate **sui byte**, non solo sul messaggio.

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
