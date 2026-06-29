# PoC Nuitka — offuscamento via compilazione nativa

> **Stato: Proof of Concept.** Questo documento riporta un esperimento per valutare
> [Nuitka](https://nuitka.net/) come alternativa a PyInstaller allo scopo di
> **proteggere il codice** (compilazione `.py` → C nativo invece del bytecode `.pyc`
> impacchettato, che è banalmente decompilabile). **Non** è una decisione di
> adozione: la build di rilascio resta `build.yaml` (PyInstaller).

## Perché Nuitka per l'offuscamento

Oggi l'EXE PyInstaller `--onefile` impacchetta i `.pyc` del progetto: il sorgente è
recuperabile quasi integralmente con un decompilatore (`decompyle3`, `pycdc`).
Nuitka invece **compila ogni modulo in C** e lo lega in un binario nativo: non
restano `.py`/`.pyc` del progetto da decompilare. È un salto di protezione reale.

Limite onesto: Nuitka (piano gratuito) **non cifra le stringhe** — i letterali
(header CSV, etichette GUI, regex del parser) restano leggibili con `strings`.
L'offuscamento dei letterali è solo nei livelli a pagamento (Nuitka Commercial).

## Cosa è stato verificato (evidenza reale, locale, Linux + GCC 13)

Compilazione della **logica core** (`tools/nuitka_poc_core.py`: parser P.Bet. →
normalizzazione quota → value-map) con `python -m nuitka --standalone`:

| Misura | Risultato |
|---|---|
| Esito compilazione | ✅ OK (Nuitka 4.1.3, backend GCC 13) |
| Tempo build (slice core) | ~40–90 s |
| Output binario vs interpretato | ✅ **Identico** (`OVER 2.5`, quota `1,85`→`1.85`, `live=True`) |
| `.py`/`.pyc` di `xtrader_bridge` nel dist | ❌ **Nessuno** (moduli compilati nel binario) |
| Tipo file prodotto | ELF nativo, *stripped* |
| `__compiled__` nel binario | `True` (interpretato: `False`) |

Il driver contiene **assert hard**: se la logica compilata divergesse (es. la quota
con la virgola non venisse più normalizzata), il PoC fallisce con exit code ≠ 0.

### Prova del limite "stringhe in chiaro"

`strings` sul binario compilato trova ancora letterali del codice
(`OVER 2.5`, `signal_type`, `Quota`, `bet_type`). Conferma: la **logica** è
protetta, il **testo** no (serve hardening dedicato, a pagamento).

## Finding critico: risoluzione path `data/` (PyInstaller-only)

Il codice attuale risolve la cartella `data/` con attributi **specifici di
PyInstaller**:

```python
# xtrader_bridge/dizionario.py e config_store.py (semplificato)
if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", ...)   # PyInstaller
else:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

Probe reale sotto Nuitka:

```text
frozen      = NOT_SET      # PyInstaller lo mette a True, Nuitka NO
has_MEIPASS = False        # esiste solo sotto PyInstaller
__compiled__= True         # marcatore Nuitka
```

**Conseguenza:** sotto Nuitka il ramo "frozen" **non viene mai preso**; si cade sul
ramo `__file__`. Il workflow PoC include i dati con `--include-data-dir=data=data`,
ma **non è ancora verificato su Windows** che `_data_dir()` risolva al percorso
giusto nell'EXE onefile (estrazione in cartella temporanea). Questo è il primo punto
da chiudere se Nuitka venisse adottato: rendere `_data_dir()`/`config_store`
**Nuitka-aware** (es. riconoscere `__compiled__` o usare un path relativo
all'eseguibile valido per entrambi i packager). In questo PoC **il codice app non è
stato modificato** (scope stretto).

## Come riprodurre

**Locale (compatibilità logica core):**

```bash
pip install nuitka
# (Linux standalone richiede anche: pip install patchelf)
python -m nuitka --standalone --include-package=xtrader_bridge tools/nuitka_poc_core.py
./nuitka_poc_core.dist/nuitka_poc_core.bin     # Windows: .exe
# atteso: ultima riga "PoC_OK", e "COMPILED = True"
```

**Windows EXE completo (CI):** lancia manualmente il workflow
**“Nuitka PoC (manuale)”** (`workflow_dispatch`) in GitHub Actions. Produce:

- job `core-smoke` → verifica automatica della logica compilata;
- job `full-exe` → artifact `XTrader-Signal-Bridge-NuitkaPoC-Windows` (EXE da
  testare a mano: la GUI non parte headless in CI).

## Cosa resta NON verificato

- Avvio reale della **GUI** (tkinter/customtkinter) dall'EXE Nuitka su Windows.
- **Telegram** live e scrittura/svuotamento **CSV** dall'EXE Nuitka.
- Risoluzione effettiva di `data/dizionario_xtrader.csv` nell'EXE (vedi finding sopra).
- Tempo di build e dimensione dell'EXE completo su `windows-latest`.
- Integrazione nel **lockfile riproducibile** (Nuitka non è in `requirements-build.lock`).

## Conclusione del PoC

La compilazione Nuitka del bridge è **tecnicamente fattibile** e dà l'offuscamento
atteso (niente bytecode decompilabile). Prima di una eventuale adozione servono:
(1) fix Nuitka-aware dei path `data/`/config; (2) verifica manuale GUI/CSV/Telegram
dall'EXE; (3) ingresso di Nuitka nella catena single-source dei requirements + lock.
Il merge e qualunque cambio di build restano decisione **manuale** del proprietario.
