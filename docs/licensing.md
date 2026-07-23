# Sistema di licenze del bridge (issue #140)

> Stato: **PR 1 + PR 2 + PR 3a + PR 3b + PR 3c (blindatura permessi cartella-chiave) fatte** — ancora
> **nessun blocco**. Mancano il **workflow di build EXE** del License Manager (PR 3d) e il **lock
> totale della GUI** (PR 4).
> PR 1 = logica (Ed25519 + Hardware ID + verifica). PR 2 = **schermata «🔑 Licenza»** (scheda del Tabview di configurazione):
> mostra l'Hardware ID, permette di incollare e **attivare** la chiave, mostra lo stato, e **persiste**
> la licenza attivata. La verifica resta **isolata dal percorso soldi** (Telegram→CSV). License
> Manager (PR 3) e **lock totale della GUI** (PR 4) arrivano dopo. Il merge resta **manuale del
> proprietario**.
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

- **POSIX**: `chmod 0o700` sulla cartella (il file-chiave è già `0o600`);
- **Windows**: ACL via `icacls`, perché `chmod` non tocca le ACL NTFS (rilievo Fugu #146). Due
  comandi (review GPT #147, perché `/inheritance:r` da solo rimuove le ACE **ereditate** ma non
  quelle **esplicite** pregresse): `icacls … /reset` azzera le ACE esplicite preesistenti, poi
  `icacls … /inheritance:r /grant:r "<utente>:(OI)(CI)F"` rimuove l'ereditarietà e concede il
  controllo al **solo** utente corrente — netto: DACL = solo owner, anche su una cartella che
  esisteva già con permessi larghi. L'utente si ricava da `getpass.getuser()` (fallback `USERNAME`/`USER`).

**Best-effort e non solleva** — se `icacls`/`chmod` mancano o falliscono il tool **prosegue ma con
la protezione della cartella NON garantita** (loggato, solo il tipo eccezione). Il comando `icacls`
è verificato in test via runner **iniettato** (nessun Windows reale necessario); il comportamento
reale su Windows resta **smoke manuale**. La blindatura riguarda **solo** la cartella-dati del tool,
mai le cartelle di **export** scelte dall'utente.

### PR 3d — workflow di build EXE (da fare)

L'EXE dedicato del License Manager (`XTrader-License-Manager`, script `license_manager_main.py`,
`--collect-submodules license_manager`) richiede un **refactor mirato** del gate anti-drift
`tests/safety/test_build_exe_safety.py` (oggi assume un solo EXE, quello del bridge) per supportare
due build distinti. Rimandato a una PR dedicata per tenerla piccola e sicura. Fino ad allora il
License Manager si usa **da sorgente** (`python license_manager_main.py`).

**Isolamento (test):** un test di sicurezza (`tests/safety/test_license_manager_isolation.py`)
verifica che **nessun modulo di `xtrader_bridge` importi `license_manager`** e che i workflow di
build non lo collezionino — così la firma/chiave privata non finisce mai nell'EXE del bridge.

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
