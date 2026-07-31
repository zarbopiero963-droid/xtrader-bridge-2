"""I redattori dei workflow di review devono redigere il seed Ed25519 — Issue #205.

Perché questo test esiste. I cinque workflow che mandano codice a un modello **esterno**
(OpenAI, Anthropic, OpenRouter) passano il testo da un redattore di segreti prima di spedirlo.
Nessuna delle sue copie riconosceva il **seed Ed25519**: la chiave che firma tutte le licenze,
l'unico segreto del sistema che non è sostituibile senza riemettere ogni licenza.

Perché il presidio è un test e non una fonte unica importabile. `tools/secret_policy.py` è la
fonte unica dei gate, ma questi cinque workflow **non fanno il checkout del repository** —
prendono il diff dalla GitHub Compare API — quindi sul runner non esiste alcun file da
importare. La condivisione a livello di codice è impossibile, e la forma più forte disponibile
è questo test: estrae le regex **reali** dai file YAML, le esegue, e diventa rosso se una delle
copie perde la copertura o se le cinque si allontanano fra loro.

Il test non confronta stringhe: **esegue** i pattern estratti, così non può essere soddisfatto
da una regex presente ma inefficace.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# I cinque workflow che spediscono testo a un modello esterno. Chi ne aggiunge un sesto senza
# il redattore lo scopre qui: `_lista_redazione` solleva invece di saltare in silenzio.
REDATTORI = (
    "pr-review-gpt55.yml",
    "pr-review-claude-fable5.yml",
    "pr-review-openrouter-fugu-ultra.yml",
    "claude-fable-full-repo-audit.yml",
    "manual-full-repo-ai-audit.yml",
)

# I due audit su tutto il repository hanno, oltre al redattore, un **rilevatore** che segnala i
# segreti come finding. Un seed esposto deve essere anche segnalato, non solo mascherato.
RILEVATORI = ("claude-fable-full-repo-audit.yml", "manual-full-repo-ai-audit.yml")

SEED_FINTO = "ab" * 32          # 64 hex: la forma esatta di un seed Ed25519 (32 byte)
SHA256_FINTO = "cd" * 32        # stessa forma, ma è un hash: NON deve essere redatto


def _blocco_python(nome: str) -> str:
    """Il sorgente Python annidato nello step bash del workflow (heredoc ``python3 <<'PY'``)."""
    doc = yaml.safe_load((WORKFLOWS / nome).read_text(encoding="utf-8"))
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []):
            s = step.get("run", "") or ""
            if "REDACTION" not in s:
                continue
            m = re.search(r"python3? <<'PY'\n(.*?)\nPY\n", s, re.S)
            if m:
                return m.group(1)
    raise AssertionError(f"{nome}: nessuno step con una lista di redazione")


def _pattern_della_lista(sorgente: str, nomi: tuple) -> list:
    """Le regex (stringhe) dei `re.compile(...)` dentro la lista chiamata come uno di `nomi`.

    Si passa per l'AST invece che per una regex sul testo: i pattern contengono virgolette
    escapate, e cercarli testualmente darebbe estrazioni parziali — cioè un test che *sembra*
    controllare e non controlla.
    """
    albero = ast.parse(sorgente)
    for nodo in ast.walk(albero):
        bersaglio = None
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1:
            bersaglio = nodo.targets[0]
        elif isinstance(nodo, ast.AnnAssign):     # `NOME: List[...] = [...]`
            bersaglio = nodo.target
        if not (isinstance(bersaglio, ast.Name) and bersaglio.id in nomi):
            continue
        trovati = []
        for chiamata in ast.walk(nodo.value):
            if (isinstance(chiamata, ast.Call)
                    and isinstance(chiamata.func, ast.Attribute)
                    and chiamata.func.attr == "compile"
                    and chiamata.args
                    and isinstance(chiamata.args[0], ast.Constant)
                    and isinstance(chiamata.args[0].value, str)):
                trovati.append(chiamata.args[0].value)
        if trovati:
            return trovati
    raise AssertionError(f"nessuna lista fra {nomi} con pattern compilati")


def _lista_redazione(nome: str) -> list:
    return _pattern_della_lista(_blocco_python(nome), ("REDACTIONS", "REDACTION_PATTERNS"))


def _lista_rilevamento(nome: str) -> list:
    return _pattern_della_lista(_blocco_python(nome), ("SECRET_PATTERNS",))


def _redigi(testo: str, pattern: list) -> str:
    """Applica i pattern come fa `redact()` nei workflow: sostituzione in cascata."""
    for p in pattern:
        testo = re.sub(p, "[REDACTED]", testo)
    return testo


# ────────────────────────────── il buco misurato (Issue #205) ──────────────────────────────

@pytest.mark.parametrize("workflow", REDATTORI)
@pytest.mark.parametrize("forma,testo", [
    ("signing_key.json", '  "seed": "%s",' % SEED_FINTO),
    ("backup (virgolette escapate)", '"{\\n  \\"seed\\": \\"%s\\"}"' % SEED_FINTO),
])
def test_il_seed_non_esce_mai_in_chiaro(workflow, forma, testo):
    """Il seed deve sparire dal testo spedito al modello, in ENTRAMBE le forme reali.

    La seconda forma è quella del backup completo, dove il file-chiave è annidato come stringa
    JSON e le virgolette sono escapate: un pattern scritto sulla sola forma in chiaro la
    mancherebbe — ed è proprio il file che il bug B3 riguardava.
    """
    ripulito = _redigi(testo, _lista_redazione(workflow))
    assert SEED_FINTO not in ripulito, (
        f"{workflow}: il seed sopravvive alla redazione nella forma «{forma}» → "
        "finirebbe in chiaro a un modello esterno")


@pytest.mark.parametrize("workflow", RILEVATORI)
def test_gli_audit_segnalano_un_seed_esposto(workflow):
    """Nei due audit su tutto il repository il seed non deve solo essere mascherato: deve essere
    **segnalato** come finding, altrimenti l'audit dichiara pulito un repo che espone la chiave
    di firma."""
    riga = '  "seed": "%s",' % SEED_FINTO
    assert any(re.search(p, riga) for p in _lista_rilevamento(workflow)), (
        f"{workflow}: nessun pattern del rilevatore riconosce un seed Ed25519 esposto")


# ─────────────────────────────────── le controprove ───────────────────────────────────

@pytest.mark.parametrize("workflow", REDATTORI)
def test_gli_hash_e_le_chiavi_pubbliche_restano_leggibili(workflow):
    """Un redattore troppo largo è un danno silenzioso: se cancellasse ogni sequenza di 64 hex
    svuoterebbe i lockfile (291 righe di hash pip) e la chiave **pubblica** embedded, cioè
    manderebbe al reviewer un diff mutilato — e le review peggiorerebbero senza che nessuno
    capisca perché. Solo il seed va redatto."""
    innocuo = ("    --hash=sha256:%s\n" % SHA256_FINTO
               + '  "public": "%s",\n' % SHA256_FINTO
               + SHA256_FINTO + "\n")
    ripulito = _redigi(innocuo, _lista_redazione(workflow))
    assert ripulito.count(SHA256_FINTO) == 3, (
        f"{workflow}: la redazione ha mangiato hash o chiavi pubbliche "
        f"(rimasti {ripulito.count(SHA256_FINTO)}/3)")


@pytest.mark.parametrize("workflow", REDATTORI)
def test_il_codice_che_parla_di_seed_resta_leggibile(workflow):
    """La decisione più delicata della Issue #205, fissata qui perché non si perda.

    La via ovvia era aggiungere `seed` all'alternanza generica (`api_key|token|secret|…`), che
    copre anche forme non esadecimali. **Misurato prima di tenerla: avrebbe redatto 30 righe in
    più del repository**, quasi tutte codice reale del License Manager — `seed = os.urandom(…)`
    sarebbe diventato `seed=[REDACTED]`. Si sarebbe cioè oscurato al reviewer proprio il modulo
    che custodisce la chiave, cioè quello dove la review serve di più, in cambio di una classe
    di segreti che **non esiste**: un seed è per costruzione 64 hex (`core._seed_from_hex` lo
    valida). Si è tenuto solo il pattern contestuale, che sul repo reale redige **zero** righe
    in più.

    Se qualcuno riaggiungesse la keyword, questo test lo direbbe.
    """
    codice = ("seed = os.urandom(_SEED_BYTES)\n"
              "seed_hex, public_hex = core.generate_keypair()\n"
              'il seed va salvato una volta sola\n')
    assert _redigi(codice, _lista_redazione(workflow)) == codice, (
        f"{workflow}: la redazione oscura codice ordinario che nomina il seed — "
        "il reviewer perderebbe di vista il License Manager")


@pytest.mark.parametrize("workflow", REDATTORI)
def test_i_segreti_gia_coperti_restano_coperti(workflow):
    """Controprova di non-regressione: aggiungere il seed non deve rompere le classi che il
    redattore copriva già. Segreti fittizi costruiti per concatenazione, così il sorgente di
    questo test non contiene un pattern in chiaro."""
    campioni = {
        "GitHub token": "ghp" + "_" + "C" * 36,
        "AWS": "AKI" + "A" + "1" * 16,
        "OpenAI": "sk-" + "D" * 24,
        "Telegram": "123456789" + ":" + "E" * 35,
    }
    pattern = _lista_redazione(workflow)
    for nome, valore in campioni.items():
        assert valore not in _redigi(f"x = {valore}", pattern), \
            f"{workflow}: {nome} non è più redatto — regressione"


def test_i_cinque_redattori_coprono_le_stesse_classi():
    """Il presidio contro la divergenza, che è il difetto strutturale della Issue #205.

    Le cinque copie non possono condividere codice (nessun checkout sul runner), quindi
    l'allineamento va verificato per **comportamento**: ogni copia deve redigere ogni campione.
    Se un domani qualcuno aggiungesse una classe a un solo file, questo test lo direbbe.

    Nota su ciò che il test **non** impone: le due varianti del pattern generico (i tre
    `pr-review-*` includono `cert` e non hanno lunghezza minima; i due `full-repo-audit` hanno
    `\\b` e `{12,}`) restano diverse **di proposito** — nei full-repo la stessa espressione
    alimenta anche il rilevatore, dove la precisione conta più della larghezza. La differenza è
    dichiarata qui invece di essere accidentale.
    """
    campioni = ['  "seed": "%s",' % SEED_FINTO,
                "x = " + "ghp" + "_" + "C" * 36,
                "x = " + "AKI" + "A" + "1" * 16]
    for campione in campioni:
        esiti = {w: campione != _redigi(campione, _lista_redazione(w)) for w in REDATTORI}
        assert all(esiti.values()), f"copertura non uniforme su {campione[:40]!r}: {esiti}"
