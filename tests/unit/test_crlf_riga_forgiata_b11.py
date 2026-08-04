"""B11 (#194, decisione D2) — un CR/LF dentro una cella non deve poter forgiare una RIGA.

**L'attacco, non la teoria.** Il PoC della #192 (M7) ha misurato che con una configurazione
parser del tutto ordinaria — `end_before="Quota:"`, la forma che la documentazione insegna —
un messaggio Telegram con CR/LF interni deposita nel file una **riga fisica da 14 campi
interamente scelta dall'attaccante**: evento diverso, selezione diversa, **`BANCA` invece di
`PUNTA`**, quota 1.01. La quota non è quotata, quindi resta intatta anche a uno `split(",")`
ingenuo.

**Perché la difesa precedente non bastava.** `QUOTE_ALL` mette ogni campo fra virgolette, e
un a-capo dentro un campo quotato è CSV *valido* secondo RFC-4180: un parser **conforme** lo
rilegge come un campo solo. Ma la conformità del parser di XTrader **non è verificata**, e il
repository stesso la dichiara fuori garanzia. Il costo di sanificare è vicino a zero — nessun
segnale legittimo ha un a-capo dentro il nome di una squadra — mentre il costo di aver
sbagliato su XTrader è una scommessa col **lato invertito**.

**Il perimetro è misurato, non assunto** (vedi `test_solo_cr_e_lf_spezzano_il_file`): a livello
di file solo `\\r` e `\\n` spezzano una riga. VT, FF, NEL, U+2028 e U+2029 spezzano soltanto
sotto `str.splitlines()` di Python, mai nell'iterazione del file — e nessun consumatore legge
il CSV così. Per questo la sanificazione si ferma a `\\r`/`\\n` invece di allargarsi a tutti i
control-char: gli altri sono la classe della B23, che ha una PR sua.
"""

import pytest

from xtrader_bridge import csv_writer

CONTRACT_HEADER = [
    "Provider", "EventId", "EventName", "MarketId", "MarketName",
    "MarketType", "SelectionId", "SelectionName", "Handicap", "Price",
    "MinPrice", "MaxPrice", "BetType", "Points",
]

# La riga che l'attaccante vuole far comparire: 14 campi, BANCA al posto di PUNTA, quota 1.01.
RIGA_FORGIATA = "Betfair,9,Partita Finta,1,Vincente,MATCH_ODDS,7,Selezione Finta,0,1.01,,,BANCA,"


def _righe_fisiche(path):
    """Le righe FISICHE del file, come le vedrebbe un lettore riga-orientata.

    È deliberatamente NON `csv.reader`: un parser conforme a RFC-4180 non si farebbe
    ingannare, ed è proprio la conformità di XTrader che non possiamo dare per scontata.
    Questo helper modella il lettore ingenuo — quello contro cui la D2 ha deciso di
    difendersi."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [ln.rstrip("\r\n") for ln in f if ln.strip()]


def test_un_crlf_in_eventname_non_deposita_una_riga_in_piu(tmp_path):
    """Il cuore della B11: dopo header + 1 segnale il file deve avere ESATTAMENTE 2 righe."""
    riga = dict.fromkeys(CONTRACT_HEADER, "")
    riga["EventName"] = f'Inter v Milan"\r\n{RIGA_FORGIATA}'
    riga["BetType"] = "PUNTA"
    percorso = str(tmp_path / "segnali.csv")

    csv_writer.write_rows([riga], percorso)

    fisiche = _righe_fisiche(percorso)
    assert len(fisiche) == 2, (
        "un lettore riga-orientata vede più di header + 1 segnale: la cella ha forgiato "
        "una riga.\nRighe trovate:\n" + "\n".join(fisiche)
    )


def test_nessuna_riga_fisica_puo_essere_letta_come_una_banca(tmp_path):
    """Il danno concreto, non solo il conteggio: nessuna riga fisica deve dire `BANCA`.

    Il segnale legittimo è un `PUNTA`. Se una riga fisica qualsiasi si lascia leggere come
    una scommessa con `BetType=BANCA`, l'attaccante ha invertito il lato — che è il danno
    reale della B11, non il conteggio delle righe.

    Il criterio sono i **primi 14 campi**, non un conteggio esatto: misurato sul file
    prodotto prima della patch, la riga forgiata è

        Betfair,9,…,BANCA,","","",…

    cioè 25 campi separati da virgola, di cui i **primi 14** sono esattamente la riga
    dell'attaccante — con `BANCA` in tredicesima posizione, che è dove il contratto mette
    `BetType`. Un lettore ingenuo che prende le prime 14 colonne e ignora il resto piazza
    la scommessa invertita. Pretendere `len(campi) == 14` avrebbe reso il test verde su un
    file già compromesso: la coda della riga vera segue sulla stessa riga fisica."""
    riga = dict.fromkeys(CONTRACT_HEADER, "")
    riga["EventName"] = f'Inter v Milan"\r\n{RIGA_FORGIATA}'
    riga["BetType"] = "PUNTA"
    percorso = str(tmp_path / "segnali.csv")

    csv_writer.write_rows([riga], percorso)

    posizione_bettype = CONTRACT_HEADER.index("BetType")
    for fisica in _righe_fisiche(percorso):
        campi = fisica.split(",")[:len(CONTRACT_HEADER)]
        assert len(campi) < len(CONTRACT_HEADER) or campi[posizione_bettype] != "BANCA", (
            f"riga fisica leggibile come una BANCA forgiata: {fisica!r}"
        )


def test_il_crlf_in_coda_a_un_numero_e_coperto(tmp_path):
    """Il caso che la formulazione «solo le celle NON numeriche» avrebbe mancato.

    `_sanitize_cell` decide la numericità sul valore **spogliato** (`s.strip()`), e `strip()`
    toglie anche i CR/LF finali: `"1.85\\r\\n"` risulta quindi *numerico*, e una sanificazione
    condizionata alla non-numericità l'avrebbe lasciato passare intatto — con l'a-capo, cioè
    con la riga forgiata. Per questo la neutralizzazione è **incondizionata**: nessun numero
    valido contiene un a-capo, quindi applicarla sempre non toglie nulla all'esenzione
    numerica e chiude questa scorciatoia."""
    riga = dict.fromkeys(CONTRACT_HEADER, "")
    riga["Price"] = f'1.85\r\n{RIGA_FORGIATA}'
    percorso = str(tmp_path / "segnali.csv")

    csv_writer.write_rows([riga], percorso)

    assert len(_righe_fisiche(percorso)) == 2, "un numero con CR/LF in coda ha forgiato una riga"


@pytest.mark.parametrize("carico", ["\r", "\n", "\r\n", "\n\r", "\r\r", "\n\n\n"])
def test_ogni_forma_di_acapo_e_neutralizzata(carico):
    """Non solo `\\r\\n`: anche `\\r` da solo, `\\n` da solo e le combinazioni ripetute.

    Un `\\r` isolato è il fine-riga del Mac classico ed è tuttora un fine-riga valido per
    l'iterazione di file di Python; guardare solo la sequenza `\\r\\n` lascerebbe aperta la
    stessa porta con un carattere in meno."""
    risultato = csv_writer._sanitize_cell(f"Inter{carico}Milan")
    assert "\r" not in risultato and "\n" not in risultato, repr(risultato)


def test_gli_acapo_diventano_un_solo_spazio():
    """`\\r\\n` è UN a-capo, non due: collassarlo in un singolo spazio tiene leggibile il
    valore («Inter Milan», non «Inter  Milan») senza cambiare il numero di campi."""
    assert csv_writer._sanitize_cell("Inter\r\nMilan") == "Inter Milan"
    assert csv_writer._sanitize_cell("Inter\n\n\nMilan") == "Inter Milan"


def test_l_esenzione_numerica_resta_intatta():
    """D2 pretende che l'esenzione numerica sopravviva alla modifica.

    Un numero non contiene a-capo, quindi la neutralizzazione non lo tocca — né il valore né
    la decisione di NON apostrofarlo (un `-1,5` apostrofato romperebbe il contratto numerico
    di XTrader, che leggerebbe `'-1,5` come testo)."""
    for numero in ("1.85", "-1.5", "-1,5", "0", "1,01", "  2.50  "):
        assert csv_writer._sanitize_cell(numero) == numero, numero
        assert not csv_writer._sanitize_cell(numero).startswith("'"), numero


def test_la_protezione_formula_sopravvive_a_un_acapo_iniziale():
    """Un a-capo in testa non deve diventare un modo per far passare una formula.

    Prima della patch un `"\\r\\n=1+1"` prendeva l'apice dal ramo control-char — ma l'a-capo
    restava nella cella, quindi la protezione formula c'era e la riga si spezzava lo stesso.
    Ora l'a-capo sparisce e la formula viene comunque intercettata dal ramo che decide sul
    valore spogliato: si guadagna la riga intatta senza perdere l'apostrofo."""
    risultato = csv_writer._sanitize_cell("\r\n=1+1")
    assert risultato.startswith("'"), risultato
    assert "\r" not in risultato and "\n" not in risultato, repr(risultato)


def test_solo_cr_e_lf_spezzano_il_file(tmp_path):
    """Il perimetro della sanificazione, **misurato** invece che deciso a intuito.

    Motiva perché ci si ferma a `\\r`/`\\n` e non si allarga a ogni control-char: a livello di
    FILE nessun altro carattere spezza una riga. Se un domani questo test diventasse rosso su
    uno dei caratteri «innocui», vorrebbe dire che il perimetro va allargato — ed è meglio
    scoprirlo da un test che da un CSV sbagliato."""
    spezza = {"\r": True, "\n": True,
              "\v": False, "\f": False, "": False, " ": False, " ": False}
    for ch, atteso in spezza.items():
        percorso = str(tmp_path / f"m{ord(ch)}.csv")
        with open(percorso, "w", newline="", encoding="utf-8") as f:
            f.write(f'"A{ch}B","x"\n')
        with open(percorso, newline="", encoding="utf-8") as f:
            spezzato = len(list(f)) > 1
        assert spezzato is atteso, f"U+{ord(ch):04X}: spezza={spezzato}, atteso={atteso}"
