"""#278 — `math.isfinite` su un valore GREZZO di config: il quarto sito, mai allineato.

Un `int` di Python non ha limite di grandezza; un `float` sì. `math.isfinite(10**400)`
non risponde «no»: **solleva** `OverflowError`. Quindi ogni coercizione che passi da
`isfinite` prima di aver separato `int` da `float` trasforma un `config.json` **valido**
in un crash.

Tre dei quattro siti del predicato erano già stati corretti, con il motivo scritto nel
commento. Il quarto — `autostart.coerce_enabled`, il primo nominato dalla riga PR-E del
piano #194 — è rimasto indietro, e sta sul percorso di `load_config`: l'app non si apre
più, e nessun `.bak` viene creato perché il JSON non è corrotto, è solo enorme.

I test di questo file coprono tre livelli, perché il difetto era invisibile ai primi due:

1. **l'helper** — `coerce_enabled` non deve sollevare (era rosso solo qui, per #243);
2. **il chiamante** — `load_config` end-to-end, che è dove il difetto fa il danno: un
   test sul solo helper non avrebbe mostrato l'app che non parte;
3. **la classe** — nessuna funzione del pacchetto può far arrivare un `int` a
   `math.isfinite`, e i quattro siti devono concordare sul contratto numerico.
"""

import ast
import json
import math
import pathlib

import pytest

from xtrader_bridge import autostart, config_store, source_manager, validators

# Un int fuori dal range di `float` ma perfettamente rappresentabile in JSON.
ENORME = 10 ** 400


# ─────────────────────────────────────────────────────────────────────────────────────
# 1. L'helper
# ─────────────────────────────────────────────────────────────────────────────────────

def test_278_coerce_enabled_non_solleva_su_int_enorme():
    """Il gemello di `test_source_manager.py::test_enabled_int_enorme_non_crasha`, che
    era stato scritto «anche qui» ovunque tranne che qui.

    Il verso è quello dei due fratelli: un int enorme è un numero **esplicitamente
    non-zero**, esattamente come `2` o `-1`. Non è un allentamento del gate — restano
    a valle il token, la chat ammessa e la conferma per la modalità reale."""
    assert autostart.coerce_enabled(ENORME) is True
    assert autostart.coerce_enabled(-ENORME) is True


def test_278_i_non_finiti_restano_fail_closed():
    """Contro-guardia: correggere l'`OverflowError` non deve far passare `inf`/`nan`.
    Un numero non finito non è un «sì» esplicito, e su un toggle con default OFF la
    risposta giusta resta no."""
    for v in (float("inf"), float("-inf"), float("nan")):
        assert autostart.coerce_enabled(v) is False, v
    assert autostart.coerce_enabled(0) is False
    assert autostart.coerce_enabled(0.0) is False


# ─────────────────────────────────────────────────────────────────────────────────────
# 2. Il chiamante — dove il difetto fa il danno
# ─────────────────────────────────────────────────────────────────────────────────────

def test_278_load_config_apre_una_config_col_numero_enorme(tmp_path):
    """**Il test che conta.** `_migrate` chiama `autostart.is_enabled` per normalizzare
    `auto_start_listener`: con il difetto, `load_config` sollevava `OverflowError` e
    l'app non si apriva più.

    E non si apriva **senza rete di salvataggio**: il recupero da config corrotta
    scatta su un JSON illeggibile, mentre questo è valido — non c'è niente da
    recuperare, c'è un `float()` che esplode. Si verifica quindi anche che nessun
    `.bak` venga creato e che il file dell'utente resti dov'è."""
    p = tmp_path / "config.json"
    p.write_text('{"auto_start_listener": ' + "1" + "0" * 400 + "}", encoding="utf-8")

    cfg = config_store.load_config(str(p), sync_csv_language=False)

    assert cfg["auto_start_listener"] is True, "il valore va normalizzato a un bool vero"
    assert [f.name for f in tmp_path.iterdir()] == ["config.json"], (
        "nessun recupero doveva scattare: il JSON è valido")
    assert json.loads(p.read_text(encoding="utf-8")), "il file dell'utente resta leggibile"


def test_278_load_config_col_numero_enorme_a_zero_resta_spento(tmp_path):
    """Contro-guardia del precedente: la correzione non deve accendere l'auto-start
    per il solo fatto di non sollevare più. Uno zero resta uno zero."""
    p = tmp_path / "config.json"
    p.write_text('{"auto_start_listener": 0}', encoding="utf-8")

    cfg = config_store.load_config(str(p), sync_csv_language=False)

    assert cfg["auto_start_listener"] is False


def test_278_can_auto_start_non_solleva_col_numero_enorme():
    """L'altro chiamante di `is_enabled` sul percorso d'avvio (`app._start`,
    `app._maybe_auto_start`). Con il difetto sollevava **dopo** che la finestra era già
    aperta, cioè in un punto dove l'utente vede l'app morire senza spiegazione."""
    ok, motivo = autostart.can_auto_start({"auto_start_listener": ENORME})

    assert ok is False and "token" in motivo, (ok, motivo)   # manca il token: fail-closed


# ─────────────────────────────────────────────────────────────────────────────────────
# 3. La classe
# ─────────────────────────────────────────────────────────────────────────────────────

def _nomi_di_isfinite(albero):
    """I nomi con cui `math.isfinite` è raggiungibile **in questo modulo**.

    Non basta cercare la stringa `isfinite`: conta a quale nome è legata la funzione
    qui dentro. Le quattro forme che compaiono in Python reale —

        import math                          → math.isfinite(v)      (attributo)
        import math as m                     → m.isfinite(v)         (attributo, alias modulo)
        from math import isfinite            → isfinite(v)           (nome)
        from math import isfinite as _isf    → _isf(v)               (nome, alias funzione)
        from math import *                   → isfinite(v)           (nome, da star-import)

    Ritorna `(alias_del_modulo, nomi_diretti)`.

    Rilievo CodeRabbit sulla PR #279: la prima stesura accettava **solo** la forma ad
    attributo, quindi un modulo scritto con `from math import isfinite` sarebbe passato
    inosservato — e il docstring della guardia promette il contrario. Una guardia che
    dichiara più di quanto controlla è esattamente il difetto che questa PR corregge,
    ripetuto nella sua stessa guardia.

    Lo **star-import** è il rilievo di GPT-5.5 sullo stesso giro, e chiude un buco vero:
    misurato che `F403` **non** è nel `select` di default di ruff, quindi
    `from math import *` non viene fermato nemmeno dal linter del repository. Restava
    l'unica forma capace di far entrare il difetto in silenzio.

    Lo **shadowing** va nel verso opposto e va tolto, non aggiunto: se il modulo ridefinisce
    in casa un `isfinite`, le sue chiamate non sono più quelle di `math` e segnalarle
    sarebbe un falso positivo. Un falso positivo si annuncia da solo — qualcuno vede il
    rosso e guarda — mentre un falso negativo tace; ma una guardia rumorosa si impara a
    ignorare, ed è il modo in cui smette di servire.
    """
    moduli, diretti, propri = set(), set(), set()
    for n in ast.walk(albero):
        if isinstance(n, ast.Import):
            moduli |= {a.asname or a.name for a in n.names if a.name == "math"}
        elif isinstance(n, ast.ImportFrom) and n.module == "math":
            for a in n.names:
                if a.name == "isfinite":
                    diretti.add(a.asname or a.name)
                elif a.name == "*":
                    diretti.add("isfinite")
    for n in albero.body:                      # solo il livello di modulo: qui avviene lo shadow
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            propri.add(n.name)
        elif isinstance(n, ast.Assign):
            propri |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return moduli, diretti - propri


def _siti_isfinite_su_int():
    """Ogni funzione del pacchetto in cui un `math.isfinite(x)` può ricevere un `x`
    che il codice stesso ammette essere un `int`.

    Il difetto **non** è «chiamare `isfinite`»: è chiamarlo in un ramo che accetta
    anche gli interi. La forma sicura separa i due tipi (`isinstance(x, int)` prima,
    `isinstance(x, float)` poi); quella difettosa li unisce in una tupla.

    Questa distinzione è il punto: la scansione della #243 cercava i `try` con
    `float()` e non poteva vedere un `isfinite` nudo; una scansione che si accontenti
    di trovare la parola «float» dentro un `isinstance` marca **verde** proprio il
    sito rotto, perché `(int, float)` contiene `float`. Qui si guarda la tupla.
    """
    fuori = []
    radici = [pathlib.Path("xtrader_bridge"), pathlib.Path("license_manager")]
    for radice in radici:
        for p in sorted(radice.rglob("*.py")):
            src = p.read_text(encoding="utf-8")
            if "isfinite" not in src:
                continue
            albero = ast.parse(src)
            moduli, diretti = _nomi_di_isfinite(albero)

            def _e_isfinite(f, _moduli=moduli, _diretti=diretti):
                if isinstance(f, ast.Attribute):
                    return (f.attr == "isfinite" and isinstance(f.value, ast.Name)
                            and f.value.id in _moduli)
                return isinstance(f, ast.Name) and f.id in _diretti

            for fn in [n for n in ast.walk(albero)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                # nomi passati a isfinite() dentro questa funzione
                argomenti = {ast.unparse(c.args[0])
                             for c in ast.walk(fn)
                             if isinstance(c, ast.Call) and _e_isfinite(c.func) and c.args}
                if not argomenti:
                    continue
                # ...e quei nomi sono ammessi come int da un isinstance con tupla?
                for c in ast.walk(fn):
                    if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                            and c.func.id == "isinstance" and len(c.args) == 2):
                        continue
                    if ast.unparse(c.args[0]) not in argomenti:
                        continue
                    tipi = c.args[1]
                    nomi = ([ast.unparse(e) for e in tipi.elts]
                            if isinstance(tipi, ast.Tuple) else [ast.unparse(tipi)])
                    if "int" in nomi and "float" in nomi:
                        fuori.append(f"{p}:{c.lineno} {fn.name}() isinstance(..., {nomi})")
    return fuori


def test_278_nessun_isfinite_puo_ricevere_un_int(monkeypatch):
    """Guardia di classe. Un `int` di Python è **sempre** finito, per quanto grande:
    domandarlo a `math.isfinite` non è solo inutile, è il modo di trasformare una
    config valida in un crash.

    Vale su tutto il pacchetto, non sui quattro siti noti: un quinto scritto domani
    nella stessa forma diventa rosso qui, senza che nessuno debba ricordarsi di
    aggiungerlo a un elenco."""
    monkeypatch.chdir(pathlib.Path(__file__).resolve().parents[2])

    siti = _siti_isfinite_su_int()

    assert siti == [], (
        "un `math.isfinite` può ricevere un int (OverflowError su 10**400):\n  "
        + "\n  ".join(siti)
        + "\n\nSepara i tipi: `isinstance(x, int)` decide senza convertire, "
          "`isinstance(x, float)` è l'unico ramo che può chiedere la finitezza.")


def test_278_la_guardia_di_classe_vede_davvero_il_difetto(tmp_path, monkeypatch):
    """Contro-guardia della guardia: un test che scandisce dei file e non trova nulla
    è indistinguibile da uno che non scandisce niente. Qui si costruisce il difetto e
    si pretende che venga trovato."""
    finto = tmp_path / "xtrader_bridge"
    finto.mkdir()
    (finto / "difettoso.py").write_text(
        "import math\n"
        "def coercizione(val):\n"
        "    if isinstance(val, (int, float)):\n"
        "        return math.isfinite(val) and val != 0\n"
        "    return False\n", encoding="utf-8")
    (finto / "sano.py").write_text(
        "import math\n"
        "def coercizione(val):\n"
        "    if isinstance(val, int):\n"
        "        return val != 0\n"
        "    if isinstance(val, float):\n"
        "        return math.isfinite(val) and val != 0\n"
        "    return False\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    siti = _siti_isfinite_su_int()

    assert len(siti) == 1, siti
    assert "difettoso.py" in siti[0] and "coercizione" in siti[0]


# Le quattro forme con cui `math.isfinite` è raggiungibile in Python reale.
FORME_ISFINITE = (
    ("modulo", "import math", "math.isfinite(v)"),
    ("modulo_alias", "import math as m", "m.isfinite(v)"),
    ("nome", "from math import isfinite", "isfinite(v)"),
    ("nome_alias", "from math import isfinite as _isf", "_isf(v)"),
    ("star", "from math import *", "isfinite(v)"),
)


@pytest.mark.parametrize("etichetta,importazione,chiamata", FORME_ISFINITE)
def test_278_la_guardia_vede_TUTTE_le_forme_di_isfinite(
        etichetta, importazione, chiamata, tmp_path, monkeypatch):
    """Rilievo CodeRabbit sulla PR #279, ed era fondato.

    La prima stesura della guardia accettava **solo** `math.isfinite(...)` come
    chiamata ad attributo. Un modulo scritto con `from math import isfinite` avrebbe
    lo stesso identico difetto e sarebbe passato **verde** — mentre il docstring della
    guardia promette che «un quinto sito scritto domani nella stessa forma diventa
    rosso qui».

    Una guardia che dichiara più di quanto controlla è precisamente il difetto che
    questa PR corregge, ripetuto dentro la correzione. Verificato che la vecchia
    versione lasciasse passare la forma `from math import …` su un difetto vero
    (che solleva davvero `OverflowError`), prima di allargarla.

    L'alias — `from math import isfinite as _isf` — è la quarta forma, e non la
    copriva nemmeno la correzione proposta nel rilievo (che confrontava il nome
    letterale `isfinite`): per questo la guardia risolve il **legame** nel modulo
    invece di cercare una stringa.
    """
    finto = tmp_path / "xtrader_bridge"
    finto.mkdir()
    (finto / f"{etichetta}.py").write_text(
        f"{importazione}\n\n\n"
        "def coercizione(v):\n"
        "    if isinstance(v, (int, float)):\n"
        f"        return {chiamata} and v != 0\n"
        "    return False\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    siti = _siti_isfinite_su_int()

    assert len(siti) == 1, f"forma «{chiamata}» non rilevata: {siti}"
    assert f"{etichetta}.py" in siti[0]


def test_278_un_isfinite_che_NON_viene_da_math_non_e_un_falso_positivo(tmp_path, monkeypatch):
    """Contro-guardia della contro-guardia: allargare il matcher non deve renderlo
    credulone. Un `isfinite` che è un metodo di un oggetto qualunque — o una funzione
    omonima definita in casa — non ha nulla a che vedere con `math.isfinite` e non deve
    accendere la guardia, altrimenti si impara a ignorarla."""
    finto = tmp_path / "xtrader_bridge"
    finto.mkdir()
    (finto / "omonimo.py").write_text(
        "def isfinite(x):\n"                       # funzione locale, non math
        "    return x is not None\n\n\n"
        "def coercizione(v, decimale):\n"
        "    if isinstance(v, (int, float)):\n"
        "        return isfinite(v) and decimale.isfinite() and v != 0\n"
        "    return False\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _siti_isfinite_su_int() == []


def test_278_un_isfinite_RIDEFINITO_in_casa_non_e_un_falso_positivo(tmp_path, monkeypatch):
    """Rilievo GPT-5.5 sulla PR #279: il caso più insidioso dei due omonimi — il modulo
    **importa** `math.isfinite` e poi lo **ridefinisce**. Da quel punto in poi il nome
    non è più quello di `math`, e segnalare le sue chiamate sarebbe un falso positivo.

    Conta perché una guardia rumorosa si impara a ignorare, ed è così che smette di
    servire — lo stesso motivo per cui il semaforo Dizionari della #258 non accende il
    giallo sui profili orfani.
    """
    finto = tmp_path / "xtrader_bridge"
    finto.mkdir()
    (finto / "shadow.py").write_text(
        "from math import isfinite\n\n\n"
        "def isfinite(x):\n"                   # ridefinito: da qui in poi non è più math
        "    return x is not None\n\n\n"
        "def coercizione(v):\n"
        "    if isinstance(v, (int, float)):\n"
        "        return isfinite(v) and v != 0\n"
        "    return False\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _siti_isfinite_su_int() == []


# I quattro siti del predicato numerico, con il verso che ciascuno cerca.
# `_is_recognized_off` è la variante `== 0`: cerca lo zero esplicito invece del non-zero.
QUATTRO_SITI = (
    ("autostart.coerce_enabled", lambda v: autostart.coerce_enabled(v), False),
    ("config_store.as_bool_optin", lambda v: config_store.as_bool_optin(v), False),
    ("source_manager.as_enabled_bool", lambda v: source_manager.as_enabled_bool(v), False),
    ("source_manager._is_recognized_off", lambda v: source_manager._is_recognized_off(v), True),
)


@pytest.mark.parametrize("numero", [ENORME, -ENORME, 2, -1, 0, 1.5, 0.0,
                                    float("inf"), float("-inf"), float("nan")])
def test_278_i_quattro_siti_concordano_sul_contratto_numerico(numero):
    """Parità. I quattro siti hanno vocabolari di **stringhe** diversi di proposito
    (`"si"` è un sì per le sorgenti e non per gli opt-in), ma sul **numero** dicono
    tutti la stessa cosa: finito e diverso da zero è un sì esplicito, non finito no.

    È il test che mancava: la divergenza fra tre siti allineati e uno indietro non
    era visibile a nessuno, perché nessuno li guardava insieme."""
    finito = isinstance(numero, int) or math.isfinite(numero)
    for nome, fn, cerca_zero in QUATTRO_SITI:
        atteso = finito and (numero == 0 if cerca_zero else numero != 0)
        assert fn(numero) is atteso, f"{nome}({numero!r}) — atteso {atteso}"


def test_278_il_predicato_e_uno_solo(monkeypatch):
    """Regola 3, verificata per **comportamento** e non leggendo il sorgente: se
    l'unica definizione della finitezza cambia risposta, tutti e quattro i siti la
    cambiano con lei. Se uno ne tenesse una copia propria, resterebbe indietro — che è
    esattamente come è nato questo bug."""
    monkeypatch.setattr(validators, "numero_finito", lambda v: False)

    for nome, fn, cerca_zero in QUATTRO_SITI:
        assert fn(2) is False, f"{nome} non passa dalla fonte unica: ha una copia propria"
        assert fn(0) is False, f"{nome} non passa dalla fonte unica: ha una copia propria"


def test_278_numero_finito_non_converte_gli_interi():
    """Il contratto dell'helper estratto, sui casi che l'hanno reso necessario."""
    assert validators.numero_finito(ENORME) is True      # nessuna conversione, nessun crash
    assert validators.numero_finito(-ENORME) is True
    assert validators.numero_finito(0) is True           # finito: lo zero è un numero
    assert validators.numero_finito(1.5) is True
    assert validators.numero_finito(float("inf")) is False
    assert validators.numero_finito(float("nan")) is False
    # Un bool NON è un numero per questo predicato: i chiamanti lo trattano prima,
    # e lasciarlo passare qui renderebbe `True` indistinguibile da `1`.
    assert validators.numero_finito(True) is False
    assert validators.numero_finito(False) is False
    for v in ("2", None, [], {}, object()):
        assert validators.numero_finito(v) is False, v


def test_278_il_percorso_di_SALVATAGGIO_non_solleva():
    """L'altro consumatore di `coerce_enabled` (Regola 2-bis): non lo legge soltanto,
    ci **persiste** sopra. `settings_controller.apply_advanced` lo applica al valore
    che sta per finire in `config.json`, quindi un crash qui non perde un campo —
    perde l'intero salvataggio della schermata Impostazioni.

    Il valore enorme arriva a questo percorso in modo del tutto ordinario: basta
    ri-salvare le impostazioni con una config che lo contiene già."""
    from xtrader_bridge import settings_controller as sc

    form = {"recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
            "dry_run": True, "max_per_day": "10", "confirmation_timeout": "90",
            "auto_start_listener": ENORME}

    nuova, errori = sc.apply_advanced({"bot_token": "T", "chat_id": "42"}, form)

    assert errori == [], errori
    assert nuova["auto_start_listener"] is True, "un numero non-zero è un sì esplicito"
    assert isinstance(nuova["auto_start_listener"], bool), (
        "va persistito un bool vero, non l'int enorme che riesploderebbe al load")
    assert nuova["bot_token"] == "T", "il resto della config non deve andare perso"
