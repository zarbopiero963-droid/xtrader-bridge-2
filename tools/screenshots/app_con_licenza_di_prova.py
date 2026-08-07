"""Avvia BetRelay con una licenza di PROVA, solo per catturare gli screenshot.

**Perché esiste.** Senza licenza attiva l'app mostra la fascia rossa «bridge bloccato» e la
scheda «🔒 Licenza» in stato non attivato: uno screenshot così documenta un programma che
l'utente non userà mai in quello stato, e in più la fascia sposta il layout di ~33 px, il che
manda a vuoto i click sulle tab (vedi la nota in `shoot.sh`).

**Che licenza usa.** Il seed di TEST che sta già nel repository — `tests/conftest.py`,
`LICENSE_TEST_SEED_HEX` — la stessa coppia di chiavi con cui girano i test. Non è la chiave di
produzione, non ne esiste una copia nuova, e nessun token viene scritto nel repository: la
licenza si emette **in memoria** a ogni avvio e finisce solo nella cartella dati della macchina
che scatta.

Uso autorizzato dal proprietario (2026-08-06), con questi limiti espliciti:

- la coppia di chiavi era **già** nel repository: non se ne genera una nuova;
- **nessuna riga** del codice di licensing di produzione viene modificata — si sostituisce la
  chiave pubblica *deployata* solo nel processo che scatta, come fa la fixture dei test;
- **nessuna licenza** viene committata;
- serve **solo** agli screenshot.

Uso:

    Xvfb :99 -screen 0 1280x1024x24 &
    DISPLAY=:99 python3 tools/screenshots/app_con_licenza_di_prova.py

Poi `shoot.sh` cattura la finestra come sempre.
"""

import atexit
import json
import os
import pathlib
import runpy
import shutil
import signal
import sys
import time

# `sys.path[0]` è `tools/screenshots/`, non la radice del repo: senza questo, `import
# xtrader_bridge` e `import license_manager` falliscono con ModuleNotFoundError.
_RADICE = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_RADICE) not in sys.path:
    sys.path.insert(0, str(_RADICE))

from tests.conftest import LICENSE_TEST_SEED_HEX
from xtrader_bridge import config_store, license_store
from xtrader_bridge.licensing import ed25519, hwid
from xtrader_bridge.licensing import license as _lic
from xtrader_bridge.licensing import revocation as _rev

INTESTATARIO = "Screenshot di documentazione"
GIORNI = 30

# Suffisso del salvataggio della licenza VERA, se ce n'è una. Nome esplicito e non nascosto:
# se il processo viene ucciso e il ripristino automatico non gira, chi guarda la cartella deve
# capire in tre secondi cos'è quel file e come rimetterlo a posto.
SUFFISSO_BACKUP = ".pre-screenshot"


def preserva_licenza_esistente(percorso) -> "str | None":
    """Mette al riparo una licenza REALE prima di sovrascriverla con quella di prova.

    Rilievo GPT-5.5 sulla PR #310, ed era fondato: il launcher scriveva la licenza di test
    dritta in `license_state.json` della cartella dati. Su una macchina con una licenza vera —
    quella del proprietario, per dire — la licenza reale spariva, e l'app normale poi rifiutava
    quella di prova perché firmata con la chiave di TEST. Cioè: **scattare uno screenshot
    disattivava il programma**, e il token originale non era più recuperabile.

    Comportamento, fail-closed:

    - nessuna licenza presente → non c'è niente da preservare, ritorna ``None``;
    - licenza presente → viene **spostata** (non copiata) in ``<percorso>.pre-screenshot`` e il
      chiamante registra il ripristino;
    - backup GIÀ presente → **si ferma**. È il caso in cui una corsa precedente è stata uccisa
      prima del ripristino: sovrascrivere quel file distruggerebbe la licenza vera, che è
      esattamente il danno da cui questa funzione difende. Meglio fermarsi e farlo sistemare
      a mano.

    Ritorna il percorso del backup, o ``None`` se non c'era nulla da salvare.
    """
    p = pathlib.Path(percorso)
    backup = p.with_name(p.name + SUFFISSO_BACKUP)
    if backup.exists():
        raise SystemExit(
            f"esiste già un salvataggio della licenza in «{backup}»: una corsa precedente è "
            "stata interrotta prima del ripristino. NON lo sovrascrivo — dentro può esserci la "
            "tua licenza vera. Rimettila a posto a mano (rinominala togliendo il suffisso "
            f"«{SUFFISSO_BACKUP}») e rilancia.")
    if not p.exists():
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(backup))
    return str(backup)


def ripristina_licenza(backup, percorso) -> None:
    """Rimette la licenza vera dov'era, in **una sola** operazione atomica.

    `os.replace` e non `unlink()` + `move()` (rilievo GPT-5.5 sulla #310): la coppia lascia una
    finestra in cui la licenza di prova è già cancellata e quella vera non è ancora arrivata —
    se il secondo passo fallisce (lock antivirus su Windows, disco pieno) l'utente resta
    **senza nessuna licenza**, che è di nuovo il danno da cui questa funzione difende.
    `os.replace` sovrascrive la destinazione in un colpo solo ed è atomico su POSIX e Windows.

    Best-effort e silenziosa sui casi già a posto: gira anche da `atexit`, dove sollevare
    sporcherebbe l'uscita del processo senza aiutare nessuno.
    """
    if not backup:
        return
    b = pathlib.Path(backup)
    if not b.exists():
        return
    os.replace(str(b), str(percorso))


def rimuovi_licenza_di_prova(percorso, token_atteso) -> None:
    """Toglie la licenza di prova quando NON c'era una licenza vera da rimettere.

    Rilievo **Claude Fable 5** sulla #310, e aveva ragione: il ripristino era registrato solo
    nel ramo `backup`. Su una macchina **senza** licenza — cioè la macchina di documentazione
    tipica — il token di test restava in `license_state.json` per sempre, e l'app di produzione
    lo **rifiuta** perché firmato con la chiave di test. Il computer passava da «non attivato» a
    «licenza non valida: bridge bloccato», che è uno stato peggiore di quello di partenza: la
    stessa classe di danno che questa PR esiste per prevenire, entrata dalla porta di servizio.

    Cancella **solo se il token è ancora il nostro**. Durante gli scatti l'utente può aver
    incollato una licenza VERA nella scheda «🔒 Licenza» dell'app: cancellarla a fine sessione
    sarebbe di nuovo il danno di partenza. Se il contenuto non combacia, non si tocca niente.
    """
    p = pathlib.Path(percorso)
    if not p.exists():
        return
    try:
        stato = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return                      # illeggibile o non JSON: non è roba nostra, non si tocca
    if str(stato.get("token", "")) != str(token_atteso):
        return                      # qualcun altro l'ha cambiata (es. licenza vera attivata)
    p.unlink()


def _installa_ripristino_su_segnale(sig) -> None:
    """Su SIGTERM/SIGINT esce pulito — **senza mangiarsi l'handler che c'era prima**.

    `main.py` gira nello STESSO processo (via `runpy`), quindi sostituire l'handler a mano ne
    cambierebbe lo spegnimento (rilievo GPT-5.5 sulla #310). I tre casi vanno distinti, e il
    terzo è quello che al primo giro avevo sbagliato:

    - handler **custom**: lo si richiama, poi si esce — `atexit` rimette a posto la licenza;
    - **SIG_DFL**: nessuno aveva chiesto niente, si esce;
    - **SIG_IGN**: il processo aveva deciso di **ignorare** quel segnale. Uscire lo
      contraddirebbe. Si continua a ignorarlo: il ripristino non si perde, perché `atexit`
      girerà comunque quando il processo uscirà per conto suo (secondo rilievo GPT-5.5, che
      aveva ragione: il codice diceva di conservare il comportamento precedente e in questo
      caso non lo faceva).
    """
    precedente = signal.getsignal(sig)

    def _gestisci(numero, frame):
        if precedente == signal.SIG_IGN:
            return                                  # il processo ignorava: continua a ignorare
        if callable(precedente) and precedente != signal.SIG_DFL:
            precedente(numero, frame)
        sys.exit(0)          # `atexit` gira qui: la licenza vera torna al suo posto

    signal.signal(sig, _gestisci)


def _attiva_licenza_di_prova() -> str:
    """Emette e salva una licenza firmata col seed di TEST. Ritorna l'hardware id usato."""
    pubblica = ed25519.public_key(bytes.fromhex(LICENSE_TEST_SEED_HEX)).hex()

    # DUE posti, e il secondo è quello che si dimentica: `revocation.py` fa
    # `from .license import LICENSE_PUBLIC_KEY_HEX`, cioè copia il valore all'import.
    # Sostituire il solo `license` lascerebbe la verifica delle liste di revoca sulla
    # chiave reale — stesso rilievo per cui la fixture dei test ne patcha due.
    _lic.LICENSE_PUBLIC_KEY_HEX = pubblica
    _rev.LICENSE_PUBLIC_KEY_HEX = pubblica

    # Importato QUI e non in testa: `license_manager` è il tool di firma, e tenerlo fuori
    # dagli import di modulo rende evidente che serve solo a questo passaggio.
    from license_manager import core

    identificativo = hwid.hardware_id()
    if not hwid.is_identifiable(identificativo):
        raise SystemExit(
            f"hardware non identificabile su questa macchina ({identificativo}): una licenza "
            "legata a un hardware cieco varrebbe su tutte le macchine anonime, quindi non la "
            "emetto. Gli screenshot vanno scattati dove l'hardware id è leggibile.")

    percorso = license_store.license_state_path(config_store.config_dir())

    # PRIMA di scrivere: la licenza vera, se c'è, va messa al riparo e rimessa a posto in
    # uscita. `atexit` copre l'uscita normale e SystemExit; i due segnali coprono un kill
    # gentile. Un SIGKILL non lo copre nessuno — per quello il backup ha un nome esplicito e
    # `preserva_licenza_esistente` si rifiuta di sovrascriverlo alla corsa dopo.
    backup = preserva_licenza_esistente(percorso)
    if backup:
        # Solo il NOME del file, non il path assoluto: questo output finisce nei log dei job e
        # negli artifact, dove un path rivelerebbe username e struttura della macchina
        # (rilievo GPT-5.5). Chi deve rimetterla a posto sa già in che cartella guardare.
        print(f"licenza esistente messa al riparo in «{pathlib.Path(backup).name}» "
              "(cartella dati dell'app) — verrà rimessa a posto all'uscita")

    adesso = int(time.time())
    token = core.issue_license(LICENSE_TEST_SEED_HEX, INTESTATARIO, GIORNI, identificativo, adesso)
    license_store.save_license(percorso, token, adesso)

    # La pulizia si registra SEMPRE, non solo quando c'era una licenza da rimettere (rilievo
    # Claude Fable 5). Senza il ramo `else` la licenza di prova restava sul disco per sempre
    # sulla macchina di documentazione tipica — quella SENZA licenza — e l'app di produzione la
    # rifiutava: da «non attivato» a «licenza non valida», cioè peggio di prima.
    if backup:
        atexit.register(ripristina_licenza, backup, percorso)
    else:
        atexit.register(rimuovi_licenza_di_prova, percorso, token)
    for sig in (signal.SIGTERM, signal.SIGINT):
        _installa_ripristino_su_segnale(sig)

    return identificativo


if __name__ == "__main__":
    hw = _attiva_licenza_di_prova()
    # L'hardware id NON si stampa intero: questo output finisce nei log dei job e negli
    # artifact, ed è un identificativo della macchina. Il prefisso basta a capire che è stato
    # letto davvero (rilievo GPT-5.5 sulla #310).
    print(f"licenza di PROVA attivata ({GIORNI} giorni, hardware {hw[:8]}…) — solo per gli "
          "screenshot")
    # `run_name="__main__"` così `main.py` esegue il suo blocco di avvio esattamente come
    # quando lo si lancia a mano: gli screenshot devono mostrare l'app vera, non una sua
    # variante importata come modulo.
    runpy.run_path(str(_RADICE / "main.py"), run_name="__main__")
