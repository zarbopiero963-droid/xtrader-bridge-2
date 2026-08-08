"""P3-39 audit #76 — constraints pinnate per i job di TEST.

Bug: i job di test installavano `pip install -r requirements-dev.txt` con soli FLOOR
`>=` — una release breaking di una dipendenza (o di una transitiva) upstream faceva
diventare rossi TUTTI i PR insieme, nello stesso momento, senza alcun cambiamento nel
repo. Fix: `requirements-dev.lock` (pin `==` generati con pip-compile su Linux+3.11,
stessa piattaforma dei job ubuntu) usato come constraints (`-c`) in pr-checks,
commit-gate e windows-tests: l'upgrade delle dipendenze diventa un atto deliberato
(rigenerare il lock in un PR dedicato), mai una sorpresa.

Questi test difendono: esistenza/forma del lock, copertura di TUTTE le dipendenze
top-level, coerenza coi floor di sicurezza di `requirements.in`, e il wiring `-c`
nei workflow (regex su testo reale, pattern `test_workflow_pins`)."""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_WF_DIR = _ROOT / ".github" / "workflows"

# I workflow di test che DEVONO installare con le constraints.
# `merge-simulation.yml` aggiunto per il finding P3-ci2 della #114: girava senza `-c` e
# senza i `.lock` nella cache-key. Era sfuggito proprio perché questa lista non lo
# includeva — il guard esisteva già ed era giusto, semplicemente non guardava lì.
_TEST_WORKFLOWS = ("pr-checks.yml", "commit-gate.yml", "windows-tests.yml",
                   "merge-simulation.yml")

# Il job notturno che builda l'EXE non usa le constraints ma il lock HASHATO: compila un
# artefatto distribuibile, quindi ha bisogno della garanzia più forte (`--require-hashes`),
# non solo di versioni pinnate. Stesso trattamento di `build.yaml` / `build-license-manager`.
_HARD_BUILD_WORKFLOW = "merge-simulation-hard.yml"

# ── Riconoscimento degli install, per CONTENUTO e non per posizione ─────────────────────────────
# Storia di questo guard, che vale più della sua implementazione: nato nel #76 come confronto di
# sottostringa esatta, ha collezionato quattro cecità diverse, ognuna trovata da un reviewer
# diverso — il comando spezzato con `\`, la metà positiva rimasta rigida, i flag ammessi
# asimmetrici fra le due metà, e infine (CodeRabbit + GPT-5.5 #165, indipendentemente) le
# opzioni con valore e quelle scritte DOPO `-r`.
#
# Ogni giro allargava la regex di un pezzo, e il difetto ricompariva altrove. Il problema non
# erano i singoli flag: era che il pattern pretendeva un ORDINE. Un comando `pip install` è un
# insieme di argomenti, non una sequenza fissa — quindi la domanda giusta non è «combacia con
# questa forma?» ma «installa requirements-dev.txt? e allora cita anche il lock?».
#
# Riconoscere per contenuto rende irrilevanti ordine, numero e valore delle opzioni, e non ha
# più nulla da allargare al prossimo flag che qualcuno userà.
# Il confronto è su ARGOMENTI, non su sottostringhe (rilievo GPT-5.5 #165): `-c` seguito da
# `requirements-dev.lock.bak` contiene la sottostringa del lock giusto pur puntando a un file
# diverso, e un `# -c requirements-dev.lock` in coda è solo un commento shell. Entrambi facevano
# passare per "costretto" un install che pip esegue senza constraints.
_REQ_OPTS = ("-r", "--requirement")
_CONSTRAINT_OPTS = ("-c", "--constraint")
_DEV_REQ_FILE = "requirements-dev.txt"
_DEV_LOCK_FILE = "requirements-dev.lock"

# TUTTI i lock del repo, non solo quello dei test (#319): i due lock di BUILD decidono cosa
# finisce dentro l'eseguibile, quindi i guard sui floor devono valere prima di tutto per loro.
_LOCK_FILES = (_DEV_LOCK_FILE, "requirements-build.lock", "requirements-build-linux.lock")


def _srotola_folded(testo: str) -> str:
    """Ricongiunge i blocchi YAML `run: >` in una riga sola.

    È **semantica YAML**, non un'euristica: in uno scalare *folded* (`>`) le righe successive
    sono un unico comando, in uno *literal* (`|`) sono comandi distinti. Trattarli allo stesso
    modo rendeva invisibile al guard un install nudo scritto in forma folded (GPT-5.5 #165) —
    il fallimento peggiore per un controllo di supply-chain, perché silenzioso."""
    righe, out, i = testo.splitlines(), [], 0
    while i < len(righe):
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*>[-+]?\s*$", righe[i])
        if not m:
            out.append(righe[i])
            i += 1
            continue
        indent, blocco, i = len(m.group(1)), [], i + 1
        while i < len(righe) and (not righe[i].strip()
                                  or len(righe[i]) - len(righe[i].lstrip()) > indent):
            blocco.append(righe[i].strip())
            i += 1
        out.append(f"{m.group(0).rstrip()} " + " ".join(x for x in blocco if x))
    return "\n".join(out)


# Separatori di comando: due `pip install` sulla stessa riga sono due comandi DISTINTI, e le
# opzioni dell'uno non valgono per l'altro (GPT-5.5 #165). Senza questo split,
# `pip install -r requirements-dev.txt && pip install -c requirements-dev.lock altro` passava
# per costretto — il `-c` del secondo comando copriva l'install nudo del primo.
_SEPARATORI_SHELL = re.compile(r"&&|\|\||;|\|")


def _comandi_pip(testo: str):
    """I comandi `pip install` del testo, come LISTE DI ARGOMENTI.

    Ricongiunge le continuazioni `\\` e i blocchi folded, separa i comandi concatenati, poi
    tronca al primo `#`: tutto ciò che segue è un commento shell, non un argomento che pip
    riceve."""
    unito = re.sub(r"\\\n\s*", " ", _srotola_folded(testo))
    for riga in unito.splitlines():
        for pezzo in _SEPARATORI_SHELL.split(riga):
            if "pip install" not in pezzo:
                continue
            args = []
            for tok in pezzo.split():
                if tok.startswith("#"):
                    break
                args.append(tok)
            yield args


def _usa_file(args, opzioni, atteso: str) -> bool:
    """True se fra gli argomenti c'è `<opzione> <atteso>` (o `--opzione=<atteso>`), confrontando
    il nome del file per INTERO."""
    for i, tok in enumerate(args):
        if tok in opzioni and i + 1 < len(args) and args[i + 1] == atteso:
            return True
        if tok.startswith("--") and "=" in tok:
            nome, _, valore = tok.partition("=")
            if nome in opzioni and valore == atteso:
                return True
    return False


def _install_nudo(testo: str) -> list:
    """Install di `requirements-dev.txt` che NON citano le constraints — la cosa da vietare."""
    return [" ".join(a) for a in _comandi_pip(testo)
            if _usa_file(a, _REQ_OPTS, _DEV_REQ_FILE)
            and not _usa_file(a, _CONSTRAINT_OPTS, _DEV_LOCK_FILE)]


def _install_costretto(testo: str) -> bool:
    """True se esiste almeno un install di `requirements-dev.txt` CON le constraints."""
    return any(_usa_file(a, _REQ_OPTS, _DEV_REQ_FILE)
               and _usa_file(a, _CONSTRAINT_OPTS, _DEV_LOCK_FILE)
               for a in _comandi_pip(testo))


def _lock_pins(nome: str = _DEV_LOCK_FILE):
    """I pin `pkg==ver` di un lockfile, indicizzati per nome normalizzato.

    Parametrizzato sul file (#319): serviva anche per i due lock di BUILD, che hanno la
    stessa forma `pkg==ver` ma con la continuazione ` \\` e le righe `--hash=` sotto.
    Prima leggeva solo `requirements-dev.lock` — ed è per questo che i guard sui floor
    coprivano un lock su tre."""
    pins = {}
    for line in (_ROOT / nome).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # `--hash=sha256:...` NON è un pin: va scartata prima del test su `==`, altrimenti
        # nei lock hashati entrerebbe come pacchetto fantasma.
        if not line or line.startswith(("#", "--hash")):
            continue
        if line.endswith("\\"):          # continuazione dei lock con hash
            line = line[:-1].strip()
        if "==" not in line:
            continue
        name, ver = line.split("==", 1)
        # via l'eventuale environment marker (es. `; sys_platform == 'win32'`):
        # i suoi digit corromperebbero il confronto di versione (CodeRabbit #88).
        ver = ver.split(";", 1)[0]
        pins[name.strip().lower().replace("_", "-")] = ver.strip()
    return pins


def _floors():
    """I FLOOR `>=` dichiarati nella catena single-source, in un posto solo (regola 3).

    Erano inline dentro il test dei floor; ora li leggono tre test parametrizzati, e
    duplicarli sarebbe la divergenza-futura che la regola 3 vieta."""
    floors = {}
    for fname in ("requirements.in", "requirements-dev.txt"):
        for line in (_ROOT / fname).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # (?:\[...\])? — tollera gli extras (es. `pkg[extra]>=1.0`, CodeRabbit #88)
            m = re.match(r"^([A-Za-z0-9._-]+)(?:\[[^\]]+\])?\s*>=\s*([0-9.]+)", line)
            if m:
                floors[m.group(1).lower().replace("_", "-")] = m.group(2)
    return floors


def _vtuple(ver):
    return tuple(int(p) for p in re.findall(r"\d+", ver)[:3])


def test_lock_esiste_ed_e_pinnato():
    pins = _lock_pins()
    assert len(pins) >= 10, "requirements-dev.lock: attesi pin == per runtime+test+transitive"
    header = (_ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "autogenerated by pip-compile" in header, (
        "requirements-dev.lock: deve restare autogenerato (mai editato a mano)")
    assert "--hash" not in header, (
        "requirements-dev.lock: niente hash — è usato come constraints (-c), e pip "
        "rifiuta constraints hashate; il lock hashato resta quello di build")


def test_lock_copre_tutte_le_top_level():
    """Ogni dipendenza top-level di requirements.in e requirements-dev.txt deve avere il
    suo pin: una top-level fuori dal lock resterebbe a floor (proprio il bug P3-39)."""
    pins = _lock_pins()
    top = set()
    for fname in ("requirements.in", "requirements-dev.txt"):
        for line in (_ROOT / fname).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-r")):
                top.add(re.split(r"[><=!\[;]", line)[0].strip().lower().replace("_", "-"))
    missing = top - set(pins)
    assert not missing, f"top-level senza pin nel lock: {sorted(missing)}"


@pytest.mark.parametrize("lock_name", _LOCK_FILES)
def test_lock_rispetta_i_floor_di_sicurezza(lock_name):
    """I pin devono soddisfare i FLOOR `>=` di requirements.in E requirements-dev.txt
    (review GPT #88: anche una dipendenza dev può avere un floor di sicurezza) — sono
    vincoli di SICUREZZA: h11>=0.16 esclude una CVE, ptb>=21 esclude h11 vulnerabile:
    un lock rigenerato male che retrocedesse sotto un floor deve fallire qui.

    Parametrizzato sui TRE lock (#319). Prima guardava solo `requirements-dev.lock`, cioè
    proprio il lock che NON finisce dentro l'eseguibile: i due lock di build — quelli che
    decidono cosa gira sul PC del proprietario — non erano controllati da nessuno. Il floor
    è un vincolo di sicurezza: se vale per i job di test, a maggior ragione vale per l'EXE."""
    pins = _lock_pins(lock_name)
    floors = _floors()
    assert floors, "requirements.in: attesi floor >= (vincoli di sicurezza)"
    for name, floor in floors.items():
        assert name in pins, f"{lock_name}: {name} ha un floor di sicurezza ma nessun pin"
        assert _vtuple(pins[name]) >= _vtuple(floor), (
            f"{lock_name}: {name} pinnato a {pins[name]}, sotto il floor >={floor}")


def test_i_lock_concordano_sulla_versione_del_toolkit_grafico():
    """I tre lock devono pinnare la STESSA `customtkinter` — #319.

    Bug reale, trovato consumando due giorni di indagine sull'ipotesi sbagliata. Il lock di
    build Windows era stato ereditato dal repository PRECEDENTE (i suoi commenti dicevano
    ancora `D:\\a\\xtrader-bridge\\xtrader-bridge\\`) e lì era stato generato prima che
    uscisse la 6.0.0. `pip-compile` senza `--upgrade` tratta il file di output esistente
    come preferenza e tiene i pin che soddisfano ancora i vincoli: con `customtkinter>=5.2.2`
    la 5.2.2 restava valida, quindi ogni rigenerazione riconfermava sé stessa. I lock Linux
    e dev, creati da zero in questo repo, avevano invece 6.0.0.

    Risultato: l'EXE girava su 5.2.2 mentre l'INTERA suite lo esercitava su 6.0.0 — e le due
    versioni differiscono proprio dove serviva, perché la 5.2.2 non ha `_check_if_valid_scroll`
    (l'isolamento delle scrollable annidate). Ogni misura fatta sotto Xvfb riguardava una
    libreria diversa da quella installata sul PC del proprietario.

    Il toolkit grafico è un wheel universale `py3-none-any`: non c'è ragione di piattaforma
    perché i tre lock divergano, e se divergono il difetto è invisibile ai test per costruzione.
    Questo guard è l'unica cosa che lo rende visibile senza rileggere tre file a mano."""
    versioni = {nome: _lock_pins(nome).get("customtkinter") for nome in _LOCK_FILES}
    mancanti = [n for n, v in versioni.items() if v is None]
    assert not mancanti, f"customtkinter non pinnato in: {mancanti}"
    assert len(set(versioni.values())) == 1, (
        "i lock divergono sulla versione di customtkinter → l'EXE gira un toolkit che i test "
        f"non esercitano mai: {versioni}")


def test_ci_installa_con_le_constraints():
    """Ogni install di requirements-dev.txt nei workflow di test deve avere
    `-c requirements-dev.lock`, e la cache-key deve includere i .lock (senza, un
    lock rigenerato riuserebbe la cache pip stantia)."""
    for name in _TEST_WORKFLOWS:
        text = (_WF_DIR / name).read_text(encoding="utf-8")
        nudi = _install_nudo(text)
        assert not nudi, f"{name}: install di requirements-dev.txt SENZA constraints → {nudi}"
        assert _install_costretto(text), (
            f"{name}: nessun install con constraints trovato")
        assert "requirements*.lock" in text, (
            f"{name}: cache-dependency-path senza requirements*.lock")


# ── CI-1 (#114 P2): il job notturno che builda l'EXE ────────────────────────────────────────────
def test_il_job_notturno_builda_da_dipendenze_pinnate_e_hashate():
    """CI-1: `merge-simulation-hard` compila un EXE su windows-latest ogni notte.

    Installava `pip install -r requirements-dev.txt pyinstaller httpx`: nessun lock, nessun
    hash, e `pyinstaller`/`httpx` senza alcun vincolo di versione. Un artefatto distribuibile
    costruito da dipendenze che possono cambiare da sola una notte all'altra — mentre il lock
    hashato per Windows (`requirements-build.lock`, che contiene pyinstaller e httpx) era già
    nel repo ed era già usato da `build.yaml` e `build-license-manager.yaml`.

    Serve la garanzia FORTE (`--require-hashes`), non le sole constraints: qui non si tratta di
    stabilizzare la CI ma di sapere cosa finisce dentro l'eseguibile."""
    text = (_WF_DIR / _HARD_BUILD_WORKFLOW).read_text(encoding="utf-8")

    assert "--require-hashes -r requirements-build.lock" in text, (
        f"{_HARD_BUILD_WORKFLOW}: l'EXE notturno deve essere buildato dal lock HASHATO")

    # Il vecchio install nudo non deve tornare, in nessuna delle sue forme.
    nudi = _install_nudo(text)
    assert not nudi, (
        f"{_HARD_BUILD_WORKFLOW}: install non pinnato reintrodotto → {nudi}")

    assert "requirements*.lock" in text, (
        f"{_HARD_BUILD_WORKFLOW}: cache-dependency-path senza requirements*.lock — un lock "
        "rigenerato riuserebbe la cache pip stantia")


@pytest.mark.parametrize("riga", [
    "      - run: pip install -r requirements-dev.txt",
    "      - run: pip install -r requirements-dev.txt pyinstaller httpx",
    "      - run: pip install --upgrade -r requirements-dev.txt",
    # Continuazione YAML: lo stesso difetto scritto su due righe (rilievo Fable #165).
    "      - run: pip install \\\n          -r requirements-dev.txt pyinstaller",
    "      - run: pip install --upgrade \\\n          -r requirements-dev.txt",
    # Forma `python -m pip`, usata altrove nel repo (rilievo GPT-5.5 #165): è già coperta
    # perché il pattern aggancia la sottostringa `pip install`, ma senza un test la
    # copertura resterebbe accidentale — e la prossima riscrittura potrebbe perderla.
    "      - run: python -m pip install -r requirements-dev.txt",
    "      - run: python -m pip install \\\n          -r requirements-dev.txt",
    # Flag arbitrario, non solo `--upgrade`: prima il pattern conosceva quel singolo flag,
    # quindi un install nudo con QUALSIASI altra opzione sarebbe passato (GPT-5.5 #165).
    "      - run: pip install --disable-pip-version-check -r requirements-dev.txt",
    # Opzione CON VALORE — es. un mirror pip privato (CodeRabbit + GPT-5.5 #165). La regex
    # posizionale si fermava al valore e perdeva il match: install nudo invisibile al guard.
    "      - run: pip install --index-url https://mirror.interno -r requirements-dev.txt",
    # Opzioni DOPO il requirements (CodeRabbit #165): stesso comando, ordine diverso.
    "      - run: pip install -r requirements-dev.txt --disable-pip-version-check",
    # `-c` che punta a un file DIVERSO ma con lo stesso prefisso (GPT-5.5 #165): pip non usa
    # il lock, e un confronto per sottostringa lo scambiava per install costretto.
    "      - run: pip install -r requirements-dev.txt -c requirements-dev.lock.bak",
    # `-c` dentro un COMMENTO shell: pip non lo riceve affatto.
    "      - run: pip install -r requirements-dev.txt # -c requirements-dev.lock",
    # Blocco YAML *folded*: le righe sono UN comando solo, e senza srotolarlo l'install nudo
    # diventava invisibile al guard — il fallimento peggiore, perché silenzioso.
    "      - run: >\n          pip install\n          -r requirements-dev.txt",
    # Blocco *literal*: righe = comandi DISTINTI, quindi il `-c` di quella dopo non salva
    # l'install nudo di quella prima.
    "      - run: |\n          pip install -r requirements-dev.txt\n"
    "          pip install -c requirements-dev.lock altro",
    # Comandi CONCATENATI sulla stessa riga (GPT-5.5 #165): stessa logica del blocco literal —
    # sono due comandi, e le opzioni del secondo non valgono per il primo.
    "      - run: pip install -r requirements-dev.txt && pip install -c requirements-dev.lock x",
    "      - run: pip install -r requirements-dev.txt ; echo -c requirements-dev.lock",
])
def test_il_guard_riconosce_tutte_le_forme_dell_install_nudo(riga):
    """Il guard è a sua volta testato, perché una regex che non morde è indistinguibile da
    un repository sano.

    Prima di questo giro il pattern pretendeva tutto su una riga: bastava spezzare il comando
    con un `\\` per reintrodurre l'install non pinnato passando i controlli."""
    assert _install_nudo(riga), f"forma non intercettata: {riga!r}"


@pytest.mark.parametrize("riga", [
    "      - run: pip install -r requirements-dev.txt -c requirements-dev.lock",
    "      - run: pip install \\\n          -r requirements-dev.txt \\\n          -c requirements-dev.lock",
    "      - run: python -m pip install --require-hashes -r requirements-build.lock",
])
def test_il_guard_non_segnala_gli_install_corretti(riga):
    """L'altra metà: un guard che grida su tutto viene disattivato entro una settimana."""
    assert not _install_nudo(riga), f"falso positivo su: {riga!r}"


@pytest.mark.parametrize("riga", [
    "      - run: pip install -r requirements-dev.txt -c requirements-dev.lock",
    "      - run: pip install \\\n          -r requirements-dev.txt \\\n          -c requirements-dev.lock",
    "      - run: python -m pip install -r requirements-dev.txt -c requirements-dev.lock",
    # Flag fra `pip install` e `-r`: il guard negativo li tollerava, il positivo no
    # (asimmetria rilevata da GPT-5.5 #165). Un install COSTRETTO ma con `--upgrade`
    # risultava insieme "non sbagliato" e "non giusto" → CI rossa su codice sicuro.
    "      - run: pip install --upgrade -r requirements-dev.txt -c requirements-dev.lock",
    "      - run: python -m pip install --disable-pip-version-check \\\n"
    "          -r requirements-dev.txt -c requirements-dev.lock",
    # Constraints DOPO altre opzioni, e opzione con valore in mezzo (CodeRabbit #165):
    # comandi sicuri che il matching posizionale bocciava.
    "      - run: pip install -r requirements-dev.txt --disable-pip-version-check "
    "-c requirements-dev.lock",
    "      - run: pip install --index-url https://mirror.interno "
    "-r requirements-dev.txt -c requirements-dev.lock",
    # Forma lunga con `=`: `--requirement=` / `--constraint=` sono equivalenti a `-r`/`-c`.
    "      - run: pip install --requirement=requirements-dev.txt "
    "--constraint=requirements-dev.lock",
    "      - run: python -m pip install --requirement=requirements-dev.txt "
    "--constraint=requirements-dev.lock",
    # Blocco folded corretto: srotolato diventa un comando con entrambe le opzioni.
    "      - run: >\n          pip install\n          -r requirements-dev.txt\n"
    "          -c requirements-dev.lock",
])
def test_il_check_positivo_accetta_anche_le_forme_spezzate(riga):
    """Rilievo GPT-5.5 (#165): il riconoscimento dell'install CORRETTO era un confronto di
    sottostringa esatta su una riga sola, quindi un workflow sicuro ma scritto su più righe
    veniva bocciato. Un guard che boccia il codice giusto costa quanto uno che lascia passare
    quello sbagliato: entrambi finiscono per essere disattivati."""
    assert _install_costretto(riga), f"forma corretta non riconosciuta: {riga!r}"


def test_il_lock_di_build_copre_davvero_pyinstaller_e_httpx():
    """Il fix regge solo se il lock contiene ciò che l'install nudo aggiungeva a mano.

    Se una rigenerazione futura togliesse `pyinstaller` da `requirements-build.lock`, il job
    notturno fallirebbe all'improvviso in fase di build — e il motivo (una riga sparita da un
    file autogenerato) sarebbe tutt'altro che ovvio a chi guarda il log."""
    lock = (_ROOT / "requirements-build.lock").read_text(encoding="utf-8")
    for pkg in ("pyinstaller", "httpx", "pytest"):
        assert re.search(rf"(?mi)^{pkg}==", lock), (
            f"requirements-build.lock: manca il pin di {pkg}, che il job notturno usa")
    assert "--hash=" in lock, (
        "requirements-build.lock deve restare hashato: senza hash `--require-hashes` fallisce")
