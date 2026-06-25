"""Fuzz / property testing del parser P.Bet (`xtrader_bridge.parser.parse_message`).

Audit #105 / roadmap #153 — voce **H1**. Complementa i casi mirati di
`test_parser_pbet_robust.py` con proprietà su input **arbitrario/malformato**,
mantenendo l'invariante safety-critical: *input malformato → nessun campo inventato*
(in particolare nessuna quota "nuda" e nessun ribaltamento accidentale del lato BACK→LAY).

Niente dipendenze esterne (`hypothesis` non è nel progetto): fuzz **deterministico** con
`random.Random(seed)` fisso, così è riproducibile e stabile in CI.
"""

import random

from xtrader_bridge import parser

# Schema completo restituito da parse_message (fonte unica per il check di struttura).
EXPECTED_KEYS = {
    "signal_type", "competition", "teams", "score", "time_",
    "quota", "probability", "bet_type", "live",
}

# Charset ostile: marker P.Bet, emoji, separatori, cifre, control char, RTL, e i token
# safety-critical (Quota/Banca/Lay/HT/FT/Prematch) così il fuzz li combina liberamente.
HOSTILE_CHARS = list(
    "P.Bet.🏆🆚⚽⌚📊📈🔊✅🔇 \t\r\n0123456789,.:;@-/vVsS%"
    "\x00\x01\x07‮​"   # NUL, control, RTL override, zero-width
) + ["Quota", "Banca", "Lay", "Punta", "Back", "Prematch:", "HT", "FT", "live", "@"]

# Pool di parole "innocue" per testare che il testo libero NON ribalti il lato a LAY:
# NON contiene banca/lay/punta/back (gli unici token che possono cambiare bet_type).
SAFE_WORDS = [
    "Inter", "Milan", "Arsenal", "Chelsea", "Over", "Under", "Goals", "Match",
    "Odds", "League", "Cup", "Town", "City", "United", "Result", "Double",
    "Chance", "Corner", "Card", "Yangon", "Roma", "Napoli", "vs", "v",
]


def _rand_hostile(rng, max_len=400):
    n = rng.randint(0, max_len)
    return "".join(rng.choice(HOSTILE_CHARS) for _ in range(n))


def _assert_schema(result):
    assert isinstance(result, dict)
    assert set(result.keys()) == EXPECTED_KEYS
    assert isinstance(result["live"], bool)
    assert result["bet_type"] in ("BACK", "LAY")
    for k in EXPECTED_KEYS - {"live", "bet_type"}:
        assert isinstance(result[k], str)


def _assert_quota_invariant(q):
    """Una quota non vuota è SEMPRE ben formata: niente virgola (normalizzata a punto),
    al più un punto decimale, parseabile come float > 1.0. Mai un valore inventato/malformato."""
    if q == "":
        return
    assert "," not in q
    assert q.count(".") <= 1
    assert float(q) > 1.0


def test_parse_message_e_totale_su_input_arbitrario():
    # Per QUALSIASI stringa ostile parse_message non solleva e ritorna lo schema completo.
    rng = random.Random(20240625)
    for _ in range(500):
        text = _rand_hostile(rng)
        result = parser.parse_message(text)
        _assert_schema(result)
        _assert_quota_invariant(result["quota"])


def test_parse_message_robusto_su_casi_limite_di_struttura():
    # Input degeneri non devono sollevare né rompere lo schema.
    for text in ("", "\n\n\n", "\t", "\x00", "‮​", "P.Bet.", "🆚", "Quota",
                 "Quota\n@\nPrematch:", "\n".join(["a"] * 5000)):
        _assert_schema(parser.parse_message(text))


def test_numero_nudo_senza_marker_non_diventa_quota():
    # Proprietà (generalizza il caso mirato '📈 1.2.3'): un numero senza un marker di
    # quota esplicito (Quota/@/HT/FT/Prematch) non deve MAI produrre una quota.
    rng = random.Random(7)
    markerless_emoji = ("", "📈", "📊", "⚽", "🏆")
    for _ in range(400):
        whole = rng.randint(0, 9999)
        frac = rng.randint(0, 999)
        sep = rng.choice([",", ".", ",,", "..", ".,"])
        num = f"{whole}{sep}{frac}"
        emoji = rng.choice(markerless_emoji)
        text = f"P.Bet. OVER 2.5\n🆚 Inter v Milan\n{emoji} {num}".strip()
        q = parser.parse_message(text)["quota"]
        assert q == "", f"quota inventata da numero nudo {num!r}: {q!r}"


def test_bet_type_non_flippa_a_lay_su_testo_libero():
    # Safety-critical: LAY è il lato OPPOSTO. Testo libero senza una riga-lato dedicata
    # (un solo token Banca/Lay) deve lasciare bet_type al default BACK.
    rng = random.Random(99)
    for _ in range(400):
        n_lines = rng.randint(1, 6)
        lines = []
        for _ in range(n_lines):
            n_words = rng.randint(2, 5)   # >=2 parole → mai un singolo token-lato
            lines.append(" ".join(rng.choice(SAFE_WORDS) for _ in range(n_words)))
        text = "P.Bet. OVER 2.5\n" + "\n".join(lines)
        assert parser.parse_message(text)["bet_type"] == "BACK"


def test_riga_lato_dedicata_ribalta_solo_token_esatto():
    # Contro-prova della proprietà: SOLO una riga con esattamente "banca"/"lay" ribalta.
    assert parser.parse_message("P.Bet. X\nInter v Milan\nBanca")["bet_type"] == "LAY"
    assert parser.parse_message("P.Bet. X\nInter v Milan\nLay")["bet_type"] == "LAY"
    # "Lay Town"/"Banca League" = due token → NON ribaltano.
    assert parser.parse_message("P.Bet. X\nInter v Milan\nLay Town")["bet_type"] == "BACK"


def test_parse_message_e_idempotente():
    # Nessuno stato nascosto: stesso input → stesso output.
    rng = random.Random(123)
    for _ in range(200):
        text = _rand_hostile(rng, max_len=200)
        assert parser.parse_message(text) == parser.parse_message(text)


def test_mutazione_di_messaggio_valido_resta_failsafe():
    # Fuzz su delimitatori/quote di un messaggio VALIDO: ogni mutazione non deve sollevare
    # e la quota resta valida-o-vuota (mai malformata). Copre 'separatori/quote' di H1.
    rng = random.Random(2026)
    base = ["P.Bet. OVER 2.5", "🆚 Inter v Milan", "📈 Quota 1,85 📊 72%", "Punta"]
    bad_quotas = ["1.2.3", "1,8,5", "1..85", "1,,85", "1,", "1.", ".85", "abc",
                  "0,5", "1,00", "999999,99", "1.85.3"]
    for _ in range(400):
        lines = list(base)
        # muta la riga quota
        if rng.random() < 0.7:
            lines[2] = f"📈 Quota {rng.choice(bad_quotas)}"
        # corrompi i separatori squadre
        if rng.random() < 0.5:
            lines[1] = lines[1].replace(" v ", rng.choice([" - ", " vs ", " — ", "  "]))
        # inietta righe di rumore
        for _ in range(rng.randint(0, 3)):
            lines.insert(rng.randint(0, len(lines)),
                         "".join(rng.choice(HOSTILE_CHARS) for _ in range(rng.randint(0, 20))))
        result = parser.parse_message("\n".join(lines))
        _assert_schema(result)
        _assert_quota_invariant(result["quota"])
