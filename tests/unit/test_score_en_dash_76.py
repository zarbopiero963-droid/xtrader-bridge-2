"""P3-13 audit #76 — `extract_scores` deve riconoscere l'EN DASH «–» (U+2013).

Bug: `_SCORE_RE` accettava SOLO il trattino ASCII `-` come separatore interno del
punteggio. Le tastiere iOS/molti client Telegram sostituiscono automaticamente il
trattino con l'EN DASH: un canale che pubblica «1–0, 2–1» non generava NESSUNA
riga (fail-closed, ma tutti i segnali di quel canale andavano persi in silenzio).

Fix testato: classe `[-–]` come separatore interno. TUTTE le difese esistenti
devono valere identiche con l'EN DASH: confini anti-cifra, anti-decimale (punto e
virgola italiana), niente «:», niente fusione multi-riga, dedup, cap. Altri dash
Unicode (em dash «—», minus «−») restano NON riconosciuti di proposito (stesso
principio fail-closed del «:»: si aggiungono solo su richiesta di un canale reale).
"""

from xtrader_bridge.custom_parser_engine import extract_scores


def test_en_dash_riconosciuto_e_normalizzato():
    """FAIL-FIRST: pre-patch «1–0, 2–1» → lista vuota (segnali persi)."""
    assert extract_scores("1–0, 2–1") == ["1 - 0", "2 - 1"]


def test_en_dash_normalizzazione_spazi_e_zeri():
    assert extract_scores("01 – 0, 2–01") == ["1 - 0", "2 - 1"]


def test_en_dash_misto_a_trattino_ascii():
    """Un elenco reale può mischiare i due separatori (copia-incolla + digitazione)."""
    assert extract_scores("1-0, 2–1, 0-0") == ["1 - 0", "2 - 1", "0 - 0"]


def test_en_dash_esclude_decimali_punto_e_virgola():
    """Le difese anti-decimale valgono IDENTICHE con l'EN DASH: «0–0.5»/«0–0,5»
    NON devono produrre un punteggio spurio (riga Correct Score errata)."""
    assert extract_scores("handicap 0–0.5 e 0–0,5 e 0,5–1") == []


def test_en_dash_esclude_numeri_lunghi():
    assert extract_scores("maglia 100–1 e id 1–100 e 007–3") == []


def test_en_dash_non_fonde_cifre_di_righe_diverse():
    """Il punteggio sta su UNA riga anche con l'EN DASH: «3\\n– 0» non è «3 - 0»."""
    assert extract_scores("quota 3\n– 0 non è un punteggio") == []


def test_en_dash_dedup_preserva_ordine():
    assert extract_scores("1–0, 1-0, 2–1") == ["1 - 0", "2 - 1"]


def test_altri_dash_unicode_restano_esclusi_fail_closed():
    """Em dash «—» (U+2014) e minus «−» (U+2212) NON sono riconosciuti (scelta
    deliberata, come il «:»): nessuna riga, mai un match parziale."""
    assert extract_scores("1—0, 2−1") == []
