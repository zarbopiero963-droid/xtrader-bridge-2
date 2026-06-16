"""Parsing dei messaggi Telegram P.Bet. (nessuna dipendenza dalla GUI).

PR-09: parser robusto che gestisce messaggi con emoji **e** in testo semplice.
Estrae signal_type, squadre (normalizzate "Home v Away" da v/vs/-), quota
(virgola o punto), score, minuto, probabilità, bet_type (BACK/LAY) e flag live.
NON inventa dati: i campi non presenti restano vuoti (il blocco dei segnali
incompleti — incl. quota mancante — è di recognition/validazione, PR-10).
"""

import re

_HAS_ALPHA = re.compile(r'[A-Za-zÀ-ÿ]')
_EMOJI_MARKERS = ('🏆', '🆚', '⚽', '⌚', '📊', '📈')

# Numero ben formato (no "1.2.3"): intero con al più una parte decimale.
_NUM = r'\d+(?:[.,]\d+)?'

# Separatori squadre: " v "/" vs " (forti) preferiti a " - " (debole, ambiguo).
_SEP_VVS = re.compile(r'^(.+?)\s+(?:vs|v)\s+(.+)$', re.IGNORECASE)
_SEP_DASH = re.compile(r'^(.+?)\s+-\s+(.+)$')

# Parole-etichetta (match per TOKEN intero, non startswith: così "Preston" ≠ "pre").
_LABEL_WORDS = frozenset({
    'quota', '@', 'time', 'tempo', 'minuto', 'score', 'risultato', 'prob',
    'probabilità', 'probabilita', 'probability', 'lega', 'campionato',
    'competition', 'live', 'pre', 'prematch', 'punta', 'banca', 'back', 'lay',
})

# Coda con punteggio/tempo da rimuovere prima di leggere le squadre
# (es. "Silver Stars FC 6 - 0 46m" → "Silver Stars FC").
# La classe [-–:] include di proposito sia il trattino ASCII "-" sia l'EN DASH "–"
# (e i due punti) perché i punteggi reali usano l'uno o l'altro carattere.
_SCORE_TAIL = re.compile(r'\s+\d+\s*[-–:]\s*\d+(?:\s.*)?$')
# Token di stato da togliere dal signal_type (LIVE/PRE) prima del mapping.
_STATUS_TAIL = re.compile(r'\s+\b(?:live|pre|prematch)\b.*$', re.IGNORECASE)


def _is_odds(value: str) -> bool:
    """Una quota decimale è sempre ≥ 1.0: così "0,5" (linea del mercato, es.
    "Quota 0,5 HT") non viene scambiato per una quota reale."""
    try:
        return float(value) >= 1.0
    except (TypeError, ValueError):
        return False


def _extract_quota(line: str):
    """Quota reale da una riga.

    Nel formato P.Bet "Quota X,Y HT/FT Prematch:Z" il numero X,Y è la **linea**
    del mercato (non una quota): la quota offerta è il valore dopo "Prematch:".
    Questa forma è riconosciuta SOLO da un marker di linea reale — `HT`/`FT`,
    oppure `Prematch:` con valore — così "Quota 1,85 Prematch" (status senza
    valore) NON perde la quota e ricade nell'estrazione normale.
    Altrove è "Quota X" / "@X". Solo quote valide: ≥ 1, ben delimitate (no "1.2.3").
    """
    low = line.lower()
    if re.search(r'\b(?:ht|ft)\b', low) or re.search(r'prematch\s*:', low):
        m = re.search(r'prematch[:\s]*(' + _NUM + r')(?![\d.,])', line, re.IGNORECASE)
    else:
        m = re.search(r'(?:quota|@)[:\s]*(' + _NUM + r')(?![\d.,])', line, re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).replace(',', '.')
    return val if _is_odds(val) else None


def _extract_probability(line: str):
    """Probabilità da "...X%" (numero ben formato e ben delimitato).

    Il lookbehind `(?<![\\d.,])` evita di prendere un frammento di un token
    malformato: "1.2.3%" non deve dare "2.3" — viene rifiutato (None).
    """
    m = re.search(r'(?<![\d.,])(' + _NUM + r')\s*%', line)
    return m.group(1) if m else None


def _looks_like_label(line: str) -> bool:
    """True se la riga è un'etichetta (Quota/Score/Time/...) e non una coppia di
    squadre: confronto per TOKEN intero (così "Preston" ≠ "pre")."""
    low = line.lower()
    if 'p.bet' in low:
        return True
    first = low.split(' ', 1)[0]
    if ':' in first:                       # "Score:", "Time:", "Quota:" ...
        return True
    return first.rstrip(':.') in _LABEL_WORDS


def _teams_from(line: str, sep: re.Pattern):
    """Se la riga (ripulita dalla coda punteggio) è una coppia di squadre con
    il separatore dato e lettere su entrambi i lati, ritorna "Home v Away"."""
    if _looks_like_label(line) or any(e in line for e in _EMOJI_MARKERS):
        return None
    cleaned = _SCORE_TAIL.sub('', line).strip()
    # togli un'eventuale coda quota/@/probabilità sulla stessa riga, così non finisce
    # nell'EventName: "Inter v Milan Quota 1,85" / "... @ 1,85" / "... Probability 72%".
    # NB: "@" senza "\b" per coprire anche la forma spaziata "@ 1,85".
    cleaned = re.sub(r'\s+(?:quota\b|@|probability\b|prob\b).*$', '', cleaned,
                     flags=re.IGNORECASE).strip()
    m = sep.match(cleaned)
    if m and _HAS_ALPHA.search(m.group(1)) and _HAS_ALPHA.search(m.group(2)):
        return f"{m.group(1).strip()} v {m.group(2).strip()}"
    return None


def _find_teams(lines) -> str:
    """Cerca la riga squadre in testo semplice: SOLO " v "/" vs " (cue forte).
    Il separatore " - " è ammesso solo nelle righe 🆚 (l'emoji conferma le squadre):
    in testo libero è troppo ambiguo (competizioni come "Italy - Serie A", punteggi)."""
    for raw in lines:
        t = _teams_from(raw.strip(), _SEP_VVS)
        if t:
            return t
    return ""


def parse_message(text: str) -> dict:
    """Estrae i campi da un messaggio P.Bet. (emoji o testo)."""
    text = text or ""
    lines = text.strip().split('\n')
    result = {
        'signal_type': '',
        'competition': '',
        'teams': '',
        'score': '',
        'time_': '',
        'quota': '',
        'probability': '',
        'bet_type': 'BACK',
        'live': False,
    }

    if re.search(r'\blive\b', text.lower()):
        result['live'] = True

    # bet_type SOLO da una riga-lato dedicata che contiene ESATTAMENTE un token
    # "Punta"/"Banca"/"Back"/"Lay" (una sola parola), NON da testo libero: così
    # né "Lay Town" (squadra) né "Lay Cup"/"Banca League" (lega/nota) forzano il
    # lato sbagliato (BANCA). Default: BACK.
    for raw in lines:
        toks = re.findall(r'[a-zàèéìòù]+', raw.lower())
        if len(toks) != 1:
            continue
        if toks[0] in ('banca', 'lay'):
            result['bet_type'] = 'LAY'
            break
        if toks[0] in ('punta', 'back'):
            result['bet_type'] = 'BACK'
            break

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if 'P.Bet.' in line:
            m = re.search(r'P\.Bet\.\s+(.+?)(?:\s+[🔊✅🔇]|$)', line)
            if m:
                # togli i token di stato (LIVE/PRE) così resta l'alias puro per il mapping.
                result['signal_type'] = _STATUS_TAIL.sub('', m.group(1).strip()).strip()
            continue
        if '🏆' in line:
            result['competition'] = re.sub(r'[🏆\s]+', ' ', line).strip()
            continue
        if '🆚' in line:
            t = _teams_from(re.sub(r'[🆚]', ' ', line).strip(), _SEP_VVS) \
                or _teams_from(re.sub(r'[🆚]', ' ', line).strip(), _SEP_DASH)
            result['teams'] = t or result['teams']
            continue
        if '⚽' in line:
            result['score'] = re.sub(r'[⚽\s]+', ' ', line).strip()
            continue
        if '⌚' in line:
            result['time_'] = re.sub(r'[⌚\s]+', ' ', line).strip()
            continue
        if '📊' in line or '📈' in line:
            # Riga mista (es. "📈Quota 1,85 📊72%"): estrai sia probabilità sia quota,
            # non fermarti alla prima trovata.
            prob = _extract_probability(line)
            if prob and not result['probability']:
                result['probability'] = prob
            if '📈' in line and not result['quota']:
                # Quota SOLO da marker espliciti (Quota/@ o HT/FT-Prematch): niente
                # numero "nudo" inventato (un "📈 1.2.3" non deve produrre un prezzo).
                q = _extract_quota(line)
                if q:
                    result['quota'] = q
            continue

        # ── righe in testo semplice (senza emoji) ──
        q = _extract_quota(line)
        if q and not result['quota']:
            result['quota'] = q
            continue
        ms = re.search(r'(?:score|risultato)[:\s]+(.+)$', line, re.IGNORECASE)
        if ms:
            result['score'] = ms.group(1).strip()
            continue
        mt = re.search(r'(?:time|tempo|minuto)[:\s]+(.+)$', line, re.IGNORECASE)
        if mt:
            result['time_'] = mt.group(1).strip()
            continue
        prob = _extract_probability(line)
        if prob and not result['probability']:
            result['probability'] = prob
            continue

    # Squadre da testo semplice (solo se non già trovate via 🆚): v/vs preferito su -.
    if not result['teams']:
        result['teams'] = _find_teams(lines)

    return result
