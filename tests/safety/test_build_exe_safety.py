"""Gate di sicurezza della build EXE personale (issue #86 PR-P13).

La build Windows (`.github/workflows/build.yaml`) deve produrre **solo** l'EXE personale
del bridge, senza includere segreti né certificati e senza un secondo «Admin EXE». La
compilazione vera (PyInstaller su Windows) NON gira in questa CI Linux: qui si verifica in
modo deterministico e offline che il **workflow** rispetti le regole non negoziabili
dell'issue:

- una sola compilazione PyInstaller (nessun Admin/secondo EXE);
- nessun `--add-data`/`--add-binary` che includa certificati, chiavi, `.env`, `config.json`,
  DB locale o token (solo il dizionario ufficiale è ammesso nel bundle);
- i test girano PRIMA di compilare l'EXE (una build non parte su codice rotto);
- `data/` non contiene file sensibili che `--collect-all`/`--add-data` potrebbero includere.
"""

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILD_YAML = os.path.join(_REPO_ROOT, ".github", "workflows", "build.yaml")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")
_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Estensioni/nomi vietati nel bundle dell'EXE (segreti, credenziali, artefatti locali).
_FORBIDDEN_BUNDLE = re.compile(
    r"\.(crt|pem|key|env|p12|pfx|db|sqlite|sqlite3|log|zip)\b|config\.json|secret|token",
    re.IGNORECASE)


def _build_yaml() -> str:
    with open(_BUILD_YAML, "r", encoding="utf-8") as fh:
        return fh.read()


def test_build_yaml_esiste():
    assert os.path.isfile(_BUILD_YAML), "manca .github/workflows/build.yaml"


def test_una_sola_compilazione_pyinstaller():
    # Esattamente UNA invocazione PyInstaller: niente secondo EXE (es. Admin).
    text = _build_yaml()
    n = len(re.findall(r"(?m)^\s*pyinstaller\b", text))
    assert n == 1, f"attesa UNA sola build PyInstaller, trovate {n}"
    assert "--onefile" in text          # EXE singolo personale


def test_nessun_admin_exe():
    # Nessun riferimento a una build/EXE «Admin» in alcun workflow.
    for name in os.listdir(_WORKFLOWS_DIR):
        if not name.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(_WORKFLOWS_DIR, name), "r", encoding="utf-8") as fh:
            low = fh.read().casefold()
        assert "admin exe" not in low
        assert "admin.exe" not in low
        # niente pyinstaller che nomina un target "admin"
        assert not re.search(r"pyinstaller[^\n]*admin", low)


def test_adddata_non_include_segreti_o_certificati():
    # Ogni --add-data "SORG;DEST": la SORGENTE non deve essere un segreto/cert/artefatto.
    text = _build_yaml()
    entries = re.findall(r'--add-data\s+"([^"]+)"', text)
    assert entries, "atteso almeno un --add-data (il dizionario)"
    for entry in entries:
        # Split SOLO sul separatore PyInstaller usato da questo workflow Windows (`;`):
        # NON splittare su `:`, altrimenti una sorgente assoluta Windows tipo
        # `C:\secrets\client.pem;certs` verrebbe troncata a "C" e l'estensione segreta non
        # verrebbe mai rilevata (Codex). Su Windows il separatore SORG/DEST è sempre `;`.
        src = entry.split(";", 1)[0].strip()
        assert not _FORBIDDEN_BUNDLE.search(src), f"--add-data include un file vietato: {src!r}"
        # CSV ammesso SOLO il dizionario ufficiale.
        if src.lower().endswith(".csv"):
            assert src.replace("\\", "/") == "data/dizionario_xtrader.csv", \
                f"nel bundle è ammesso solo il dizionario, non {src!r}"


def test_nessun_add_binary_di_certificati():
    # Nessun --add-binary che trascini cert/chiavi nell'EXE.
    text = _build_yaml()
    for entry in re.findall(r'--add-binary\s+"([^"]+)"', text):
        assert not _FORBIDDEN_BUNDLE.search(entry), f"--add-binary include un file vietato: {entry!r}"


def test_test_eseguiti_prima_della_build():
    # I test (pytest) devono precedere la compilazione dell'EXE: una build non deve
    # partire su codice non testato. Si confronta lo step REALE `python -m pytest` con la
    # REALE invocazione di build (riga che inizia con `pyinstaller`), NON un semplice
    # substring "pytest"/"pyinstaller": un commento che cita entrambe le parole (es. il
    # commento sul lockfile) soddisferebbe falsamente il gate anche se lo step dei test
    # fosse rimosso o spostato dopo la build (Codex).
    text = _build_yaml()
    i_pytest = text.find("python -m pytest")
    m_build = re.search(r"(?m)^\s*pyinstaller\b", text)
    assert i_pytest != -1, "manca lo step reale dei test (`python -m pytest`)"
    assert m_build is not None, "manca la reale invocazione `pyinstaller`"
    assert i_pytest < m_build.start(), "i test devono girare PRIMA della build dell'EXE"


def test_data_dir_senza_file_sensibili():
    # La cartella bundle-abile `data/` non deve contenere segreti/cert/DB (li includerebbe
    # --add-data/--collect-all). Deve esserci il dizionario ufficiale. La scansione è
    # RICORSIVA (os.walk): un file annidato come `data/certs/client.key` o
    # `data/parsers/.env` finirebbe nel bundle se `data/` venisse impacchettata come
    # cartella, e `os.listdir` sul solo primo livello non lo vedrebbe (Codex).
    assert os.path.isdir(_DATA_DIR)
    found_dizionario = False
    for root, _dirs, files in os.walk(_DATA_DIR):
        for n in files:
            if n == "dizionario_xtrader.csv":
                found_dizionario = True
            rel = os.path.relpath(os.path.join(root, n), _DATA_DIR)
            assert not _FORBIDDEN_BUNDLE.search(n), f"file sensibile in data/: {rel!r}"
    assert found_dizionario, "manca data/dizionario_xtrader.csv"


def test_artifact_e_release_solo_un_exe():
    # L'upload artifact (`path:`) E la release (`files:`, softprops/action-gh-release)
    # devono pubblicare ESATTAMENTE un singolo .exe da dist/, non cartelle e non un secondo
    # eseguibile. Si controllano ENTRAMBI i canali: prima il gate leggeva solo `path:`,
    # lasciando il lato release non verificato; e accettava "almeno un" exe, così un
    # secondo `dist/Admin.exe` sarebbe passato (Codex).
    text = _build_yaml()
    artifact_exes = [p for p in re.findall(r"(?m)^\s*path:\s*(\S+)", text)
                     if p.lower().endswith(".exe")]
    release_exes = [p for p in re.findall(r"(?m)^\s*files:\s*(\S+)", text)
                    if p.lower().endswith(".exe")]
    assert len(artifact_exes) == 1, \
        f"atteso ESATTAMENTE un EXE nell'upload artifact, trovati {artifact_exes}"
    assert len(release_exes) == 1, \
        f"atteso ESATTAMENTE un EXE nella release, trovati {release_exes}"
    for p in artifact_exes + release_exes:
        assert p.startswith("dist/"), f"path EXE inatteso: {p!r}"
    # Difesa in profondità: nessun secondo eseguibile (es. dist/Admin.exe) referenziato da
    # NESSUNA parte del workflow — l'unico EXE pubblicabile è quello personale del bridge.
    all_exe = re.findall(r"dist/(\S+\.exe)", text)
    assert all_exe and all(e == "XTrader-Signal-Bridge.exe" for e in all_exe), \
        f"pubblicato un secondo EXE inatteso: {all_exe}"
