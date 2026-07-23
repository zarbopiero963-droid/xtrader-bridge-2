# Sistema di licenze del bridge (issue #140)

> Stato: **PR 1 + PR 2 di 4 fatte** — ancora **nessun blocco**. PR 1 = logica (Ed25519 + Hardware
> ID + verifica). PR 2 = **schermata «🔑 Licenza»** (scheda del Tabview di configurazione):
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

## Azione una-tantum del proprietario (NON una PR)

Generare la **keypair Ed25519**: rimandabile (serve un PC). La farà il License Manager al primo
avvio. Fino ad allora si sviluppa/mergia con le **chiavi di TEST** + placeholder; il PC serve solo
**prima di distribuire** copie licenziate reali.

## Test hard (questa PR)

- `test_licensing_ed25519.py` — vettori ufficiali **RFC 8032** (pub/sign/verify), tamper messaggio/
  firma, chiave sbagliata, fail-closed su input malformato, round-trip casuale.
- `test_licensing_hardware_id.py` — impronta pura deterministica/formato/lista vuota, stabilità
  della macchina reale, `components()` non solleva.
- `test_licensing_license.py` — round-trip valido, hardware errato, scaduta, anti-rollback (con
  tolleranza), token malformato, versione errata, firma non valida, override chiave pubblica.
