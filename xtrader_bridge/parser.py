"""Parsing dei messaggi Telegram P.Bet. (nessuna dipendenza dalla GUI).

PR-09: parser robusto che gestisce messaggi con emoji **e** in testo semplice.
Estrae signal_type, squadre (normalizzate "Home v Away" da v/vs/-), quota
(virgola o punto), score, minuto, probabilità, bet_type (BACK/LAY) e flag live.
NON inventa dati: i campi non presenti restano vuoti (il blocco dei segnali
incompleti è di recognition/PR-10).
"""

import re

# Separatore squadre: " v ", " vs ", " - " (case-insensitive).
_TEAM_SEP = re.compile(r'^(.+?)\s+(?:vs|v|-)\s+(.+)$', re.IGNORECASE)
_HAS_ALPHA = re.compile(r'[A-Za-zÀ-ÿ]')
_EMOJI_MARKERS = ('🏆', '🆚', '⚽', '⌚', '📊', '📈')

# Prefissi di riga che NON sono squadre (per non scambiare "Score: 1 - 0" per teams).
_LABEL_PREFIXES = (
    'quota', '@', 'time', 'tempo', 'minuto', 'score', 'risultato', 'prob',
    'probabilit', 'probability', 'lega', 'campionato', 'competition', 'p.bet',
    'live', 'pre', 'punta', 'banca', 'back', 'lay',
)


def _looks_like_label(line: str) -> bool:
    low = line.lower()
    first = low.split(' ', 1)[0]
    if ':' in first:                       # "Score:", "Time:", "Quota:" ...
        return True
    return any(low.startswith(p) for p in _LABEL_PREFIXES)


def _normalize_teams(text: str) -> str:
    """Normalizza "A vs B" / "A - B" / "A v B" in "A v B" (se entrambi hanno lettere)."""
    m = _TEAM_SEP.match(text.strip())
    if m and _HAS_ALPHA.search(m.group(1)) and _HAS_ALPHA.search(m.group(2)):
        return f"{m.group(1).strip()} v {m.group(2).strip()}"
    return text.strip()


def _extract_teams(line: str):
    """Estrae le squadre da una riga in testo semplice, evitando le etichette."""
    if _looks_like_label(line) or any(e in line for e in _EMOJI_MARKERS):
        return None
    norm = _normalize_teams(line)
    return norm if ' v ' in norm else None


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

    low = text.lower()
    # bet_type: BANCA/LAY ha priorità su PUNTA/BACK; default BACK.
    if re.search(r'\bbanca\b', low) or re.search(r'\blay\b', low):
        result['bet_type'] = 'LAY'
    elif re.search(r'\bpunta\b', low) or re.search(r'\bback\b', low):
        result['bet_type'] = 'BACK'
    if re.search(r'\blive\b', low):
        result['live'] = True

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if 'P.Bet.' in line:
            m = re.search(r'P\.Bet\.\s+(.+?)(?:\s+[🔊✅🔇]|$)', line)
            if m:
                result['signal_type'] = m.group(1).strip()
            continue
        if '🏆' in line:
            result['competition'] = re.sub(r'[🏆\s]+', ' ', line).strip()
            continue
        if '🆚' in line:
            result['teams'] = _normalize_teams(re.sub(r'[🆚\s]+', ' ', line).strip())
            continue
        if '⚽' in line:
            result['score'] = re.sub(r'[⚽\s]+', ' ', line).strip()
            continue
        if '⌚' in line:
            result['time_'] = re.sub(r'[⌚\s]+', ' ', line).strip()
            continue
        if '📊' in line or '📈' in line:
            mm = re.search(r'([\d.]+)\s*%', line)
            if mm:
                result['probability'] = mm.group(1)
            else:
                mq = re.search(r'([\d]+[.,]\d+)', line)
                if mq and not result['quota']:
                    result['quota'] = mq.group(1).replace(',', '.')
            continue

        # ── righe in testo semplice (senza emoji) ──
        mq = re.search(r'(?:quota|@)[:\s]*([\d]+(?:[.,]\d+)?)', line, re.IGNORECASE)
        if mq and not result['quota']:
            result['quota'] = mq.group(1).replace(',', '.')
            continue
        ms = re.search(r'(?:score|risultato)[:\s]+(.+)$', line, re.IGNORECASE)
        if ms:
            result['score'] = ms.group(1).strip()
            continue
        mt = re.search(r'(?:time|tempo|minuto)[:\s]+(.+)$', line, re.IGNORECASE)
        if mt:
            result['time_'] = mt.group(1).strip()
            continue
        mp = re.search(r'([\d.]+)\s*%', line)
        if mp and not result['probability']:
            result['probability'] = mp.group(1)
            continue
        if not result['teams']:
            t = _extract_teams(line)
            if t:
                result['teams'] = t
                continue

    return result
