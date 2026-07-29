"""Test hard del contratto CSV XTrader (PR-01, aggiornato PR-03).

Esercita le funzioni reali di `xtrader_bridge.csv_writer`. Il contratto a 14
colonne è basato sui CSV di esempio reali del team XTrader. `CONTRACT_HEADER` è
volutamente un letterale indipendente: è la guardia che fa fallire il test se
l'header di produzione cambia per errore.
"""

import pytest

from xtrader_bridge import csv_writer

# Contratto ufficiale a 14 colonne (vedi docs/xtrader_csv_contract.md).
CONTRACT_HEADER = [
    "Provider", "EventId", "EventName", "MarketId", "MarketName",
    "MarketType", "SelectionId", "SelectionName", "Handicap", "Price",
    "MinPrice", "MaxPrice", "BetType", "Points",
]


def _row(**overrides):
    parsed = {
        "signal_type": "MATCH ODDS", "competition": "Serie A",
        "teams": "Inter v Milan", "score": "1 - 0", "time_": "67m",
        "quota": "1.85", "probability": "72.5", "bet_type": "BACK",
    }
    parsed.update(overrides)
    return csv_writer.build_csv_row(parsed, "PBet")


def test_header_matches_contract_in_order():
    assert csv_writer.CSV_HEADER == CONTRACT_HEADER


def test_header_has_14_columns():
    assert len(csv_writer.CSV_HEADER) == 14


def test_header_has_no_stake_or_timestamp():
    assert "Stake" not in csv_writer.CSV_HEADER
    assert "Timestamp" not in csv_writer.CSV_HEADER


def test_id_columns_present():
    for col in ("EventId", "MarketId", "SelectionId", "Handicap"):
        assert col in csv_writer.CSV_HEADER


def test_build_csv_row_keys_match_header_order():
    # Assert order-sensitive: cattura regressioni nell'ordine delle colonne.
    assert list(_row().keys()) == CONTRACT_HEADER


def test_csv_injection_neutralizzata_ma_numeri_intatti(tmp_path):
    # audit B1: un nome squadra/selezione attacker-controlled da Telegram che inizia con
    # =/+/-/@ o un control-char NON deve finire verbatim nel CSV (formula/comando per un
    # reader formula-aware). Viene prefissato con un apice. I NUMERI (Handicap negativo,
    # Price) restano intatti, altrimenti il contratto numerico si romperebbe.
    import csv as _csv
    row = dict.fromkeys(CONTRACT_HEADER, "")
    row.update({
        "EventName": "=cmd|'/c calc'!A1",
        "SelectionName": "@SUM(1+1)",
        "MarketName": "-payload",
        "Provider": "\tTabInjection",
        "Handicap": "-1",          # numero legittimo: NON va prefissato
        "Price": "1.85",
    })
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.reader(f))
    assert rows[0] == CONTRACT_HEADER
    out = dict(zip(CONTRACT_HEADER, rows[1]))
    assert out["EventName"] == "'=cmd|'/c calc'!A1"
    assert out["SelectionName"] == "'@SUM(1+1)"
    assert out["MarketName"] == "'-payload"
    assert out["Provider"] == "'\tTabInjection"
    assert out["Handicap"] == "-1"      # numero preservato (niente apice, resta intero)
    assert out["Price"] == "1,85"       # #342: lingua CSV default IT → decimale con la VIRGOLA


def test_csv_nomi_legittimi_non_prefissati(tmp_path):
    # Un nome reale (non formula) non deve essere alterato: nessun falso positivo.
    import csv as _csv
    row = dict.fromkeys(CONTRACT_HEADER, "")
    row.update({"EventName": "Inter v Milan", "SelectionName": "Over 2,5 goal",
                "MarketName": "Over/Under 2,5 gol", "Handicap": "+1,5"})
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        out = dict(zip(CONTRACT_HEADER, list(_csv.reader(f))[1]))
    assert out["EventName"] == "Inter v Milan"
    assert out["SelectionName"] == "Over 2,5 goal"
    assert out["Handicap"] == "+1,5"    # numero col segno: intatto


def test_bettype_back_maps_to_punta():
    assert _row(bet_type="BACK")["BetType"] == "PUNTA"


def test_bettype_lay_maps_to_banca():
    assert _row(bet_type="LAY")["BetType"] == "BANCA"


def test_bettype_lowercase_is_normalized():
    assert _row(bet_type="back")["BetType"] == "PUNTA"
    assert _row(bet_type="lay")["BetType"] == "BANCA"


def test_unsupported_bettype_is_blocked():
    raised = False
    try:
        _row(bet_type="foo")
    except ValueError:
        raised = True
    assert raised, "bet_type non valido deve sollevare ValueError"


def test_points_is_empty_by_default():
    assert _row()["Points"] == csv_writer.DEFAULT_POINTS == ""


def test_handicap_default_is_zero():
    assert _row()["Handicap"] == "0"


def test_ids_empty_when_absent_from_signal():
    row = _row()
    assert row["EventId"] == "" and row["MarketId"] == "" and row["SelectionId"] == ""


def test_file_scritto_ha_bom_utf8_e_quote_all(tmp_path):
    # Verifica byte-level del formato reale: BOM utf-8-sig + QUOTE_ALL.
    # (gli altri test leggono via csv.reader e NON distinguono QUOTE_ALL da MINIMAL).
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_csv(_row(), path)
    with open(path, "rb") as f:
        raw = f.read()

    # BOM UTF-8 in testa (utf-8-sig).
    assert raw.startswith(b"\xef\xbb\xbf")

    header_line = raw.decode("utf-8-sig").splitlines()[0]
    # QUOTE_ALL: ogni campo dell'header è racchiuso tra virgolette, niente campo "nudo".
    assert header_line.startswith('"') and header_line.endswith('"')
    for col in csv_writer.CSV_HEADER:
        assert f'"{col}"' in header_line
    # Controprova MINIMAL: con QUOTE_MINIMAL i nomi colonna NON sarebbero quotati.
    assert "Provider" not in header_line.replace('"Provider"', "")


def _read_data_lines(path):
    with open(path, encoding="utf-8-sig") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def test_write_rows_scrive_piu_righe_attive(tmp_path):
    # PR-22: la coda multi-segnale scrive header + una riga per ogni segnale attivo.
    path = str(tmp_path / "segnali.csv")
    rows = [_row(teams="Inter v Milan"), _row(teams="Roma v Lazio"),
            _row(teams="Napoli v Juve")]
    csv_writer.write_rows(rows, path)
    lines = _read_data_lines(path)
    assert len(lines) == 1 + 3                      # header + 3 segnali
    assert lines[0].count('"Provider"') == 1        # header in testa
    assert "Inter v Milan" in lines[1]
    assert "Napoli v Juve" in lines[3]


def test_write_rows_vuoto_lascia_solo_header(tmp_path):
    # rows vuota → solo header (equivale a svuotamento del CSV).
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([_row()], path)           # prima una riga
    csv_writer.write_rows([], path)                 # poi svuota
    lines = _read_data_lines(path)
    assert len(lines) == 1                          # solo header
    for col in csv_writer.CSV_HEADER:
        assert f'"{col}"' in lines[0]


def test_write_csv_delega_a_write_rows(tmp_path):
    # write_csv resta retro-compatibile: una sola riga.
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_csv(_row(), path)
    assert len(_read_data_lines(path)) == 2         # header + 1


# ── P3-cw1 (#166): la neutralizzazione anti-formula non deve dipendere da `s[0]` ──────────────

@pytest.mark.parametrize("prefisso", [" ", "  ", " \t", "\t ", "   \t  "])
@pytest.mark.parametrize("carico", ["=1+1", "=cmd|'/c calc'!A1", "@SUM(1+1)", "+payload",
                                    "-payload"])
def test_uno_spazio_davanti_non_aggira_la_neutralizzazione(prefisso, carico):
    """Excel, LibreOffice e Google Sheets **ignorano gli spazi iniziali** quando decidono se
    una cella è una formula: « =1+1» viene valutata esattamente come «=1+1».

    `_sanitize_cell` guardava solo `s[0]`, quindi bastava uno spazio davanti per passare.
    L'asimmetria era interna alla funzione stessa: il ramo NUMERICO usava già `s.strip()`,
    quello del carattere-formula no.

    Provato su tutti e quattro i caratteri formula e su più forme di spaziatura iniziale,
    perché il buco non era in un carattere particolare ma nel modo di guardarli."""
    sporco = prefisso + carico
    assert csv_writer._sanitize_cell(sporco).startswith("'"), sporco
    # Il contenuto non viene alterato: si antepone l'apice, non si riscrive il valore.
    assert csv_writer._sanitize_cell(sporco) == "'" + sporco


@pytest.mark.parametrize("numero", ["-1", "+1,5", "1.85", "2,5", "-0.5"])
@pytest.mark.parametrize("spazi", ["", " ", "  ", " \t"])
def test_il_contratto_numerico_resta_intatto_anche_con_spazi(numero, spazi):
    """Il vincolo che rende il fix delicato: Handicap «-1»/«+1,5» e Price «1.85» iniziano con
    un carattere formula ma sono **numeri legittimi**. Prefissarli romperebbe il contratto —
    XTrader leggerebbe testo dove si aspetta un numero.

    Guardare il valore spogliato non deve cambiare questo: si decide su `strip()`, e `strip()`
    è esattamente ciò che la regex numerica già usava."""
    assert not csv_writer._sanitize_cell(spazi + numero).startswith("'"), spazi + numero


def test_nessun_falso_positivo_sui_nomi_legittimi():
    """La direzione opposta: il fix è più severo, quindi va verificato che non prenda nomi
    veri. Nessuno di questi inizia con un carattere formula, spogliato o no."""
    for nome in ["Inter v Milan", " Inter v Milan", "Over 2,5 goal", " L'Aquila v Ternana",
                 "Bodø/Glimt v Malmö FF", "  Esito Finale", ""]:
        assert csv_writer._sanitize_cell(nome) == nome, nome


def test_il_bypass_non_arriva_piu_nel_file_scritto(tmp_path):
    """Il test che conta: la funzione pura può essere corretta e il file sbagliato lo stesso.

    Questo è il percorso reale — `write_rows` → `_sanitize_row` → file su disco — ed è quello
    su cui il difetto era stato misurato: il valore ci arrivava verbatim."""
    import csv as _csv

    row = dict.fromkeys(CONTRACT_HEADER, "")
    row.update({
        "EventName": " =cmd|'/c calc'!A1 v Milan",   # spazio iniziale: il bypass
        "SelectionName": "  @SUM(1+1)",
        "MarketName": " -payload",
        "Handicap": " -1",                            # numero con spazio: NON va prefissato
    })
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        out = dict(zip(CONTRACT_HEADER, list(_csv.reader(f))[1]))

    assert out["EventName"].startswith("'"), out["EventName"]
    assert out["SelectionName"].startswith("'"), out["SelectionName"]
    assert out["MarketName"].startswith("'"), out["MarketName"]
    assert not out["Handicap"].startswith("'"), out["Handicap"]


def test_i_control_char_interni_sopravvivono_al_giro_completo(tmp_path):
    """P3-cw2 (#166) — comportamento **invariato**, ma misurato invece che presunto.

    L'audit segnalava che i CR/LF *interni* a una cella non vengono neutralizzati (solo quelli
    in testa lo sono). È vero, ed è deliberato: `QUOTE_ALL` mette ogni campo fra virgolette, e
    un a-capo dentro un campo quotato è CSV **valido** secondo RFC-4180 — un parser conforme lo
    rilegge come un singolo campo, non come due righe.

    Questo test lo dimostra facendo il giro completo scrittura → rilettura: se un domani la
    scrittura smettesse di quotare, o qualcuno togliesse `QUOTE_ALL`, il valore tornerebbe
    spezzato e questo test diventerebbe rosso. È la ragione per cui non serve neutralizzarli —
    resa eseguibile, non lasciata in un commento.

    Resta fuori dalla garanzia il caso in cui il parser di XTrader non sia conforme a
    RFC-4180: non è verificabile senza XTrader, ed è annotato nella #166."""
    import csv as _csv

    row = dict.fromkeys(CONTRACT_HEADER, "")
    row.update({"EventName": "Inter\r\nMilan", "MarketName": "Esito\tFinale"})
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        righe = list(_csv.reader(f))

    assert len(righe) == 2, "il CR/LF interno non deve produrre righe extra"
    out = dict(zip(CONTRACT_HEADER, righe[1]))
    assert out["EventName"] == "Inter\r\nMilan"    # round-trip esatto
    assert out["MarketName"] == "Esito\tFinale"


@pytest.mark.parametrize("carico", ["=1+1", "+payload", "-payload", "@SUM(A1)"])
@pytest.mark.parametrize("spazio,nome", [
    ("\xa0", "NBSP U+00A0"), (" ", "thin space U+2009"),
    ("　", "ideographic space U+3000"), ("\x0b", "vertical tab"), ("\x0c", "form feed"),
])
def test_anche_lo_spazio_unicode_e_coperto(spazio, nome, carico):
    """Perimetro del fix, misurato. L'invariante è che la nostra nozione di «spazio iniziale»
    sia **almeno larga quanto** quella del reader che valuta la formula: se il reader ne
    saltasse uno che noi non togliamo, resterebbe un buco.

    `str.strip()` senza argomenti toglie lo spazio bianco **Unicode**, non solo ASCII — quindi
    il fix copre anche NBSP & co., che sono realistici in un messaggio Telegram
    (copia-incolla, tastiere mobili). Verificato eseguendo, non dedotto."""
    assert csv_writer._sanitize_cell(spazio + carico).startswith("'"), (nome, carico)


def test_lo_zero_width_space_non_e_spazio_ed_e_un_confine_noto():
    """L'altro lato del perimetro, dichiarato invece che scoperto per caso.

    `U+200B` (zero-width space) **non** è spazio bianco per Python, quindi `strip()` non lo
    toglie e la cella non viene prefissata. Non è un buco: non essendo spazio, un reader non
    lo salta e la cella non viene letta come formula — il nostro comportamento e il suo
    coincidono.

    Il test esiste per fissare il confine: se un domani si scoprisse un reader che **salta**
    i caratteri a larghezza zero, questo test va cambiato **deliberatamente**, con la nota del
    perché — invece di trovarsi il buco senza sapere che c'era una decisione."""
    assert csv_writer._sanitize_cell("​=1+1") == "​=1+1"


@pytest.mark.parametrize("colonna,sporco,atteso_it", [
    ("Handicap", " -1", "-1"), ("Handicap", "-1 ", "-1"), ("Handicap", " +1,5 ", "+1,5"),
    ("Price", " 1.85", "1,85"), ("Price", "1.85 ", "1,85"),
    ("MinPrice", " 1.50 ", "1,50"), ("MaxPrice", " 2.00", "2,00"),
])
def test_le_colonne_numeriche_arrivano_nel_file_senza_spazi(tmp_path, colonna, sporco,
                                                            atteso_it):
    """Rilievo GPT-5.5 (#170): «un numero con spazio iniziale resta non prefissato, quindi viene
    scritto CON lo spazio — se XTrader non trimma, non lo legge come numero».

    Osservazione giusta, ma non si verifica: le colonne decimali passano da `_localize_decimal`
    **prima** di `_sanitize_cell` (`_sanitize_row(_localize_row(...))`), e la localizzazione
    strippa già. Nel file arriva `-1`, non ` -1`.

    Il test lo fissa dove conta — sul **file scritto**, non sulla funzione pura — così la
    garanzia non dipende dall'ordine attuale delle due trasformazioni: se un domani qualcuno le
    invertisse o togliesse lo strip, questo diventa rosso."""
    import csv as _csv

    row = dict.fromkeys(CONTRACT_HEADER, "")
    row.update({"EventName": "Inter v Milan", colonna: sporco})
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        out = dict(zip(CONTRACT_HEADER, list(_csv.reader(f))[1]))

    assert out[colonna] == atteso_it, f"{colonna}={sporco!r}"
    assert not out[colonna].startswith("'"), "un numero non deve mai essere prefissato"


@pytest.mark.parametrize("numero", ["-1", "+1,5", "1.85"])
@pytest.mark.parametrize("spazio", ["\xa0", " ", "　"])
def test_l_esenzione_numerica_regge_anche_dopo_spazio_unicode(spazio, numero):
    """Il ramo che la parametrizzazione sui caratteri formula NON tocca, e che è il più
    delicato: `-1` e `+1,5` iniziano con un carattere formula ma sono numeri, quindi l'apice
    non va messo.

    Con lo spazio unicode davanti si percorrono **entrambe** le novità del fix insieme —
    `strip()` che vede oltre l'ASCII, e l'esenzione numerica che deve continuare a valere sul
    valore spogliato. Era l'unica combinazione rimasta scoperta (rilievo GPT-5.5 #170, esteso:
    lui chiedeva i quattro caratteri formula, ma il ramo scoperto era questo)."""
    assert not csv_writer._sanitize_cell(spazio + numero).startswith("'"), spazio + numero


@pytest.mark.parametrize("vuoto", ["", " ", "   ", "\xa0\xa0", "　"])
def test_una_cella_di_solo_spazio_resta_invariata(vuoto):
    """La guardia `if nudo and ...`: spogliando una cella di soli spazi resta la stringa vuota,
    e `nudo[0]` solleverebbe `IndexError`. Non deve né esplodere né prefissare nulla —
    una cella vuota non è una formula (rilievo GPT-5.5 #170 sui campi whitespace-only)."""
    assert csv_writer._sanitize_cell(vuoto) == vuoto


def _chiamate_ast(percorso, nomi):
    """Nomi di attributo chiamati nel file, via AST — es. `("writerow", "writerows")`.

    AST e non regex (rilievo GPT-5.5 #170): una regex su riga fallisce sulle chiamate
    formattate su più righe, sui commenti e sulle stringhe che contengono il testo. L'AST vede
    la struttura, non il testo, quindi non dipende dalla formattazione."""
    import ast

    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    return [n for n in ast.walk(albero)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in nomi]


def test_ogni_riga_dati_passa_dalla_sanitizzazione():
    """Rilievo GPT-5.5 (#170): i test su `_sanitize_cell` non garantiscono da soli che **tutti**
    i percorsi di scrittura CSV passino da lì.

    Osservazione giusta, ed è la forma di difetto che questo repository ha già incontrato più
    volte: una guardia corretta con un **perimetro incompleto** è indistinguibile da una
    guardia che passa. Il grep di oggi non basta — serve un invariante che si accorga di un
    secondo writer aggiunto domani.

    Regola: nel modulo può esistere **una sola** scrittura di riga dati, e il suo argomento deve
    essere il risultato di `_sanitize_row`. `writeheader()` è escluso: emette i nomi di colonna
    del contratto, non dati che arrivano da Telegram."""
    import ast
    import pathlib

    modulo = pathlib.Path(csv_writer.__file__)
    scritture = _chiamate_ast(modulo, ("writerow", "writerows"))

    assert len(scritture) == 1, (
        "aggiunto un secondo punto di scrittura righe: deve passare da `_sanitize_row`, poi "
        f"aggiorna questo guard. Righe: {[n.lineno for n in scritture]}")

    (chiamata,) = scritture
    arg = chiamata.args[0] if chiamata.args else None
    assert (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
            and arg.func.id == "_sanitize_row"), (
        f"la scrittura delle righe dati (riga {chiamata.lineno}) non passa da `_sanitize_row`")


def test_nessun_altro_modulo_scrive_direttamente_il_csv():
    """L'altra metà del perimetro: la sanitizzazione vale solo se `csv_writer` resta l'unico a
    scrivere il CSV. Un secondo scrittore altrove la aggirerebbe per intero, non in un ramo.

    **La prima stesura di questo guard aveva lo stesso difetto che il guard esiste per
    prevenire** (trovato da GPT-5.5 #170): usava `glob("*.py")`, che non scende nei
    sottopacchetti — `betfair/` e `licensing/`, **12 file**, erano invisibili. Un guard che non
    guarda dove dice di guardare è peggio di nessun guard, perché autorizza a non controllare.
    Ora `rglob`, e il test verifica anche di aver **davvero** visto i sottopacchetti."""
    import pathlib

    pacchetto = pathlib.Path(csv_writer.__file__).parent
    files = [f for f in sorted(pacchetto.rglob("*.py")) if "__pycache__" not in f.parts]

    # Auto-controllo del perimetro: se un domani la struttura cambia e il glob torna piatto,
    # questo assert lo dice invece di lasciar passare il guard a vuoto.
    sottopacchetti = {f.parent.name for f in files if f.parent != pacchetto}
    assert sottopacchetti, "il guard non sta vedendo alcun sottopacchetto: perimetro sospetto"

    colpevoli = [f"{f.relative_to(pacchetto)}:{n.lineno}"
                 for f in files if f.name != "csv_writer.py"
                 for n in _chiamate_ast(f, ("writer", "DictWriter"))]

    assert not colpevoli, (
        "questi punti creano un writer CSV senza passare da `csv_writer`, quindi bypassano "
        f"la sanitizzazione anti-formula: {colpevoli}")
